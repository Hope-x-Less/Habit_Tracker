from datetime import date, timedelta
import sqlite3

from flask import Flask, flash, g, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = "habit-tracker-dev-secret"
DATABASE = "database.db"
VALID_FILTERS = {"all", "completed", "pending"}
VALID_SORTS = {"newest", "streak"}


def get_db():
    """Return a database connection for the current request."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    """Close the database connection at the end of the request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create required tables if they do not exist."""
    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_date DATE NOT NULL
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            date DATE NOT NULL,
            completed BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
        )
        """
    )

    # Keep one record per habit per day, then enforce that rule at DB level.
    db.execute(
        """
        DELETE FROM habit_logs
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM habit_logs
            GROUP BY habit_id, date
        )
        """
    )

    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_habit_logs_habit_day
        ON habit_logs (habit_id, date)
        """
    )

    db.commit()


def calculate_current_streak(db, habit_id):
    """Return consecutive completed days ending today for one habit."""
    completed_dates = {
        row["date"]
        for row in db.execute(
            "SELECT date FROM habit_logs WHERE habit_id = ? AND completed = 1",
            (habit_id,),
        ).fetchall()
    }

    streak = 0
    current_day = date.today()

    while current_day.isoformat() in completed_dates:
        streak += 1
        current_day -= timedelta(days=1)

    return streak


def build_weekly_chart_data(db, base_date=None):
    """Return labels, counts and per-day completed task names for the week containing `base_date`.

    `base_date` may be an ISO date string or a date object. If None, uses today.
    """
    if isinstance(base_date, str):
        base_date = date.fromisoformat(base_date)

    # normalize to ISO strings ordered Monday->Sunday using get_week_dates
    iso_week_dates = get_week_dates(base_date if base_date is None else base_date)
    week_start = iso_week_dates[0]
    week_end = iso_week_dates[-1]

    rows = db.execute(
        """
        SELECT date, COUNT(*) AS completed_count
        FROM habit_logs
        WHERE completed = 1 AND date BETWEEN ? AND ?
        GROUP BY date
        """,
        (week_start, week_end),
    ).fetchall()

    completed_by_date = {row["date"]: row["completed_count"] for row in rows}

    # Build mapping of iso_date -> list of habit names completed that date
    name_rows = db.execute(
        """
        SELECT hl.date AS date, h.name AS name
        FROM habit_logs hl
        JOIN habits h ON h.id = hl.habit_id
        WHERE hl.completed = 1 AND hl.date BETWEEN ? AND ?
        ORDER BY hl.date, h.id
        """,
        (week_start, week_end),
    ).fetchall()

    tasks_by_date = {}
    for r in name_rows:
        tasks_by_date.setdefault(r["date"], []).append(r["name"])

    counts = [completed_by_date.get(d, 0) for d in iso_week_dates]

    # previous week totals for comparison
    week_start_dt = date.fromisoformat(week_start)
    prev_start = (week_start_dt - timedelta(days=7)).isoformat()
    prev_end = (week_start_dt - timedelta(days=1)).isoformat()
    prev_total_row = db.execute(
        "SELECT COUNT(*) FROM habit_logs WHERE completed = 1 AND date BETWEEN ? AND ?",
        (prev_start, prev_end),
    ).fetchone()
    prev_total = prev_total_row[0] if prev_total_row is not None else 0

    total_this_week = sum(counts)

    percent_change = None
    if prev_total:
        percent_change = round((total_this_week - prev_total) / prev_total * 100, 1)

    return {
        "labels": [date.fromisoformat(d).strftime("%a") for d in iso_week_dates],
        "iso_dates": iso_week_dates,
        "counts": counts,
        "start_date": week_start,
        "end_date": week_end,
        "tasks_by_date": tasks_by_date,
        "total_this_week": total_this_week,
        "total_prev_week": prev_total,
        "percent_change": percent_change,
    }


def get_start_of_week(base_date):
    """Return Monday for the week containing base_date."""
    return base_date - timedelta(days=base_date.weekday())


def get_week_dates(base_date=None):
    """Return current week dates from Monday to Sunday as ISO strings."""
    if base_date is None:
        base_date = date.today()

    start_of_week = get_start_of_week(base_date)
    return [
        (start_of_week + timedelta(days=offset)).isoformat()
        for offset in range(7)
    ]


def format_day_label(iso_date):
    """Return a full weekday label for an ISO date."""
    return date.fromisoformat(iso_date).strftime("%A")


def sanitize_view_options(status_filter, sort_by):
    """Return safe filter/sort values for list view controls."""
    if status_filter not in VALID_FILTERS:
        status_filter = "all"
    if sort_by not in VALID_SORTS:
        sort_by = "newest"
    return status_filter, sort_by


def get_view_options_from_args():
    """Read filter/sort options from query string."""
    return sanitize_view_options(
        request.args.get("filter", "all"),
        request.args.get("sort", "newest"),
    )


def get_view_options_from_form():
    """Read filter/sort options from form data."""
    return sanitize_view_options(
        request.form.get("filter", "all"),
        request.form.get("sort", "newest"),
    )


def redirect_home(status_filter, sort_by):
    """Redirect to homepage while keeping current list view options."""
    return redirect(url_for("home", filter=status_filter, sort=sort_by))


def fetch_habits_with_stats(db, today, week_start, week_end):
    """Load habits with completion stats used by the homepage cards."""
    # One grouped query keeps the homepage fast even as logs grow.
    habit_rows = db.execute(
        """
        SELECT
            habits.id,
            habits.name,
            habits.description,
            habits.created_date,
            COALESCE(SUM(CASE WHEN habit_logs.completed = 1 THEN 1 ELSE 0 END), 0) AS total_completed,
            COALESCE(
                SUM(
                    CASE
                        WHEN habit_logs.completed = 1
                        AND habit_logs.date BETWEEN ? AND ?
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS completed_last_7_days,
            COALESCE(MAX(CASE WHEN habit_logs.date = ? AND habit_logs.completed = 1 THEN 1 ELSE 0 END), 0) AS completed_today
        FROM habits
        LEFT JOIN habit_logs ON habit_logs.habit_id = habits.id
        GROUP BY habits.id
        ORDER BY habits.id DESC
        """,
        (week_start, week_end, today),
    ).fetchall()

    habits = []
    for row in habit_rows:
        habit = dict(row)
        habit["completed_today"] = bool(habit["completed_today"])
        habit["current_streak"] = calculate_current_streak(db, row["id"])
        habits.append(habit)

    return habits


def attach_weekly_completions(db, habits, week_dates):
    """Attach a non-breaking completions map keyed by ISO date to each habit."""
    if not habits:
        return habits

    habit_ids = [habit["id"] for habit in habits]
    placeholders = ", ".join(["?"] * len(habit_ids))

    rows = db.execute(
        f"""
        SELECT habit_id, date
        FROM habit_logs
        WHERE completed = 1
          AND habit_id IN ({placeholders})
          AND date BETWEEN ? AND ?
        """,
        (*habit_ids, week_dates[0], week_dates[-1]),
    ).fetchall()

    completions_by_habit = {habit_id: {} for habit_id in habit_ids}
    for row in rows:
        completions_by_habit[row["habit_id"]][row["date"]] = True

    for habit in habits:
        habit["completions"] = completions_by_habit.get(habit["id"], {})

    return habits


def filter_and_sort_habits(habits, status_filter, sort_by):
    """Apply optional list filters and sorting choices."""
    if status_filter == "completed":
        habits = [habit for habit in habits if habit["completed_today"]]
    elif status_filter == "pending":
        habits = [habit for habit in habits if not habit["completed_today"]]

    if sort_by == "streak":
        # Tie-breakers keep ordering stable when streaks match.
        habits = sorted(
            habits,
            key=lambda habit: (habit["current_streak"], habit["total_completed"], habit["id"]),
            reverse=True,
        )
    else:
        habits = sorted(habits, key=lambda habit: habit["id"], reverse=True)

    return habits


@app.route("/")
def home():
    """Show all habits on the homepage."""
    db = get_db()
    status_filter, sort_by = get_view_options_from_args()
    # Optional `week` query param accepts an ISO date within the week to view.
    week_param = request.args.get("week")
    if week_param:
        try:
            base_date = date.fromisoformat(week_param)
        except Exception:
            base_date = date.today()
    else:
        base_date = date.today()

    today = date.today().isoformat()
    weekly_chart = build_weekly_chart_data(db, base_date=base_date)
    week_start = weekly_chart["start_date"]
    week_end = weekly_chart["end_date"]

    # previous / next week controls
    ws_dt = date.fromisoformat(week_start)
    prev_week = (ws_dt - timedelta(days=7)).isoformat()
    next_week = (ws_dt + timedelta(days=7)).isoformat()

    habits = fetch_habits_with_stats(db, today, week_start, week_end)
    habits = filter_and_sort_habits(habits, status_filter, sort_by)

    # When viewing a specific week, show that week's table too
    habit_table_week_dates = get_week_dates(base_date)
    habit_table_week_labels = [format_day_label(iso_date) for iso_date in habit_table_week_dates]
    habits = attach_weekly_completions(db, habits, habit_table_week_dates)

    return render_template(
        "index.html",
        habits=habits,
        weekly_chart=weekly_chart,
        status_filter=status_filter,
        sort_by=sort_by,
        habit_table_week_dates=habit_table_week_dates,
        habit_table_week_labels=habit_table_week_labels,
        today_iso=today,
        prev_week=prev_week,
        next_week=next_week,
    )


@app.route("/add", methods=["GET", "POST"])
def add_habit():
    """Handle new habit submission from the homepage form."""
    if request.method == "GET":
        return redirect(url_for("home"))

    status_filter, sort_by = get_view_options_from_form()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()

    if not name:
        flash("Habit name is required.", "error")
        return redirect_home(status_filter, sort_by)

    db = get_db()
    db.execute(
        "INSERT INTO habits (name, description, created_date) VALUES (?, ?, ?)",
        (name, description, date.today().isoformat()),
    )
    db.commit()
    flash("Habit added successfully.", "success")
    return redirect_home(status_filter, sort_by)


@app.route("/delete/<int:id>", methods=["POST"])
def delete_habit(id):
    """Delete a habit by ID."""
    status_filter, sort_by = get_view_options_from_form()
    db = get_db()
    result = db.execute("DELETE FROM habits WHERE id = ?", (id,))
    db.commit()

    if result.rowcount:
        flash("Habit deleted.", "success")
    else:
        flash("Habit not found.", "error")

    return redirect_home(status_filter, sort_by)


@app.route("/complete/<int:id>", methods=["POST"])
def complete_habit(id):
    """Mark a habit as completed for today, only once."""
    status_filter, sort_by = get_view_options_from_form()
    db = get_db()

    habit = db.execute("SELECT id FROM habits WHERE id = ?", (id,)).fetchone()
    if habit is None:
        flash("Habit not found.", "error")
        return redirect_home(status_filter, sort_by)

    today = date.today().isoformat()
    existing_log = db.execute(
        "SELECT id, completed FROM habit_logs WHERE habit_id = ? AND date = ?",
        (id, today),
    ).fetchone()

    if existing_log is None:
        db.execute(
            "INSERT INTO habit_logs (habit_id, date, completed) VALUES (?, ?, 1)",
            (id, today),
        )
        db.commit()
        flash("Habit marked as done for today.", "success")
    elif existing_log["completed"] == 0:
        db.execute("UPDATE habit_logs SET completed = 1 WHERE id = ?", (existing_log["id"],))
        db.commit()
        flash("Habit marked as done for today.", "success")
    else:
        flash("This habit is already completed today.", "info")

    return redirect_home(status_filter, sort_by)


@app.route("/edit/<int:id>", methods=["GET", "POST"])
def edit_habit(id):
    """Edit habit name and description."""
    db = get_db()
    habit_row = db.execute(
        "SELECT id, name, description FROM habits WHERE id = ?",
        (id,),
    ).fetchone()

    if habit_row is None:
        if request.method == "POST":
            status_filter, sort_by = get_view_options_from_form()
        else:
            status_filter, sort_by = get_view_options_from_args()
        flash("Habit not found.", "error")
        return redirect_home(status_filter, sort_by)

    if request.method == "POST":
        status_filter, sort_by = get_view_options_from_form()
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()

        if not name:
            flash("Habit name is required.", "error")
            habit = dict(habit_row)
            habit["name"] = name
            habit["description"] = description
            return render_template(
                "edit.html",
                habit=habit,
                status_filter=status_filter,
                sort_by=sort_by,
            )

        db.execute(
            "UPDATE habits SET name = ?, description = ? WHERE id = ?",
            (name, description, id),
        )
        db.commit()
        flash("Habit updated successfully.", "success")
        return redirect_home(status_filter, sort_by)

    status_filter, sort_by = get_view_options_from_args()
    return render_template(
        "edit.html",
        habit=dict(habit_row),
        status_filter=status_filter,
        sort_by=sort_by,
    )


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
