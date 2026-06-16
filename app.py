"""
TuneTrack - Multi-user Spotify Listening Habit Analyzer
-----------------------------------------------------------
Each visitor logs in with their OWN Spotify account and sees
their own personal dashboard. No data is shared between users.

Run locally:
    python app.py
Then open http://localhost:8888

Deploy:
    See README.md for Render/Railway deployment steps.
"""

import os
import time
import uuid
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.utils
import json

from flask import Flask, request, redirect, session, render_template, url_for
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-this")

CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI", "http://localhost:8888/callback")
SCOPE = "user-read-recently-played user-top-read"

# Cache folder for per-user token files (so each session has its own login)
CACHE_DIR = ".spotify_caches"
os.makedirs(CACHE_DIR, exist_ok=True)


def get_oauth(cache_path):
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=cache_path,
        show_dialog=True
    )


def get_session_cache_path():
    if "uid" not in session:
        session["uid"] = str(uuid.uuid4())
    return os.path.join(CACHE_DIR, f".cache-{session['uid']}")


@app.route("/")
def index():
    cache_path = get_session_cache_path()
    oauth = get_oauth(cache_path)
    token_info = oauth.get_cached_token()

    if not token_info:
        return render_template("login.html")

    return redirect(url_for("dashboard"))


@app.route("/login")
def login():
    cache_path = get_session_cache_path()
    oauth = get_oauth(cache_path)
    auth_url = oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    cache_path = get_session_cache_path()
    oauth = get_oauth(cache_path)
    code = request.args.get("code")
    if code:
        oauth.get_access_token(code, as_dict=False)
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    cache_path = get_session_cache_path()
    if os.path.exists(cache_path):
        os.remove(cache_path)
    session.clear()
    return redirect(url_for("index"))


def fetch_user_data(sp):
    """Pull recently played tracks for the logged-in user and build a DataFrame."""
    results = sp.current_user_recently_played(limit=50)

    tracks = []
    for item in results["items"]:
        track = item.get("track")
        if not track or not track.get("id"):
            continue
        artists = track.get("artists") or []
        artist_name = artists[0]["name"] if artists else "Unknown"

        tracks.append({
            "song": track.get("name", "Unknown"),
            "artist": artist_name,
            "played_at": item["played_at"],
            "track_id": track["id"],
            "popularity": track.get("popularity", 0),
            "duration_ms": track.get("duration_ms", 0),
            "album": (track.get("album") or {}).get("name", "Unknown")
        })

    df = pd.DataFrame(tracks)
    if df.empty:
        return df

    df["played_at"] = pd.to_datetime(df["played_at"])
    df["hour"] = df["played_at"].dt.hour
    df["day"] = df["played_at"].dt.day_name()
    df["date"] = df["played_at"].dt.date

    def time_label(h):
        if 5 <= h < 12:
            return "Morning"
        elif 12 <= h < 17:
            return "Afternoon"
        elif 17 <= h < 21:
            return "Evening"
        else:
            return "Night"

    df["time_of_day"] = df["hour"].apply(time_label)
    df["duration_min"] = df["duration_ms"] / 60000
    return df


