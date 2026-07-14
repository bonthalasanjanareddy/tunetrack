"""
TuneTrack - Spotify Listening Habit Analyzer
==============================================
A multi-user Flask web app that connects to a user's Spotify account,
pulls their listening history (recently played, top tracks, top artists),
and analyzes it to surface music preferences, genre breakdowns,
favourite artists, and peak listening times.

Stack: Flask, Spotipy, Pandas, Plotly, Gunicorn
Deploy target: Render.com
"""

import os
import uuid
from datetime import datetime
from collections import Counter

from flask import Flask, session, request, redirect, url_for, render_template, jsonify
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import FlaskSessionCacheHandler
import pandas as pd
import plotly.express as px
import plotly.utils
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

# Spotify API credentials - set these as environment variables on Render
SPOTIPY_CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET")
SPOTIPY_REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:5000/callback")

# Validate that required credentials are set
if not SPOTIPY_CLIENT_ID or not SPOTIPY_CLIENT_SECRET:
    raise ValueError(
        "Missing Spotify API credentials! Please set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET "
        "environment variables. You can do this by:\n"
        "1. Creating a .env file in your project root with:\n"
        "   SPOTIPY_CLIENT_ID=your_client_id\n"
        "   SPOTIPY_CLIENT_SECRET=your_client_secret\n"
        "   SPOTIPY_REDIRECT_URI=http://127.0.0.1:5000/callback\n"
        "2. Get credentials from: https://developer.spotify.com/dashboard"
    )

SCOPE = "user-read-recently-played user-top-read user-read-private"


def create_spotify_oauth():
    """Creates a per-session SpotifyOAuth object.

    Using FlaskSessionCacheHandler + a session-scoped cache path keeps
    each logged-in user's token isolated from other concurrent users
    (this is what makes the app safely multi-user on a shared server).
    """
    cache_handler = FlaskSessionCacheHandler(session)
    return SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        cache_handler=cache_handler,
        show_dialog=True,
    )


def get_spotify_client():
    """Returns an authenticated Spotipy client for the current session, or None."""
    cache_handler = FlaskSessionCacheHandler(session)
    sp_oauth = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SCOPE,
        cache_handler=cache_handler,
    )
    token_info = cache_handler.get_cached_token()
    if not token_info:
        return None
    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
    return spotipy.Spotify(auth=token_info["access_token"], requests_timeout=15)


# ---------------------------------------------------------------------------
# Routes: Auth
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    sp = get_spotify_client()
    if sp:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login")
