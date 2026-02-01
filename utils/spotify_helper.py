"""
Spotify 音樂資訊輔助模組
用於取得歌曲的詳細音樂特徵，增強 AI 推薦效果
"""

from typing import Optional
import re


class SpotifyHelper:
    """Spotify 音樂資訊助手"""

    def __init__(self):
        self.spotify = None
        self.enabled = False
        self._setup()

    def _setup(self):
        """初始化 Spotify 客戶端"""
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=SPOTIFY_CLIENT_ID,
                        client_secret=SPOTIFY_CLIENT_SECRET
                    )
                )
                self.enabled = True
                print("Spotify 音樂分析功能已啟用")
            else:
                print("Spotify API 未設定（推薦功能將使用基本模式）")
        except Exception as e:
            print(f"Spotify 初始化失敗: {e}")

    def _clean_title(self, title: str) -> str:
        """清理 YouTube 標題，提取歌曲名稱"""
        # 移除常見的非歌曲資訊
        clean = title

        # 移除各種括號內容
        clean = re.sub(r'\[.*?\]|\(.*?\)|【.*?】|「.*?」', ' ', clean)

        # 移除 hashtag
        clean = re.sub(r'#\S+', ' ', clean)

        # 移除常見關鍵字
        clean = re.sub(
            r'MV|Official|Music Video|Lyric|lyrics|官方|完整版|HD|HQ|4K|'
            r'纯享|合辑|精选|现场|Live|Cover|翻唱|Audio|Video|Visualizer',
            ' ', clean, flags=re.IGNORECASE
        )

        # 移除表情符號
        clean = re.sub(r'[🔥✨💕🎵🎶❤️💜💙🌟⭐️😊🥰🎤🎧]+', ' ', clean)

        # 移除 ｜ 和之後的內容
        clean = re.sub(r'[｜|].*$', '', clean)

        # 移除多餘空格
        clean = re.sub(r'\s+', ' ', clean).strip()

        return clean if len(clean) >= 2 else title[:30]

    async def search_track(self, title: str) -> Optional[dict]:
        """
        根據標題搜尋 Spotify 上的歌曲

        Returns:
            包含歌曲資訊的字典，如果找不到則回傳 None
        """
        if not self.enabled:
            return None

        try:
            clean_title = self._clean_title(title)
            results = self.spotify.search(q=clean_title, type='track', limit=1)

            if not results['tracks']['items']:
                return None

            track = results['tracks']['items'][0]

            return {
                'spotify_id': track['id'],
                'name': track['name'],
                'artists': [a['name'] for a in track['artists']],
                'album': track['album']['name'],
                'popularity': track['popularity'],  # 0-100 熱門度
                'preview_url': track.get('preview_url'),
            }

        except Exception as e:
            print(f"Spotify 搜尋失敗: {e}")
            return None

    async def get_audio_features(self, track_id: str) -> Optional[dict]:
        """
        取得歌曲的音樂特徵

        Returns:
            包含音樂特徵的字典
        """
        if not self.enabled:
            return None

        try:
            features = self.spotify.audio_features([track_id])[0]

            if not features:
                return None

            return {
                'danceability': features['danceability'],      # 0-1 舞曲性
                'energy': features['energy'],                  # 0-1 能量
                'valence': features['valence'],                # 0-1 正面情緒
                'tempo': features['tempo'],                    # BPM
                'acousticness': features['acousticness'],      # 0-1 原聲程度
                'instrumentalness': features['instrumentalness'],  # 0-1 器樂程度
                'speechiness': features['speechiness'],        # 0-1 說唱程度
            }

        except Exception as e:
            print(f"取得音樂特徵失敗: {e}")
            return None

    async def get_artist_genres(self, artist_name: str) -> list[str]:
        """取得歌手的音樂風格"""
        if not self.enabled:
            return []

        try:
            results = self.spotify.search(q=f'artist:{artist_name}', type='artist', limit=1)

            if not results['artists']['items']:
                return []

            artist = results['artists']['items'][0]
            return artist.get('genres', [])

        except Exception as e:
            print(f"取得歌手風格失敗: {e}")
            return []

    async def get_recommendations(self, track_ids: list[str], limit: int = 5) -> list[dict]:
        """
        使用 Spotify 推薦 API 取得相似歌曲

        Args:
            track_ids: 種子歌曲的 Spotify ID 列表（最多 5 首）
            limit: 推薦數量

        Returns:
            推薦歌曲列表
        """
        if not self.enabled or not track_ids:
            return []

        try:
            # Spotify 推薦 API 最多接受 5 個種子
            seed_tracks = track_ids[:5]

            results = self.spotify.recommendations(
                seed_tracks=seed_tracks,
                limit=limit
            )

            recommendations = []
            for track in results['tracks']:
                recommendations.append({
                    'name': track['name'],
                    'artists': [a['name'] for a in track['artists']],
                    'search_query': f"{track['artists'][0]['name']} {track['name']}",
                    'popularity': track['popularity'],
                })

            return recommendations

        except Exception as e:
            print(f"Spotify 推薦失敗: {e}")
            return []

    async def analyze_song(self, title: str) -> Optional[dict]:
        """
        完整分析一首歌曲

        Returns:
            包含所有音樂資訊的字典
        """
        if not self.enabled:
            return None

        try:
            # 搜尋歌曲
            track = await self.search_track(title)
            if not track:
                return None

            # 取得音樂特徵
            features = await self.get_audio_features(track['spotify_id'])

            # 取得歌手風格
            genres = []
            if track['artists']:
                genres = await self.get_artist_genres(track['artists'][0])

            return {
                'track': track,
                'features': features,
                'genres': genres[:5],  # 最多取 5 個風格標籤
            }

        except Exception as e:
            print(f"歌曲分析失敗: {e}")
            return None

    def format_for_ai(self, analysis: dict) -> str:
        """將分析結果格式化為 AI 可讀的文字"""
        if not analysis:
            return ""

        lines = []

        track = analysis.get('track', {})
        if track:
            artists = ", ".join(track.get('artists', ['未知']))
            lines.append(f"歌曲: {track.get('name', '未知')} - {artists}")
            lines.append(f"專輯: {track.get('album', '未知')}")
            lines.append(f"熱門度: {track.get('popularity', 0)}/100")

        genres = analysis.get('genres', [])
        if genres:
            lines.append(f"風格: {', '.join(genres)}")

        features = analysis.get('features', {})
        if features:
            # 轉換為易讀的描述
            energy = features.get('energy', 0.5)
            valence = features.get('valence', 0.5)
            tempo = features.get('tempo', 120)
            acousticness = features.get('acousticness', 0.5)

            mood = "歡快正面" if valence > 0.6 else "憂鬱深沉" if valence < 0.4 else "中性"
            energy_desc = "高能量" if energy > 0.6 else "低能量" if energy < 0.4 else "中等能量"
            acoustic_desc = "原聲/不插電" if acousticness > 0.6 else "電子/合成" if acousticness < 0.3 else "混合"

            lines.append(f"節奏: {tempo:.0f} BPM")
            lines.append(f"情緒: {mood}, {energy_desc}")
            lines.append(f"風格: {acoustic_desc}")

        return "\n".join(lines)


# 全域實例
spotify_helper = SpotifyHelper()
