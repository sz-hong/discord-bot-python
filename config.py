import os
from dotenv import load_dotenv

load_dotenv()

# ─── Discord ────────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ─── Spotify OAuth2 ─────────────────────────────────────────
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Spotify OAuth2 需要的權限範圍
SPOTIFY_SCOPES = [
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-read-playback-state",
    "user-top-read",
]

# ─── Last.fm ─────────────────────────────────────────────────
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")

# ─── YouTube Cookie ──────────────────────────────────────────
YOUTUBE_COOKIE = os.getenv("YOUTUBE_COOKIE")

# ─── yt-dlp ──────────────────────────────────────────────────
YTDL_OPTIONS = {
    'format': 'bestaudio[ext=webm]/bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'extract_flat': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
        }
    },
}

# Cookie 處理
if YOUTUBE_COOKIE:
    import tempfile
    import atexit

    cookie_content = YOUTUBE_COOKIE.replace('\\n', '\n').replace('\\t', '\t')
    cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    cookie_file.write(cookie_content)
    cookie_file.close()
    YTDL_OPTIONS['cookiefile'] = cookie_file.name
    print("✅ 已載入 YouTube Cookie")

    def _cleanup_cookie():
        try:
            os.unlink(cookie_file.name)
        except Exception:
            pass
    atexit.register(_cleanup_cookie)

# ─── FFmpeg ──────────────────────────────────────────────────
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -bufsize 64k',
}

# ─── Bot 設定 ────────────────────────────────────────────────
DEFAULT_VOLUME = 0.5
MAX_QUEUE_SIZE = 100
AUTOPLAY_ENABLED = True
AUTOPLAY_MAX_HISTORY = 50
AUTOPLAY_LOW_WATERMARK = int(os.getenv("AUTOPLAY_LOW_WATERMARK", "2"))
AUTOPLAY_TARGET_SIZE = int(os.getenv("AUTOPLAY_TARGET_SIZE", "5"))
