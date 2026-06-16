# TuneTrack — Multi-user Spotify Listening Habit Analyzer

A Flask web app where each visitor logs in with their own Spotify account
and sees a live, personal dashboard of their listening habits. Nothing is
saved to disk per-user except a temporary auth token cache.

## What changed from the script version

- No more static `spotify_dashboard.html` file — charts render live in the browser
  via Plotly's JavaScript, generated fresh from the Flask backend on each visit.
- Multiple people can use it. Each person's Spotify login is isolated to their
  own browser session (Flask session + per-user token cache file).
- Genre data and "audio features" (mood/energy) are NOT included — Spotify
  deprecated those endpoints for all new apps in late 2024. This version uses
  what's still available: timestamps, play counts, popularity, duration, top
  artists/songs.

---

## 1. Local setup

```bash
cd tunetrack-web
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your real Spotify Client ID/Secret (same ones from your
existing Developer Dashboard app). Generate a random string for
`FLASK_SECRET_KEY` (any long random text works, e.g. run
`python -c "import secrets; print(secrets.token_hex(16))"`).

Run it:

```bash
python app.py
```

Open `http://localhost:8888` in your browser.

---

## 2. Add friends as allowed users (required while in Development Mode)

Spotify restricts new apps to a max of 25 manually-approved users until you
apply for extended quota. To let friends log in:

1. Go to your app on `developer.spotify.com/dashboard`
2. Settings → User Management
3. Add each friend's **exact Spotify account email** (the one tied to their
   Spotify login) — they'll get an email/notification accepting access.
4. They can then visit your deployed link and click "Connect with Spotify."

Without this step, friends will see an error saying the app is restricted.

---

## 3. Deploying online (so others can use the live link)

### Option: Render.com (free tier, easiest)

1. Push this folder to a GitHub repo
2. Go to render.com → New → Web Service → connect your repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variables in Render's dashboard (same as your `.env`):
   `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`,
   `FLASK_SECRET_KEY`
6. Once deployed, Render gives you a URL like `https://tunetrack.onrender.com`

### Update your Spotify app's redirect URI

After deploying, go back to `developer.spotify.com/dashboard` → your app →
Settings → Redirect URIs → add:

```
https://tunetrack.onrender.com/callback
```

(Use your actual Render URL.) Then update `SPOTIPY_REDIRECT_URI` in Render's
environment variables to match exactly — including `https://` and the
`/callback` path, no trailing slash.

You can keep both the localhost and the live redirect URI registered at the
same time, so local testing still works too.

---

## 4. Talking points for interviews

- "Built a multi-tenant Flask web app with OAuth 2.0, where each user
  authenticates with their own Spotify account and gets an isolated session
  with personalized data — not a single shared dataset."
- "Handled a live API deprecation: Spotify removed the audio-features
  endpoint for new developer apps mid-project, so I redesigned the analysis
  around timestamp and play-count features instead of relying on
  pre-computed mood scores."
- "Deployed end-to-end: Flask backend, server-side chart generation with
  Plotly, hosted live on Render."
