import os
from dotenv import load_dotenv

load_dotenv()

# Discord 設定
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Spotify 設定 (選填)
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

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