def login():
    if "uid" not in session:
        session["uid"] = str(uuid.uuid4())
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    sp_oauth = create_spotify_oauth()
    code = request.args.get("code")
    if not code:
        return redirect(url_for("index"))
    sp_oauth.get_access_token(code, as_dict=False)
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/test")
def api_test():
    """Simple test endpoint to verify API is working."""
    sp = get_spotify_client()
    if not sp:
        return jsonify({"status": "error", "message": "not_authenticated"}), 401
    
    try:
        user = sp.current_user()
        return jsonify({
            "status": "success",
            "user": user.get("display_name", "Unknown"),
            "message": "Spotify connection working!"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes: Dashboard
# ---------------------------------------------------------------------------
@app.route("/dashboard")
def dashboard():
    sp = get_spotify_client()
    if not sp:
        return redirect(url_for("login"))

    user = sp.current_user()
    return render_template("dashboard.html", user=user)


@app.route("/api/analysis")
def api_analysis():
    """Returns all analyzed listening-habit data as JSON for the dashboard charts."""
    sp = get_spotify_client()
    if not sp:
        return jsonify({"error": "not_authenticated"}), 401

    time_range = request.args.get("time_range", "medium_term")  # short_term / medium_term / long_term

    try:
        print(f"[API] Fetching recently played tracks...")
        recent = fetch_recently_played(sp)
        print(f"[API] Fetched {len(recent)} recent tracks")
        
        print(f"[API] Fetching top tracks (time_range={time_range})...")
        top_tracks = fetch_top_tracks(sp, time_range)
        print(f"[API] Fetched {len(top_tracks)} top tracks")
        
        print(f"[API] Fetching top artists (time_range={time_range})...")
        top_artists = fetch_top_artists(sp, time_range)
        print(f"[API] Fetched {len(top_artists)} top artists")

        print(f"[API] Analyzing data...")
        result = {
            "peak_hours": analyze_peak_hours(recent),
            "peak_days": analyze_peak_days(recent),
            "top_genres": analyze_genres(top_artists),
            "top_artists": analyze_top_artists(top_artists),
            "top_tracks": analyze_top_tracks(top_tracks),
            "audio_features": analyze_audio_features(sp, top_tracks),
            "summary": build_summary(recent, top_tracks, top_artists),
        }
        print(f"[API] Analysis complete, returning data")
        return jsonify(result)
    except Exception as e:
        print(f"[API ERROR] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_recently_played(sp, limit=50):
    """Fetch recently played tracks (Spotify API caps this at 50 items)."""
    results = sp.current_user_recently_played(limit=limit)
    items = results.get("items", [])
    rows = []
    for item in items:
        track = item["track"]
        rows.append({
            "played_at": item["played_at"],
            "track_name": track["name"],
            "artist_name": track["artists"][0]["name"] if track["artists"] else "Unknown",
            "artist_id": track["artists"][0]["id"] if track["artists"] else None,
            "duration_ms": track["duration_ms"],
            "popularity": track["popularity"],
        })
    return pd.DataFrame(rows)


def fetch_top_tracks(sp, time_range="medium_term", limit=50):
    results = sp.current_user_top_tracks(limit=limit, time_range=time_range)
    rows = []
    for rank, track in enumerate(results.get("items", []), start=1):
        rows.append({
            "rank": rank,
            "track_id": track["id"],
            "track_name": track["name"],
            "artist_name": track["artists"][0]["name"] if track["artists"] else "Unknown",
            "album": track["album"]["name"],
            "popularity": track["popularity"],
            "duration_ms": track["duration_ms"],
        })
    return pd.DataFrame(rows)


def fetch_top_artists(sp, time_range="medium_term", limit=50):
    results = sp.current_user_top_artists(limit=limit, time_range=time_range)
    rows = []
    for rank, artist in enumerate(results.get("items", []), start=1):
        rows.append({
            "rank": rank,
            "artist_id": artist["id"],
            "artist_name": artist["name"],
            "genres": artist["genres"],
            "popularity": artist["popularity"],
            "followers": artist["followers"]["total"],
            "image": artist["images"][0]["url"] if artist["images"] else None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Analysis functions (Pandas)
# ---------------------------------------------------------------------------
def analyze_peak_hours(df):
    """Which hours of the day the user listens to music most."""
    if df.empty:
        return {"labels": [], "values": []}
    df = df.copy()
    df["played_at"] = pd.to_datetime(df["played_at"])
    df["hour"] = df["played_at"].dt.hour
    counts = df["hour"].value_counts().sort_index()
    # ensure all 24 hours are represented
    full = pd.Series([counts.get(h, 0) for h in range(24)], index=range(24))
    return {"labels": [f"{h:02d}:00" for h in range(24)], "values": full.tolist()}


def analyze_peak_days(df):
    """Which days of the week the user listens to music most."""
    if df.empty:
        return {"labels": [], "values": []}
    df = df.copy()
    df["played_at"] = pd.to_datetime(df["played_at"])
    df["day"] = df["played_at"].dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    counts = df["day"].value_counts().reindex(order, fill_value=0)
    return {"labels": order, "values": counts.tolist()}


def analyze_genres(artists_df, top_n=10):
    """Flattens each artist's genre list and counts frequency across top artists."""
    if artists_df.empty:
        return {"labels": [], "values": []}
    all_genres = []
    for genres in artists_df["genres"]:
        all_genres.extend(genres)
    if not all_genres:
        return {"labels": [], "values": []}
    counter = Counter(all_genres)
    top = counter.most_common(top_n)
    return {"labels": [g[0] for g in top], "values": [g[1] for g in top]}


def analyze_top_artists(artists_df, top_n=10):
    if artists_df.empty:
        return []
    subset = artists_df.head(top_n)
    return subset[["rank", "artist_name", "popularity", "followers", "image", "genres"]].to_dict(orient="records")


def analyze_top_tracks(tracks_df, top_n=10):
    if tracks_df.empty:
        return []
    subset = tracks_df.head(top_n)
    return subset[["rank", "track_name", "artist_name", "album", "popularity"]].to_dict(orient="records")


def analyze_audio_features(sp, tracks_df, sample_size=30):
    """Average audio features (danceability, energy, valence, etc.) across top tracks."""
    if tracks_df.empty:
        return {}
    track_ids = tracks_df["track_id"].dropna().head(sample_size).tolist()
    if not track_ids:
        return {}
    try:
        features = sp.audio_features(track_ids)
        features = [f for f in features if f]  # drop None entries
        if not features:
            return {}
        fdf = pd.DataFrame(features)
        keys = ["danceability", "energy", "valence", "acousticness",
                "instrumentalness", "liveness", "speechiness", "tempo"]
        keys = [k for k in keys if k in fdf.columns]
        avg = fdf[keys].mean().round(3).to_dict()
        return avg
    except spotipy.exceptions.SpotifyException:
        # audio-features endpoint occasionally restricted on some app tiers
        return {}


def build_summary(recent_df, tracks_df, artists_df):
    total_minutes = 0
    if not recent_df.empty:
        total_minutes = round(recent_df["duration_ms"].sum() / 60000, 1)

    top_artist = artists_df.iloc[0]["artist_name"] if not artists_df.empty else "N/A"
    top_track = tracks_df.iloc[0]["track_name"] if not tracks_df.empty else "N/A"

    return {
        "recent_tracks_analyzed": len(recent_df),
        "estimated_recent_minutes": total_minutes,
        "top_artist": top_artist,
        "top_track": top_track,
        "generated_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
