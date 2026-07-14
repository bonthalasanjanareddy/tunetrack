# TuneTrack — Spotify Listening Habit Analyzer

A multi-user Flask web app that connects to a user's Spotify account and
analyzes their listening history to surface:

- 🎧 Top genres
- 🎤 Favourite artists
- 🎵 Favourite tracks
- ⏰ Peak listening hours (by hour of day)
- 📅 Peak listening days (by day of week)
- 🎚️ Average audio profile (danceability, energy, valence, etc.)

## Project structure

```
tunetrack/
├── app.py                 # Flask app: routes, Spotify OAuth, analysis logic
├── requirements.txt
├── Procfile                # gunicorn start command for Render
├── .env.example
├── templates/
│   ├── index.html          # Login landing page
│   └── dashboard.html      # Main analytics dashboard (Plotly charts)
└── static/
    └── style.css
```

**Important (this fixes your deployment error):** `index.html` and
`dashboard.html` MUST be inside a `templates/` folder at the repo root
(sitting next to `app.py`), and `style.css` MUST be inside `static/`.
Flask looks for these exact folder names by default. If they're flattened
at the repo root instead, Flask throws a `TemplateNotFound` error on Render.

## 1. Create a Spotify Developer App

1. Go to https://developer.spotify.com/dashboard and log in.
2. Click **Create app**.
3. Set **Redirect URI** to `http://127.0.0.1:5000/callback` for local dev.
4. Note your **Client ID** and **Client Secret**.

## 2. Local setup

```bash
git clone https://github.com/bonthalasanjanareddy/tunetrack.git
cd tunetrack
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Create a `.env` file (or set env vars directly) based on `.env.example`.
Then run:

```bash
python app.py
```

Visit `http://127.0.0.1:5000`.

## 3. Deploy to Render.com

1. Push this repo to GitHub with the folder structure above intact.
2. On Render: **New +** → **Web Service** → connect your GitHub repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Add environment variables in Render's dashboard:
   - `SPOTIPY_CLIENT_ID`
   - `SPOTIPY_CLIENT_SECRET`
   - `SPOTIPY_REDIRECT_URI` → `https://<your-render-app>.onrender.com/callback`
   - `FLASK_SECRET_KEY` → any long random string
5. Add the same redirect URI in your Spotify Developer Dashboard app settings.
6. Deploy. Once live, visit your Render URL and click **Connect with Spotify**.

## How multi-user works

Each visitor gets a `uid` stored in their own browser session. Spotify
OAuth tokens are cached per-session via `FlaskSessionCacheHandler`, so
concurrent users on the same deployed instance never see each other's
data — every dashboard call fetches from the currently signed-in
session's token only.

## Notes on Spotify API scopes used

- `user-read-recently-played` — last ~50 played tracks, used for peak
  hour/day analysis.
- `user-top-read` — top artists/tracks over short/medium/long term,
  used for genre and audio-feature analysis.
- `user-read-private` — basic profile (display name) for the header.

## Talking points for interviews

- OAuth 2.0 authorization code flow, per-session token isolation.
- Pandas used for time-series resampling (hour/day extraction) and
  Counter-based genre frequency analysis.
- Plotly.js on the frontend for interactive, responsive charts fed by
  a JSON API endpoint (`/api/analysis`) — clean separation between
  data analysis (backend) and visualization (frontend).
- Deployed on Render with Gunicorn as a production WSGI server.
