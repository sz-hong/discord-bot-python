import os
from dotenv import load_dotenv

load_dotenv()

# Discord 設定
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Spotify 設定 (選填)
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# YouTube Cookie 設定 (從環境變數讀取)
YOUTUBE_COOKIE = os.getenv("YOUTUBE_COOKIE")

# yt-dlp 設定
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

# 如果有設定 cookie，加入 yt-dlp 設定
if YOUTUBE_COOKIE:
    import tempfile
    import atexit

    # 將 \n 字串轉換為實際換行符
    cookie_content = YOUTUBE_COOKIE.replace('\\n', '\n').replace('\\t', '\t')

    # 建立暫時的 cookie 檔案
    cookie_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    cookie_file.write(cookie_content)
    cookie_file.close()

    YTDL_OPTIONS['cookiefile'] = cookie_file.name
    print(f"已載入 YouTube Cookie")

    # 程式結束時刪除暫時檔案
    def cleanup_cookie():
        import os
        try:
            os.unlink(cookie_file.name)
        except:
            pass
    atexit.register(cleanup_cookie)

# FFmpeg 設定
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -bufsize 64k',
}

# Bot 設定
BOT_PREFIX = "!"
DEFAULT_VOLUME = 0.5
MAX_QUEUE_SIZE = 100

# 自動播放設定
AUTOPLAY_ENABLED = True  # 預設開啟自動播放
AUTOPLAY_MAX_HISTORY = 20  # 避免重複播放的歷史記錄數量

# OpenAI 設定 (用於智慧推薦)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"  # 使用較便宜的模型，也可以改成 gpt-4o

# AI 推薦 Pre-prompt 預設值
DEFAULT_AI_PREPROMPT = """你是一個音樂推薦專家。請根據使用者的聽歌歷史和音樂特徵分析，推薦相似風格的歌曲。

推薦策略：
1. 優先考慮 Spotify 分析出的音樂風格（genres）和情緒特徵
2. 考慮 BPM（節奏）和能量等級的相似性
3. 同語言/地區的歌曲優先
4. 混合推薦：一些相同歌手的其他歌曲 + 一些不同歌手但風格相近的歌曲
5. 不要重複已播放過的歌曲"""
