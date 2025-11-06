# Enhanced Admin Website (backend)

This repository contains a tiny Flask backend used by the admin UI in `static/index.html`.

Quick notes for deploying to Railway

1. Railway will detect Python when `requirements.txt` is present. I've included a `Procfile` so the web process runs with `gunicorn`:

   - `web: gunicorn backend:app --log-file -`

   `backend:app` references the `app` object in `backend.py`.

2. Files added to help deployment:

   - `requirements.txt` — packages required to run the app (Flask, spotipy, psycopg2-binary, gunicorn, python-dotenv).
   - `Procfile` — instructs Railway to run gunicorn to serve the Flask app.
   - `runtime.txt` — optional Python runtime (Heroku-style). Railway may ignore it, but it's harmless.
   - `.env.example` — example env vars for local development (DO NOT commit a real `.env`).

3. Required environment variables

   - `DATABASE_URL` (or `RAILWAY_DATABASE_URL`) — Postgres connection string. Railway provides this when adding a Postgres plugin.
   - `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` — for Spotify API lookups (optional if you don't need lookups)
   - `SPOTIFY_REFRESH_TOKEN` — optional; if provided will be used to refresh Spotify token.
   - `BASE_URL` — used to build redirect URI (can be `https://<your-railway-url>` or `http://localhost:5000` for local dev)
   - `PORT` — Railway provides this automatically; the app reads `PORT` (defaults to 5000 locally).
   - `FLASK_DEBUG` — optional, set to `1` to enable debug locally.

4. Local testing

   - Create a virtualenv and install requirements:

     ```bash
     python -m venv venv
     source venv/bin/activate
     pip install -r requirements.txt
     cp .env.example .env
     # edit .env to add real values
     export $(cat .env | xargs)
     python backend.py
     ```

   - Or use gunicorn for a production-like server (the Procfile uses this):

     ```bash
     gunicorn backend:app --bind 0.0.0.0:5000
     ```

5. Deploying on Railway

   - Create a new project on Railway and connect this repository, or push these files to a branch and connect the repo.
   - Add a Postgres plugin (if needed) or provide `DATABASE_URL` in Environment variables.
   - Add the Spotify secrets as environment variables in Railway.
   - Railway will install `requirements.txt` and run the `Procfile` command.

If you'd like, I can also:

- Add a tiny `Makefile` or `start.sh` for local development convenience.
- Add a health-check endpoint for Railway to probe.

