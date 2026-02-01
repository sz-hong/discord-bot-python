"""
AI 音樂推薦模組
使用 OpenAI GPT + Spotify 分析播放歷史並推薦相似歌曲
"""

import json
from typing import Optional
from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from utils.spotify_helper import spotify_helper
from utils.prompt_manager import prompt_manager


class AIRecommender:
    """AI 音樂推薦器（整合 Spotify 音樂分析）"""

    def __init__(self):
        self.client = None
        self.enabled = False

        if OPENAI_API_KEY:
            try:
                self.client = AsyncOpenAI(api_key=OPENAI_API_KEY)
                self.enabled = True
                print("AI 推薦功能已啟用 (OpenAI)")
            except Exception as e:
                print(f"AI 推薦功能初始化失敗: {e}")

    async def get_recommendations(
        self,
        current_song: str,
        play_history: list[str],
        excluded_songs: list[str] = None,
        count: int = 5,
        guild_id: int = None
    ) -> list[str]:
        """
        根據當前歌曲和播放歷史，取得推薦的搜尋關鍵字

        Args:
            current_song: 當前播放的歌曲標題
            play_history: 最近播放過的歌曲標題列表
            excluded_songs: 不要推薦的歌曲列表
            count: 要推薦的歌曲數量
            guild_id: Discord 伺服器 ID（用於取得自訂 pre-prompt）

        Returns:
            推薦的 YouTube 搜尋關鍵字列表
        """
        if not self.enabled or not self.client:
            return []

        excluded_songs = excluded_songs or []

        # 取得該伺服器的 pre-prompt
        pre_prompt = prompt_manager.get_prompt(guild_id) if guild_id else prompt_manager.get_default()

        # 嘗試使用 Spotify 取得更詳細的音樂資訊
        spotify_info = ""
        spotify_recommendations = []

        if spotify_helper.enabled:
            print("正在使用 Spotify 分析歌曲...")

            # 分析當前歌曲
            current_analysis = await spotify_helper.analyze_song(current_song)
            if current_analysis:
                spotify_info = spotify_helper.format_for_ai(current_analysis)
                print(f"Spotify 分析結果:\n{spotify_info}")

                # 嘗試使用 Spotify 推薦 API
                track_id = current_analysis['track'].get('spotify_id')
                if track_id:
                    spotify_recs = await spotify_helper.get_recommendations([track_id], limit=count)
                    for rec in spotify_recs:
                        spotify_recommendations.append(rec['search_query'])
                    if spotify_recommendations:
                        print(f"Spotify 推薦: {spotify_recommendations}")

        # 建立歷史紀錄文字
        history_text = ""
        if play_history:
            recent = play_history[-10:]
            history_text = "\n".join([f"- {song}" for song in recent])

        # 建立排除清單
        excluded_text = ""
        if excluded_songs:
            excluded_text = "\n".join([f"- {song}" for song in excluded_songs[:20]])

        # 建立 Spotify 推薦參考
        spotify_rec_text = ""
        if spotify_recommendations:
            spotify_rec_text = f"""
Spotify 推薦的相似歌曲（可作為參考，但不必完全採用）：
{chr(10).join([f"- {rec}" for rec in spotify_recommendations])}
"""

        # 使用自訂或預設的 pre-prompt
        prompt = f"""{pre_prompt}

目前正在播放的歌曲：
{current_song}

{f"Spotify 音樂分析：{chr(10)}{spotify_info}" if spotify_info else ""}
{spotify_rec_text}
最近播放過的歌曲：
{history_text if history_text else "（無）"}

請勿推薦以下已播放過的歌曲：
{excluded_text if excluded_text else "（無）"}

請根據以上資訊，推薦 {count} 首風格相似的歌曲。

請以 JSON 格式回應：
{{
    "analysis": "簡短分析使用者的音樂風格偏好",
    "recommendations": [
        "歌手名 歌曲名",
        "歌手名 歌曲名",
        ...
    ]
}}

只回應 JSON，不要加其他文字。"""

        try:
            response = await self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一個專業的音樂推薦助手，精通各種音樂風格和歌手。你會結合 Spotify 的音樂特徵數據來做更精準的推薦。請用 JSON 格式回應。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=500
            )

            content = response.choices[0].message.content.strip()

            # 嘗試解析 JSON
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            data = json.loads(content)

            analysis = data.get("analysis", "")
            recommendations = data.get("recommendations", [])

            if analysis:
                print(f"AI 分析: {analysis}")

            print(f"AI 推薦 {len(recommendations)} 首歌曲")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")

            return recommendations

        except json.JSONDecodeError as e:
            print(f"AI 回應解析失敗: {e}")
            print(f"原始回應: {content[:200]}...")
            # 如果 AI 失敗，回傳 Spotify 推薦
            if spotify_recommendations:
                print("使用 Spotify 推薦作為備選")
                return spotify_recommendations
            return []
        except Exception as e:
            print(f"AI 推薦失敗: {e}")
            # 如果 AI 失敗，回傳 Spotify 推薦
            if spotify_recommendations:
                print("使用 Spotify 推薦作為備選")
                return spotify_recommendations
            return []


# 全域實例
ai_recommender = AIRecommender()
