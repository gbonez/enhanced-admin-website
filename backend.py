import os
import re
from urllib.parse import urlparse
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import spotipy
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth

# ==== CONFIG / AUTH ====
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = (os.environ.get("BASE_URL") or "http://localhost:5000") + "/callback"
SPOTIFY_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN")

# Minimal scope for metadata lookups
SCOPE = "playlist-read-private playlist-read-collaborative user-library-read"

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["JSON_SORT_KEYS"] = False
# Enable CORS for GitHub Pages and local dev; adjust origins as needed
CORS(app, origins=["https://gbonez.github.io", "http://localhost:5000"]) 

# Try to init Spotify client (best-effort)
_sp = None
try:
    auth_manager = SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
        cache_path=None
    )
    if SPOTIFY_REFRESH_TOKEN:
        try:
            auth_manager.refresh_access_token(SPOTIFY_REFRESH_TOKEN)
        except Exception:
            pass
    _sp = Spotify(auth_manager=auth_manager)
except Exception:
    _sp = None

SPOTIFY_ID_RE = re.compile(r"([A-Za-z0-9]{22})")

# ==== DB HELPERS (Railway-compatible) ====
def get_db_conn():
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("RAILWAY_DATABASE_URL")
    if not db_url:
        app.logger.warning("DATABASE_URL not set")
        return None
    try:
        conn = psycopg2.connect(db_url, sslmode="require")
        conn.autocommit = True
        return conn
    except Exception as e:
        app.logger.warning("DB connection failed: %s", e)
        return None

def ensure_tables(conn):
    sqls = [
        """
        CREATE TABLE IF NOT EXISTS blacklisted_songs (
            song_id text PRIMARY KEY,
            song_name text,
            artist_id text,
            artist_name text,
            fixed boolean DEFAULT false,
            created_at timestamptz DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_playlists (
            playlist_id text PRIMARY KEY,
            playlist_name text,
            blacklisted boolean DEFAULT true,
            updated_at timestamptz DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS whitelisted_profiles (
            profile_id text PRIMARY KEY,
            added_at timestamptz DEFAULT NOW()
        )
        """
    ]
    with conn.cursor() as cur:
        for s in sqls:
            cur.execute(s)

def upsert_blacklisted_song(conn, song_id, song_name=None, artist_id=None, artist_name=None, fixed=True):
    sql = """
    INSERT INTO blacklisted_songs (song_id, song_name, artist_id, artist_name, fixed, created_at)
    VALUES (%s, %s, %s, %s, %s, NOW())
    ON CONFLICT (song_id) DO UPDATE
      SET fixed = EXCLUDED.fixed,
          song_name = COALESCE(EXCLUDED.song_name, blacklisted_songs.song_name),
          artist_id = COALESCE(EXCLUDED.artist_id, blacklisted_songs.artist_id),
          artist_name = COALESCE(EXCLUDED.artist_name, blacklisted_songs.artist_name)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (song_id, song_name, artist_id, artist_name, fixed))

def upsert_user_playlist_blacklist(conn, playlist_id, playlist_name=None, blacklisted=True):
    sql = """
    INSERT INTO user_playlists (playlist_id, playlist_name, blacklisted, updated_at)
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT (playlist_id) DO UPDATE
      SET playlist_name = COALESCE(EXCLUDED.playlist_name, user_playlists.playlist_name),
          blacklisted = EXCLUDED.blacklisted,
          updated_at = NOW()
    """
    with conn.cursor() as cur:
        cur.execute(sql, (playlist_id, playlist_name, blacklisted))

def upsert_whitelisted_profile(conn, profile_id):
    sql = """
    INSERT INTO whitelisted_profiles (profile_id, added_at)
    VALUES (%s, NOW())
    ON CONFLICT (profile_id) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, (profile_id,))

