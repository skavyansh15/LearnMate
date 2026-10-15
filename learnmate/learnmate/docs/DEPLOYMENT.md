# Deployment guide (Render, free tier) - not yet performed

Nothing here has been deployed or tested on a host. Do a dry run before the demo.

1. Push the project to GitHub (`.env` and `data/` are git-ignored; the demo video is ~4.5 MB and is included).
2. Render -> **New Web Service** -> your repo. Runtime **Python 3.11 or 3.12**.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60` (also in `Procfile`).
   Keep **one worker**: rate limits and the file lock live inside the process.
5. Environment variables (Render dashboard -> Environment):
   - `SECRET_KEY` = long random text (required; otherwise everyone is logged out on each restart)
   - `COOKIE_SECURE` = `1`
   - `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` (optional: skip them to run the public demo in demo mode)
   - `DAILY_AI_CALLS` (e.g. `30`) to cap spending per visitor
6. Open the URL, run the demo script from the README, check `/api/health`.

**Storage warning:** free instances have a temporary disk, so uploaded courses disappear on restart/redeploy. For a real deployment attach a persistent disk and set `DATA_DIR` to it. The demo course is part of the repo and always available.

**Cost safety:** set a spending limit in your AI provider's console as well; the app's limits are per visitor, not global.

**Other hosts** (Railway, PythonAnywhere, a VPS): any host that runs `gunicorn app:app` works; serve over HTTPS and set the same variables.
