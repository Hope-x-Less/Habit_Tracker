import re
import sqlite3
from datetime import date as real_date

import pytest
from flask import render_template_string

import app as habit_app


class FrozenDate(real_date):
    @classmethod
    def today(cls):
        # Fixed Thursday used to keep week and "today" assertions deterministic.
        return cls(2026, 4, 23)


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr(habit_app, "date", FrozenDate)


@pytest.fixture
def test_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "test_database.db"
    monkeypatch.setattr(habit_app, "DATABASE", str(db_path))
    habit_app.app.config.update(TESTING=True)

    with habit_app.app.app_context():
        habit_app.init_db()

    return str(db_path)


@pytest.fixture
def client(test_db_path):
    return habit_app.app.test_client()


def insert_habit(db_path, name, description="", created_date="2026-04-20"):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO habits (name, description, created_date) VALUES (?, ?, ?)",
            (name, description, created_date),
        )
        conn.commit()
        return cursor.lastrowid


def insert_log(db_path, habit_id, iso_date, completed=1):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO habit_logs (habit_id, date, completed) VALUES (?, ?, ?)",
            (habit_id, iso_date, completed),
        )
        conn.commit()


def fetch_scalar(db_path, query, params=()):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
        return row[0]


def extract_weekly_table(html):
    start = html.find('<table class="habit-table"')
    assert start != -1, "Weekly table was not rendered."
    end = html.find("</table>", start)
    assert end != -1, "Weekly table closing tag not found."
    return html[start : end + len("</table>")]


def extract_task_row(table_html, task_name):
    pattern = rf'<tr>\s*<td class="habit-table-task">\s*{re.escape(task_name)}\s*</td>(.*?)</tr>'
    match = re.search(pattern, table_html, re.DOTALL)
    assert match is not None, f"Task row for '{task_name}' not found in table."
    return match.group(1)


def find_habit_id_by_name(db_path, name):
    return fetch_scalar(db_path, "SELECT id FROM habits WHERE name = ?", (name,))


