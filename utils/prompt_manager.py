"""
Pre-prompt 管理模組
用於儲存和管理每個伺服器的 AI 推薦 pre-prompt
"""

import json
import os
from typing import Optional

from config import DEFAULT_AI_PREPROMPT


# 預設的 pre-prompt 模板
PROMPT_PRESETS = {
    "default": {
        "name": "🎵 通用模式",
        "description": "根據 Spotify 分析推薦相似風格的歌曲",
        "prompt": DEFAULT_AI_PREPROMPT
    },
    "mandopop": {
        "name": "🎤 華語流行",
        "description": "專注於華語流行音樂，包含經典與新歌",
        "prompt": """你是一個華語音樂專家，專門推薦華語流行歌曲。

推薦策略：
1. 優先推薦華語歌曲（國語、粵語、台語）
2. 參考 Spotify 分析的曲風和情緒
3. 混合推薦：經典老歌 + 近年新歌
4. 知名華語歌手優先：周杰倫、林俊傑、陳奕迅、五月天、蔡依林、張惠妹、鄧紫棋等
5. 如果原曲是抒情歌，推薦其他抒情歌；如果是快歌，推薦其他節奏感強的歌"""
    },
    "jpop": {
        "name": "🇯🇵 日本流行",
        "description": "J-Pop、動漫歌曲、Vocaloid",
        "prompt": """你是一個日本音樂專家，專門推薦日本流行音樂。

推薦策略：
1. 優先推薦日語歌曲
2. 包含：J-Pop、動漫 OP/ED、Vocaloid、日本搖滾
3. 熱門歌手：YOASOBI、Ado、米津玄師、Official髭男dism、back number、LiSA、Aimer 等
4. 如果是動漫歌曲，推薦其他動漫相關歌曲
5. 參考 BPM 和能量等級，推薦節奏相似的歌曲"""
    },
    "kpop": {
        "name": "🇰🇷 韓國流行",
        "description": "K-Pop 男團女團、韓國 R&B",
        "prompt": """你是一個韓國音樂專家，專門推薦 K-Pop 歌曲。

推薦策略：
1. 優先推薦韓語歌曲
2. 包含：K-Pop 男團女團、韓國 R&B、韓國 Hip-hop
3. 熱門團體/歌手：BTS、BLACKPINK、NewJeans、aespa、IVE、Stray Kids、IU、TWICE 等
4. 如果是舞曲，推薦其他節奏感強的 K-Pop
5. 如果是抒情歌，推薦韓國 R&B 或 Ballad"""
    },
    "western": {
        "name": "🌍 歐美流行",
        "description": "Billboard 熱門、歐美流行樂",
        "prompt": """你是一個西洋音樂專家，專門推薦歐美流行音樂。

推薦策略：
1. 優先推薦英語歌曲
2. 包含：Pop、R&B、Hip-hop、Electronic、Rock
3. 熱門歌手：Taylor Swift、The Weeknd、Dua Lipa、Ed Sheeran、Bruno Mars、Billie Eilish 等
4. 參考 Billboard Hot 100 熱門歌曲
5. 根據曲風推薦：流行推流行、嘻哈推嘻哈、搖滾推搖滾"""
    },
    "chill": {
        "name": "😌 放鬆模式",
        "description": "輕柔、舒緩、適合放鬆的音樂",
        "prompt": """你是一個放鬆音樂專家，專門推薦適合放鬆、工作、讀書時聽的音樂。

推薦策略：
1. 優先推薦輕柔、舒緩的歌曲
2. 包含：Acoustic、Lo-fi、輕音樂、Jazz、Bossa Nova、輕柔的流行歌
3. 避免節奏太快或太激烈的歌曲
4. BPM 建議在 60-100 之間
5. 情緒偏向平靜、溫暖、放鬆"""
    },
    "energetic": {
        "name": "🔥 嗨歌模式",
        "description": "高能量、適合運動或派對的音樂",
        "prompt": """你是一個派對音樂專家，專門推薦高能量、適合運動或派對的音樂。

推薦策略：
1. 優先推薦節奏快、能量高的歌曲
2. 包含：EDM、Dance Pop、Hip-hop、電子舞曲
3. BPM 建議在 120 以上
4. 情緒偏向興奮、熱情、充滿活力
5. 適合健身、派對、開車時聽"""
    },
    "retro": {
        "name": "📻 經典懷舊",
        "description": "80-2000年代的經典老歌",
        "prompt": """你是一個經典音樂專家，專門推薦 80-2000 年代的懷舊老歌。

推薦策略：
1. 優先推薦 1980-2010 年間發行的歌曲
2. 各語言都可以：華語經典、西洋經典、日本經典
3. 包含：經典情歌、經典搖滾、經典舞曲
4. 華語經典：張學友、王菲、劉德華、張國榮等
5. 西洋經典：Michael Jackson、Madonna、Whitney Houston 等"""
    },
    "indie": {
        "name": "🎸 獨立音樂",
        "description": "獨立樂團、另類音樂、小眾風格",
        "prompt": """你是一個獨立音樂專家，專門推薦獨立樂團和另類音樂。

推薦策略：
1. 優先推薦獨立樂團、獨立歌手的作品
2. 包含：Indie Rock、Indie Pop、Alternative、Post-rock、Shoegaze
3. 可以推薦較小眾但高品質的音樂
4. 華語獨立：草東沒有派對、落日飛車、告五人、茄子蛋等
5. 西洋獨立：Arctic Monkeys、Tame Impala、The 1975 等"""
    },
    "anime": {
        "name": "🎌 動漫專屬",
        "description": "專門推薦動漫相關歌曲",
        "prompt": """你是一個動漫音樂專家，專門推薦動漫相關的歌曲。

推薦策略：
1. 只推薦動漫相關歌曲：OP、ED、插入曲、角色歌、動漫電影主題曲
2. 熱門動漫歌手：LiSA、Aimer、YOASOBI、米津玄師、Linked Horizon、藍井艾露等
3. 經典動漫歌曲也可以推薦
4. 如果原曲是熱血番，推薦其他熱血動漫歌曲
5. 如果原曲是抒情番，推薦其他抒情動漫歌曲"""
    }
}


