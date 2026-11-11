"""Users-file schema validation and cookie-file loading with a short-lived cache."""

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple


class ConfigManager:
    """Loads and validates the users file."""

    SUPPORTED_FORMATS = ["user_id", "screen_name"]

    def __init__(self, users_file: str):
        self.users_file = users_file
        self._user_format = None
        self._users_data = None

    def load_users_data(self) -> Tuple[List[str], str]:
        """Load the users file (cached after the first call).

        Returns:
            Tuple of (users list, format), where format is "user_id" or "screen_name".

        Raises:
            ValueError: If the file does not match the expected schema.
        """
        if self._users_data is not None and self._user_format is not None:
            return self._users_data, self._user_format

        with open(self.users_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._validate_schema(data)
        self._user_format = data["format"]
        self._users_data = data["users"]

        return self._users_data, self._user_format

    def get_user_format(self) -> str:
        """Return the users-file format ("user_id" or "screen_name"), loading the file if needed."""
        if self._user_format is None:
            self.load_users_data()
        return self._user_format

    def _validate_schema(self, data: Any) -> None:
        """Validate the users-file schema: {"format": "user_id"|"screen_name", "users": [non-empty list]}.

        Raises:
            ValueError: On any schema violation.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"不正なユーザーファイル形式: {type(data)}。"
                f"期待値: {{'format': 'user_id|screen_name', 'users': [...]}}"
            )

        if "format" not in data:
            raise ValueError(
                "不正なスキーマ: 'format' フィールドが必要です。"
                "期待値: {'format': 'user_id|screen_name', 'users': [...]}"
            )

        if "users" not in data:
            raise ValueError(
                "不正なスキーマ: 'users' フィールドが必要です。"
                "期待値: {'format': 'user_id|screen_name', 'users': [...]}"
            )

        format_value = data["format"]
        if format_value not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"不正なformat値: '{format_value}'。"
                f"有効値: {' または '.join(self.SUPPORTED_FORMATS)}"
            )

        users = data["users"]
        if not isinstance(users, list):
            raise ValueError(
                f"不正なusers値: リストである必要があります。取得値: {type(users)}"
            )

        if not users:
            raise ValueError("users リストが空です")


class CookieManager:
    """Reads Twitter-domain cookies from a JSON export and caches them briefly.

    The cache is invalidated by age or by a change of the file mtime, so cookie
    files refreshed externally are picked up while running.
    """

    TWITTER_DOMAINS = [".x.com", ".twitter.com", "x.com", "twitter.com"]

    def __init__(self, cookies_file: str, cache_duration: int = 60):
        self.cookies_file = cookies_file
        self._cookies_cache = None
        self._cache_timestamp = None
        self._file_mtime = None
        self.cache_duration = cache_duration  # seconds

        self._global_optimization = True
        self._min_cache_duration = 30     # seconds; also caps the effective duration (see load_cookies)

    def load_cookies(self) -> Dict[str, str]:
        """Return cookies for Twitter domains as a name -> value dict.

        The cache is used while younger than min(cache_duration, _min_cache_duration)
        seconds and the file mtime is unchanged.

        Raises:
            FileNotFoundError: If the cookies file does not exist.
        """
        current_time = time.time()
        cookie_path = Path(self.cookies_file)

        if not cookie_path.exists():
            raise FileNotFoundError(f"Cookieファイルが見つかりません: {self.cookies_file}")
        
        current_mtime = cookie_path.stat().st_mtime
        
        effective_duration = min(self.cache_duration, self._min_cache_duration)
        
        cache_valid = (
            self._cookies_cache is not None and
            self._cache_timestamp is not None and
            self._file_mtime is not None and
            (current_time - self._cache_timestamp < effective_duration) and
            (current_mtime == self._file_mtime)
        )
        
        if cache_valid:
            return self._cookies_cache
        
        print(f"🔄 Cookie再読み込み [全サービス最適化]: {self.cookies_file}")
        if self._cookies_cache is not None:
            print(f"   時間経過={current_time - (self._cache_timestamp or 0):.1f}秒 "
                  f"(設定: {effective_duration}秒), "
                  f"ファイル更新={'Yes' if current_mtime != (self._file_mtime or 0) else 'No'}")
        
        with open(self.cookies_file, "r", encoding="utf-8") as f:
            cookies_list = json.load(f)

        cookies_dict = {}
        for cookie in cookies_list:
            domain = cookie.get("domain", "")
            if domain in self.TWITTER_DOMAINS:
                cookies_dict[cookie["name"]] = cookie["value"]

        self._cookies_cache = cookies_dict
        self._cache_timestamp = current_time
        self._file_mtime = current_mtime
        
        print(f"✅ Cookie更新完了: {len(cookies_dict)}個のTwitter関連Cookie取得")
        return cookies_dict
    
    def clear_cache(self):
        """Drop the cache so the next load_cookies() re-reads the file."""
        print(f"🧹 Cookieキャッシュクリア実行")
        self._cookies_cache = None
        self._cache_timestamp = None
        self._file_mtime = None
    
    def force_refresh_on_error_threshold(self, error_count: int, threshold: int = 20, reset_callback=None) -> bool:
        """Force a cookie reload and a long blocking pause once 403 errors reach the threshold.

        Args:
            error_count: Number of 403 errors observed so far.
            threshold: Error count at which the refresh is triggered.
            reset_callback: Optional callable that resets the caller's 403 counter.

        Returns:
            True if the threshold was reached (after sleeping 30 minutes), else False.
        """
        if error_count >= threshold:
            print(f"🚨 403エラー{error_count}回検出: Cookie強制更新実行（閾値: {threshold}）")
            print(f"⏸️ 緊急停止: {threshold}回エラー到達により一時処理停止")
            self.clear_cache()

            if reset_callback and callable(reset_callback):
                try:
                    reset_callback()
                    print("🔄 403エラーカウンター強制リセット完了（Cookie更新時）")
                except Exception as e:
                    print(f"⚠️ 403エラーカウンターリセット失敗: {e}")

            import time
            print(f"🕒 緊急クールダウン開始: 30分間処理停止")
            time.sleep(1800)  # 30 minutes: cooldown that prevents an endless forced-refresh loop
            print(f"✅ 緊急クールダウン完了: 処理再開")
                    
            return True
        return False
    
    def set_cache_duration(self, duration: int):
        """Set the cache duration in seconds (clamped to at least 30). NOTE: load_cookies caps the effective duration at 30, so values above 30 have no effect."""
        old_duration = self.cache_duration
        self.cache_duration = max(duration, self._min_cache_duration)  # floor of 30s
        print(f"⏰ Cookieキャッシュ有効期限変更: {old_duration}秒 → {self.cache_duration}秒")
        
    def get_cache_info(self) -> Dict[str, Any]:
        """Return a snapshot of the cache state (ages and durations in seconds)."""
        current_time = time.time()
        effective_duration = min(self.cache_duration, self._min_cache_duration)
        
        return {
            "cached": self._cookies_cache is not None,
            "cache_age": current_time - (self._cache_timestamp or 0) if self._cache_timestamp else None,
            "cache_duration": self.cache_duration,
            "effective_duration": effective_duration,
            "global_optimization": self._global_optimization,
            "min_duration": self._min_cache_duration,
            "cookies_count": len(self._cookies_cache) if self._cookies_cache else 0,
            "file_mtime": self._file_mtime,
            "next_refresh_in": max(0, effective_duration - (current_time - (self._cache_timestamp or 0))) if self._cache_timestamp else 0
        }