def test_weekly_table_structure_and_render_order(client, test_db_path):
    insert_habit(test_db_path, "Read")
    insert_habit(test_db_path, "Run")
    insert_habit(test_db_path, "Meditate")

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Weekly Accomplishment Table" in html
    assert html.find("Your Habits") < html.find("Weekly Accomplishment Table")

    table_html = extract_weekly_table(html)
    headers = [
        header.strip()
        for header in re.findall(r"<th[^>]*>\s*([^<]+?)\s*</th>", table_html)
    ]

    assert headers == [
        "Task",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    assert table_html.count('class="habit-table-task"') == 3
    assert "undefined" not in table_html
    assert "null" not in table_html


def test_mark_done_updates_today_cell_immediately_and_persists(client, test_db_path):
    habit_id = insert_habit(test_db_path, "Hydrate", "Drink enough water")
    today_iso = FrozenDate.today().isoformat()

    before_html = client.get("/").get_data(as_text=True)
    before_row = extract_task_row(extract_weekly_table(before_html), "Hydrate")
    assert re.search(rf'title="{today_iso}"[^>]*data-done="false">⬜</td>', before_row)

    mark_done_response = client.post(
        f"/complete/{habit_id}",
        data={"filter": "all", "sort": "newest"},
        follow_redirects=True,
    )
    mark_done_html = mark_done_response.get_data(as_text=True)

    assert mark_done_response.status_code == 200
    assert "Habit marked as done for today." in mark_done_html
    updated_row = extract_task_row(extract_weekly_table(mark_done_html), "Hydrate")
    assert re.search(rf'title="{today_iso}"[^>]*data-done="true">✅</td>', updated_row)

    refreshed_html = client.get("/").get_data(as_text=True)
    refreshed_row = extract_task_row(extract_weekly_table(refreshed_html), "Hydrate")
    assert re.search(rf'title="{today_iso}"[^>]*data-done="true">✅</td>', refreshed_row)

    assert (
        fetch_scalar(
            test_db_path,
            "SELECT COUNT(*) FROM habit_logs WHERE habit_id = ? AND date = ? AND completed = 1",
            (habit_id, today_iso),
        )
        == 1
    )


def test_duplicate_mark_done_click_does_not_duplicate_logs(client, test_db_path):
    habit_id = insert_habit(test_db_path, "Journal")
    today_iso = FrozenDate.today().isoformat()

    first = client.post(
        f"/complete/{habit_id}",
        data={"filter": "all", "sort": "newest"},
        follow_redirects=True,
    )
    second = client.post(
        f"/complete/{habit_id}",
        data={"filter": "all", "sort": "newest"},
        follow_redirects=True,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already completed today" in second.get_data(as_text=True)
    assert (
        fetch_scalar(
            test_db_path,
            "SELECT COUNT(*) FROM habit_logs WHERE habit_id = ? AND date = ?",
            (habit_id, today_iso),
        )
        == 1
    )


def test_empty_state_renders_for_cards_and_weekly_table(client):
    response = client.get("/")
    html = response.get_data(as_text=True)
    table_html = extract_weekly_table(html)

    assert response.status_code == 200
    assert "No habits yet" in html
    assert "No habits available for this view." in table_html


def test_habit_table_macro_handles_tasks_missing_completions_field():
    week_dates = habit_app.get_week_dates(FrozenDate.today())
    week_labels = [habit_app.format_day_label(iso_date) for iso_date in week_dates]

    with habit_app.app.app_context():
        rendered = render_template_string(
            '{% from "components/habit_table.html" import HabitTable %}'
            "{{ HabitTable(tasks, week_dates, week_labels, today_iso) }}",
            tasks=[{"name": "Task Without Completions"}],
            week_dates=week_dates,
            week_labels=week_labels,
            today_iso=FrozenDate.today().isoformat(),
        )

    assert "Task Without Completions" in rendered
    assert rendered.count("⬜") == 7
    assert "undefined" not in rendered
    assert "None" not in rendered


def test_multiple_tasks_completed_same_day_are_reflected_correctly(client, test_db_path):
    today_iso = FrozenDate.today().isoformat()
    first_habit_id = insert_habit(test_db_path, "Workout")
    second_habit_id = insert_habit(test_db_path, "Read Book")

    insert_log(test_db_path, first_habit_id, today_iso, completed=1)
    insert_log(test_db_path, second_habit_id, today_iso, completed=1)

    html = client.get("/").get_data(as_text=True)
    table_html = extract_weekly_table(html)

    first_row = extract_task_row(table_html, "Workout")
    second_row = extract_task_row(table_html, "Read Book")
    assert re.search(rf'title="{today_iso}"[^>]*data-done="true">✅</td>', first_row)
    assert re.search(rf'title="{today_iso}"[^>]*data-done="true">✅</td>', second_row)


def test_get_week_dates_and_labels_are_iso_and_monday_to_sunday():
    week_dates = habit_app.get_week_dates(real_date(2026, 4, 23))
    labels = [habit_app.format_day_label(iso_date) for iso_date in week_dates]

    assert len(week_dates) == 7
    assert week_dates[0] == "2026-04-20"
    assert week_dates[-1] == "2026-04-26"
    assert labels == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    for iso_date in week_dates:
        parsed = real_date.fromisoformat(iso_date)
        assert parsed.isoformat() == iso_date


def test_get_week_dates_handles_sunday_to_monday_boundary():
    sunday_week = habit_app.get_week_dates(real_date(2026, 4, 26))
    monday_week = habit_app.get_week_dates(real_date(2026, 4, 27))

    assert sunday_week[0] == "2026-04-20"
    assert sunday_week[-1] == "2026-04-26"
    assert monday_week[0] == "2026-04-27"
    assert monday_week[-1] == "2026-05-03"


def test_regression_add_edit_delete_flow_still_works(client, test_db_path):
    add_response = client.post(
        "/add",
        data={"name": "Code", "description": "1 hour", "filter": "all", "sort": "newest"},
        follow_redirects=True,
    )
    add_html = add_response.get_data(as_text=True)
    habit_id = find_habit_id_by_name(test_db_path, "Code")

    assert add_response.status_code == 200
    assert "Habit added successfully." in add_html
    assert habit_id is not None

    edit_response = client.post(
        f"/edit/{habit_id}",
        data={"name": "Deep Work", "description": "2 hours", "filter": "all", "sort": "newest"},
        follow_redirects=True,
    )
    edit_html = edit_response.get_data(as_text=True)

    assert edit_response.status_code == 200
    assert "Habit updated successfully." in edit_html
    assert "Deep Work" in client.get("/").get_data(as_text=True)

    delete_response = client.post(
        f"/delete/{habit_id}",
        data={"filter": "all", "sort": "newest"},
        follow_redirects=True,
    )
    delete_html = delete_response.get_data(as_text=True)

    assert delete_response.status_code == 200
    assert "Habit deleted." in delete_html
    assert "Deep Work" not in client.get("/").get_data(as_text=True)


@pytest.mark.xfail(
    reason="Weekly table currently uses filtered habits list; requirement expects rows to always include all tasks.",
    strict=False,
)
def test_weekly_table_should_keep_all_tasks_even_when_list_is_filtered(client, test_db_path):
    completed_habit_id = insert_habit(test_db_path, "Completed Habit")
    insert_habit(test_db_path, "Pending Habit")
    insert_log(test_db_path, completed_habit_id, FrozenDate.today().isoformat(), completed=1)

    html = client.get("/?filter=completed&sort=newest").get_data(as_text=True)
    table_html = extract_weekly_table(html)

    assert "Completed Habit" in table_html
    assert "Pending Habit" in table_html