class PromptManager:
    """管理每個伺服器的 pre-prompt 設定"""

    def __init__(self, data_file: str = "data/prompts.json"):
        self.data_file = data_file
        self.prompts: dict[int, str] = {}  # guild_id -> pre-prompt
        self.presets = PROMPT_PRESETS
        self._ensure_data_dir()
        self._load()

    def _ensure_data_dir(self):
        """確保資料目錄存在"""
        data_dir = os.path.dirname(self.data_file)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir)

    def _load(self):
        """從檔案載入設定"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 轉換 key 為 int（JSON 會將 key 轉為 string）
                    self.prompts = {int(k): v for k, v in data.items()}
                print(f"已載入 {len(self.prompts)} 個伺服器的 pre-prompt 設定")
        except Exception as e:
            print(f"載入 pre-prompt 設定失敗: {e}")
            self.prompts = {}

    def _save(self):
        """儲存設定到檔案"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.prompts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"儲存 pre-prompt 設定失敗: {e}")

    def get_prompt(self, guild_id: int) -> str:
        """
        取得指定伺服器的 pre-prompt

        Args:
            guild_id: Discord 伺服器 ID

        Returns:
            pre-prompt 字串，如果沒有自訂則回傳預設值
        """
        return self.prompts.get(guild_id, DEFAULT_AI_PREPROMPT)

    def set_prompt(self, guild_id: int, prompt: str) -> bool:
        """
        設定指定伺服器的 pre-prompt

        Args:
            guild_id: Discord 伺服器 ID
            prompt: 新的 pre-prompt

        Returns:
            是否成功
        """
        try:
            self.prompts[guild_id] = prompt
            self._save()
            return True
        except Exception as e:
            print(f"設定 pre-prompt 失敗: {e}")
            return False

    def reset_prompt(self, guild_id: int) -> bool:
        """
        重設指定伺服器的 pre-prompt 為預設值

        Args:
            guild_id: Discord 伺服器 ID

        Returns:
            是否成功
        """
        try:
            if guild_id in self.prompts:
                del self.prompts[guild_id]
                self._save()
            return True
        except Exception as e:
            print(f"重設 pre-prompt 失敗: {e}")
            return False

    def is_custom(self, guild_id: int) -> bool:
        """檢查是否有自訂 pre-prompt"""
        return guild_id in self.prompts

    def get_default(self) -> str:
        """取得預設的 pre-prompt"""
        return DEFAULT_AI_PREPROMPT

    def get_preset(self, preset_key: str) -> Optional[dict]:
        """取得指定的預設模板"""
        return self.presets.get(preset_key)

    def get_all_presets(self) -> dict:
        """取得所有預設模板"""
        return self.presets

    def set_preset(self, guild_id: int, preset_key: str) -> bool:
        """
        使用預設模板設定 pre-prompt

        Args:
            guild_id: Discord 伺服器 ID
            preset_key: 預設模板的 key

        Returns:
            是否成功
        """
        preset = self.get_preset(preset_key)
        if not preset:
            return False
        return self.set_prompt(guild_id, preset['prompt'])

    def get_current_preset_key(self, guild_id: int) -> Optional[str]:
        """取得目前使用的預設模板 key（如果有的話）"""
        current_prompt = self.get_prompt(guild_id)
        for key, preset in self.presets.items():
            if preset['prompt'] == current_prompt:
                return key
        return None


# 全域實例
prompt_manager = PromptManager()