# ==== UTIL ====
def extract_id_from_input(value):
    if not value:
        return None, None
    v = value.strip()
    if v.startswith("spotify:"):
        parts = v.split(":")
        if len(parts) >= 3:
            return parts[1], parts[2]
    try:
        p = urlparse(v)
        if p.netloc and "spotify" in p.netloc:
            path = p.path.strip("/")
            parts = path.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1].split("?")[0]
            if parts:
                return None, parts[0]
    except Exception:
        pass
    m = SPOTIFY_ID_RE.search(v)
    if m:
        return None, m.group(1)
    return None, v

# ==== HTTP routes ====
@app.route("/", methods=["GET"])
def index():
    # serve the static frontend file
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/blacklist_track", methods=["POST"])
def api_blacklist_track():
    payload = request.get_json() or {}
    val = (payload.get("input") or "").strip()
    kind, id_or_raw = extract_id_from_input(val)
    track_id = id_or_raw
    if kind and kind != "track":
        if SPOTIFY_ID_RE.search(id_or_raw):
            track_id = SPOTIFY_ID_RE.search(id_or_raw).group(1)
    if not track_id:
        return jsonify({"ok": False, "error": "Could not parse track id"}), 400

    song_name = None
    artist_id = None
    artist_name = None
    if _sp:
        try:
            t = _sp.track(track_id)
            song_name = t.get("name")
            artists = t.get("artists") or []
            if artists:
                artist_id = artists[0].get("id")
                artist_name = artists[0].get("name")
        except Exception:
            pass

    conn = get_db_conn()
    if not conn:
        return jsonify({"ok": False, "error": "DB unavailable"}), 500
    try:
        ensure_tables(conn)
        upsert_blacklisted_song(conn, track_id, song_name, artist_id, artist_name, True)
        return jsonify({"ok": True, "msg": f"Blacklisted track {track_id} (fixed=true)"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/blacklist_playlist", methods=["POST"])
def api_blacklist_playlist():
    payload = request.get_json() or {}
    val = (payload.get("input") or "").strip()
    blacklisted_flag = bool(payload.get("blacklisted", True))

    kind, id_or_raw = extract_id_from_input(val)
    playlist_id = id_or_raw
    if kind and kind != "playlist":
        if SPOTIFY_ID_RE.search(id_or_raw):
            playlist_id = SPOTIFY_ID_RE.search(id_or_raw).group(1)
    if not playlist_id:
        return jsonify({"ok": False, "error": "Could not parse playlist id"}), 400

    pname = None
    if _sp:
        try:
            p = _sp.playlist(playlist_id)
            pname = p.get("name")
        except Exception:
            pass

    conn = get_db_conn()
    if not conn:
        return jsonify({"ok": False, "error": "DB unavailable"}), 500
    try:
        ensure_tables(conn)
        upsert_user_playlist_blacklist(conn, playlist_id, pname, blacklisted=blacklisted_flag)
        return jsonify({"ok": True, "msg": f"Playlist {playlist_id} upserted with blacklisted={blacklisted_flag}"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/whitelist_profile", methods=["POST"])
def api_whitelist_profile():
    payload = request.get_json() or {}
    val = (payload.get("input") or "").strip()
    kind, id_or_raw = extract_id_from_input(val)
    candidate_id = id_or_raw

    maybe_kind, maybe_id = extract_id_from_input(val)
    if maybe_kind == "playlist" or (not maybe_kind and SPOTIFY_ID_RE.search(candidate_id)):
        if _sp:
            try:
                plist = _sp.playlist(maybe_id)
                owner = plist.get("owner") or {}
                owner_id = owner.get("id")
                if owner_id:
                    candidate_id = owner_id
            except Exception:
                pass

    if not candidate_id:
        return jsonify({"ok": False, "error": "Could not parse profile or playlist owner id"}), 400

    conn = get_db_conn()
    if not conn:
        return jsonify({"ok": False, "error": "DB unavailable"}), 500
    try:
        ensure_tables(conn)
        upsert_whitelisted_profile(conn, candidate_id)
        return jsonify({"ok": True, "msg": f"Whitelisted profile {candidate_id}"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)