def build_charts(df, display_name):
    """Build all Plotly figures and return as JSON for client-side rendering."""
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    time_order = ["Morning", "Afternoon", "Evening", "Night"]

    df["day"] = pd.Categorical(df["day"], categories=day_order, ordered=True)
    df["time_of_day"] = pd.Categorical(df["time_of_day"], categories=time_order, ordered=True)

    figs = {}

    # 1. Plays by time of day
    count_by_time = df.groupby("time_of_day", observed=True).size().reset_index(name="plays")
    figs["time_of_day"] = px.bar(
        count_by_time, x="time_of_day", y="plays",
        title="Songs Played by Time of Day",
        labels={"plays": "Plays", "time_of_day": "Time of Day"},
        color="plays", color_continuous_scale="Greens"
    )

    # 2. Plays by day of week
    count_by_day = df.groupby("day", observed=True).size().reset_index(name="plays")
    figs["day_of_week"] = px.bar(
        count_by_day, x="day", y="plays",
        title="Songs Played by Day of Week",
        labels={"plays": "Plays", "day": "Day"},
        color="plays", color_continuous_scale="Purples"
    )

    # 3. Heatmap
    pivot = df.pivot_table(values="song", index="day", columns="hour", aggfunc="count", observed=True)
    pivot = pivot.reindex(day_order).fillna(0)
    figs["heatmap"] = px.imshow(
        pivot, title="Listening Activity: Hour vs Day",
        labels={"x": "Hour", "y": "Day", "color": "Plays"},
        color_continuous_scale="Greens", aspect="auto"
    )

    # 4. Top artists & songs
    top_artists = df["artist"].value_counts().head(10).reset_index()
    top_artists.columns = ["artist", "plays"]
    top_songs = df["song"].value_counts().head(10).reset_index()
    top_songs.columns = ["song", "plays"]

    fig_top = make_subplots(rows=1, cols=2, subplot_titles=("Top Artists", "Top Songs"))
    fig_top.add_trace(go.Bar(x=top_artists["plays"], y=top_artists["artist"],
                              orientation="h", marker_color="#1DB954"), row=1, col=1)
    fig_top.add_trace(go.Bar(x=top_songs["plays"], y=top_songs["song"],
                              orientation="h", marker_color="#5B5B8C"), row=1, col=2)
    fig_top.update_layout(showlegend=False, height=420)
    fig_top.update_yaxes(autorange="reversed")
    figs["top"] = fig_top

    # 5. Popularity by time of day
    pop_by_time = df.groupby("time_of_day", observed=True)["popularity"].mean().reset_index()
    figs["popularity"] = px.bar(
        pop_by_time, x="time_of_day", y="popularity",
        title="Avg Song Popularity by Time of Day",
        labels={"popularity": "Popularity (0-100)", "time_of_day": "Time of Day"},
        color="popularity", color_continuous_scale="Blues"
    )

    # 6. Duration by time of day
    dur_by_time = df.groupby("time_of_day", observed=True)["duration_min"].mean().reset_index()
    figs["duration"] = px.bar(
        dur_by_time, x="time_of_day", y="duration_min",
        title="Avg Song Length by Time of Day",
        labels={"duration_min": "Minutes", "time_of_day": "Time of Day"},
        color="duration_min", color_continuous_scale="Oranges"
    )

    for f in figs.values():
        f.update_layout(margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="white", plot_bgcolor="white")

    charts_json = {k: json.dumps(v, cls=plotly.utils.PlotlyJSONEncoder) for k, v in figs.items()}

    insights = {}
    if not count_by_time.empty:
        insights["busiest_time"] = count_by_time.loc[count_by_time["plays"].idxmax(), "time_of_day"]
    if not top_artists.empty:
        insights["top_artist"] = top_artists.iloc[0]["artist"]
    if not top_songs.empty:
        insights["top_song"] = top_songs.iloc[0]["song"]
    insights["total_plays"] = len(df)

    return charts_json, insights


@app.route("/dashboard")
def dashboard():
    cache_path = get_session_cache_path()
    oauth = get_oauth(cache_path)
    token_info = oauth.get_cached_token()

    if not token_info:
        return redirect(url_for("index"))

    sp = spotipy.Spotify(auth=token_info["access_token"])
    me = sp.current_user()
    display_name = me.get("display_name", "there")

    df = fetch_user_data(sp)

    if df.empty:
        return render_template("dashboard.html", display_name=display_name,
                                no_data=True, charts={}, insights={})

    charts_json, insights = build_charts(df, display_name)

    return render_template(
        "dashboard.html",
        display_name=display_name,
        no_data=False,
        charts=charts_json,
        insights=insights
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8888))
    app.run(host="0.0.0.0", port=port, debug=True)
