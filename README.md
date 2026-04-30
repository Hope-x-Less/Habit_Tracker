# Habit Tracker

A simple and polished Flask web application for tracking daily habits, monitoring streaks, and reviewing weekly completion trends.

## Features

- Add, edit, and delete habits
- Mark habits as completed for the current day
- Prevent duplicate completion logs for the same habit/day
- View current streak, total completed days, and last-7-day completion count per habit
- Filter habits by status: all, completed today, pending today
- Sort habits by newest or highest streak
- Weekly accomplishment table (Monday to Sunday)
- Weekly bar chart powered by Chart.js
 - Navigate by week to view past/future weekly progress
 - Hover chart bars to see tasks completed on that day
 - Weekly summary comparing this week to the previous week
- Flash messages for successful and error states
- Automated tests with pytest

## Tech Stack

- Python: Core programming language
- Flask: Web framework and routing
- Jinja2: Server-side HTML templating
- SQLite: Lightweight local relational database
- HTML/CSS: User interface layout and styling
- Chart.js: Weekly progress chart rendering
- pytest: Test framework for regression and behavior checks

## Project Structure

```text
Habbit Tracker/
|-- app.py
|-- database.db
|-- pytest.ini
|-- README.md
|-- .gitignore
|-- static/
|   `-- style.css
|-- templates/
|   |-- index.html
|   |-- add.html
|   |-- edit.html
|   `-- components/
|       `-- habit_table.html
`-- tests/
    `-- test_habit_tracker.py
```

### Folder Responsibilities

- `app.py`: Flask application entry point, routes, database setup, and business logic
- `static/`: Frontend static assets (CSS)
- `templates/`: Jinja HTML templates used by Flask views
- `templates/components/`: Reusable template components/macros
- `tests/`: Automated test suite for core behavior and regressions

## Installation

1. Clone the repository.
2. Open the project directory.
3. Create a virtual environment:

   ```powershell
   python -m venv .venv
   ```

4. Activate the environment (Windows PowerShell):

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

5. Install dependencies:

   ```powershell
   pip install flask pytest
   ```

## Running Locally

1. Start the Flask app:

   ```powershell
   python app.py
   ```

2. Open your browser at:

   ```text
   http://127.0.0.1:5000
   ```

## Running Tests

```powershell
pytest
```

## Usage

- Add a new habit from the "Add Habit" form.
- Use "Mark as Done" to complete a habit for today.
- Use filter and sort controls to refine the list view.
- Edit or delete habits from each habit card.
- Review the weekly chart and weekly accomplishment table to track consistency.

## Notes

- The SQLite database file (`database.db`) is created/updated locally.
- This project currently stores data locally (no external database required).
- Keep secrets and environment-specific settings out of version control.
