# watcher

Watches your screen and coaches you. Runs locally on Windows.

- Every 3s: logs the active app, window title and idle state to SQLite (`data/watcher.db`). No API calls.
- Every 30s: takes a screenshot of the monitor you're on, skipping it if the screen hasn't changed, you're idle, or any private window is visible on that monitor (bank, password manager, DMs, Gmail, `.env`, Chrome incognito via UI Automation, lock screen).
- Every 10 min: sends up to 6 screenshots plus an activity digest to Claude Haiku 5.5, which returns a summary, a focus score and 0–3 tips. Screenshots are deleted after analysis. High-impact tips show up as a Windows toast, at most one every 45 min.

## Use

- `start.bat` / `stop.bat`: run the watcher (under a supervisor that restarts it on crash) + dashboard in the background. Logs: `data/watcher.log` (rotates at 5 MB), `data/supervisor.log`
- `dashboard.bat` — open the live dashboard at http://127.0.0.1:8765 (pause/resume, check now, today's feed)
- `report.bat`: today's HTML report with deep-work blocks, where focus leaked, a 7-day trend and grouped tips (`report.bat 2026-11-10` for another day, `--no-ai` to skip the debrief)
- `install-autostart.bat` — start at login (already installed; remove `watcher.bat` from shell:startup to undo)
- `.venv\Scripts\python watcher.py --once` — one immediate analysis, for testing
- Copy `profile.example.md` to `profile.md` and edit it to change what the coach knows about you.

Settings are env vars in `.env`: `SHOT_SECONDS`, `ANALYZE_SECONDS`, `IDLE_SECONDS`, `MAX_SHOTS_PER_ANALYSIS`, `KEEP_SCREENSHOTS=1`, `WATCHER_NOTIFY=1` (desktop toasts, off by default), `NOTIFY_COOLDOWN`, `PRIVATE_PATTERN` (replaces the built-in list in `common.py`), `WATCHER_MODEL`, `SHOT_MAX_AGE` (unanalyzed screenshots deleted after this, default 3600), `RAW_RETENTION_DAYS` (raw 3s rows kept, default 30; daily totals kept forever), `WATCHER_DASH_PORT`, `WATCHER_DATA_DIR` (use a different data folder, e.g. for tests).

## Tests

- `.venv\Scripts\python -m pytest tests`: 96 unit tests (privacy filter, capture, analysis with a mocked model, migrations, report, local dashboard). They run on a temp data dir and never touch `data/`.
- `cd web && pnpm test:e2e`: 23 Playwright tests for both dashboards against throwaway servers (PGlite instead of Neon, fake data from `tests/seed_demo.py`).
- `cd web && pnpm exec playwright test -c playwright.demo.config.ts` re-records `docs/videos/`.

## Cloud dashboard

Deploy `web/` to Vercel. Set `REQUIRE_LOGIN=1`, `DASHBOARD_PASSWORD` and `AUTH_SECRET` so the dashboard needs a password (without them it is public). Source in `web/` (Next.js + Neon project `watcher`). The PC pushes status, summaries, tips and app times every 15s to `/api/ingest` (`WATCHER_CLOUD_URL` + `INGEST_TOKEN` in `.env`). Screenshots are never uploaded. Pause and Check now from the site reach the PC on its next sync. Deploy: `cd web && vercel deploy --prod`.
