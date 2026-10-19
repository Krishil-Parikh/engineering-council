# Project: Habitly, a habit tracker with a CLI and a small web API

## Problem

I want to track daily habits (drink water, read 20 pages, exercise) and see whether I am keeping them up. Today I use a notes file and it
tells me nothing: I cannot see streaks, I forget to log, and I have no weekly picture.

Build a small, dependable habit tracker I can use from the terminal and from a browser on my own machine.

## What it must do

1. **Habits.** Create, list, rename and archive habits. A habit has a name, an optional daily target (for example 8 glasses), and a start date.
2. **Check-ins.** Log a check-in for a habit on a date (default today), with an optional count. Logging twice for the same day updates it. I can
   undo the last check-in.
3. **Streaks and stats.** For each habit show the current streak, the longest streak, the completion rate over the last 7 and 30 days, and a
   one-line text bar chart of the last 14 days.
4. **Weekly report.** A command that prints a weekly summary across all habits (best habit, worst habit, missed days) and can export it as
   Markdown or CSV.
5. **Local web API.** A small HTTP JSON API on localhost (FastAPI) with the same operations: list/create habits, post a check-in, get stats,
   get the weekly report. It must reject bad input with clear 4xx errors.
6. **Reminders.** A command that lists habits not yet checked in today, so I can run it from a scheduler. No notifications, just the list and a
   non-zero exit code when something is missing.

## Constraints

- Python 3.11, standard library plus FastAPI/uvicorn for the API. No other third-party services, no accounts, no network calls.
- Storage is a single SQLite file; the path is configurable by an environment variable (default `~/.habitly/habitly.db`).
- The CLI is `habitly <command>` (argparse). Everything the CLI does goes through one shared service layer that the API also uses, so the two
  cannot disagree.
- All dates are local calendar days. Streak logic must handle gaps, the current day not yet being logged, and habits created mid-history.
- Tests with pytest, using a temporary database. `python -m pytest -q` must pass offline, and each feature has tests.

## Done means

- `habitly add "Read" --target 20`, `habitly checkin Read --count 25`, `habitly stats`, `habitly report --format md`, `habitly due`, and
  `habitly serve` all work.
- A README explains install, the commands, the API endpoints, and how to run the tests.
- Verification command: `python -m pytest -q`
