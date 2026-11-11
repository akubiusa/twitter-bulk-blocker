"""Orchestrates the bulk block run over the target users."""

import time
from typing import Any, Dict, List, Optional

from .api import TwitterAPI
from .config import ConfigManager, CookieManager
from .database import DatabaseManager
from .retry import RetryManager


class BulkBlockManager:
    """Coordinates bulk blocking of the target users."""

    def __init__(
        self,
        cookies_file: str = "cookies.json",
        users_file: str = "video_misuse_detecteds.json",
        db_file: str = "block_history.db",
        cache_dir: str = "/data/cache",
        debug_mode: bool = False,
        enable_header_enhancement: bool = True,
        enable_forwarded_for: bool = False,
    ):
        self.config_manager = ConfigManager(users_file)
        self.cookie_manager = CookieManager(cookies_file)
        self.database = DatabaseManager(db_file)
        self.api = TwitterAPI(
            self.cookie_manager, 
            cache_dir, 
            debug_mode, 
            enable_header_enhancement, 
            enable_forwarded_for
        )
        self.retry_manager = RetryManager()
        
        # Each monitor below is optional; if its import or init fails, its attribute is set to None.
        try:
            from .error_analytics import HTTPErrorAnalytics
            self.api.error_analytics = HTTPErrorAnalytics(self.database)
            if debug_mode:
                print("📊 HTTPエラー分析システム初期化完了")
        except Exception as e:
            if debug_mode:
                print(f"⚠️ HTTPエラー分析システム初期化失敗: {e}")
            self.api.error_analytics = None
        
        try:
            from .performance_monitor import PerformanceMonitor
            self.performance_monitor = PerformanceMonitor(self.database)
            if debug_mode:
                print("🚀 パフォーマンス監視システム初期化完了")
        except Exception as e:
            if debug_mode:
                print(f"⚠️ パフォーマンス監視システム初期化失敗: {e}")
            self.performance_monitor = None
        
        try:
            from .user_status_monitor import UserStatusMonitor
            self.status_monitor = UserStatusMonitor(self.database)
            if debug_mode:
                print("👥 ユーザーステータス監視システム初期化完了")
        except Exception as e:
            if debug_mode:
                print(f"⚠️ ユーザーステータス監視システム初期化失敗: {e}")
            self.status_monitor = None

    def load_target_users(self) -> List[str]:
        users, _ = self.config_manager.load_users_data()
        return users

    def get_user_format(self) -> str:
        """Return the users file format ("screen_name" or "user_id")."""
        return self.config_manager.get_user_format()

    def is_already_blocked(
        self, identifier: str, user_format: str = "screen_name"
    ) -> bool:
        return self.database.is_already_blocked(identifier, user_format)

    def get_blocked_users_count(self) -> int:
        return self.database.get_blocked_users_count()

    def get_remaining_users(self) -> List[str]:
        """Return target users that are not in the DB blocked set."""
        target_users = self.load_target_users()
        user_format = self.get_user_format()

        blocked_users = self.database.get_blocked_users_set(user_format)

        remaining_users = [
            user for user in target_users if str(user) not in blocked_users
        ]

        return remaining_users

    def get_retry_candidates(self) -> List[Dict[str, Any]]:
        return self.database.get_retry_candidates()

    def reset_retry_counts(self) -> int:
        """Reset retry counts of all failed users and return the number of affected rows."""
        affected_rows = self.database.reset_retry_counts()
        print(f"リトライ回数をリセットしました: {affected_rows}人")
        return affected_rows

    def process_bulk_block(
        self, max_users: Optional[int] = None, delay: float = 1.0, batch_size: int = 50
    ) -> None:
        """Block remaining target users in batches.

        Args:
            max_users: Cap on users handled in this run (None = no cap).
            delay: Wait in seconds: between batches for user_id format, after each executed block for screen_name format.
            batch_size: Number of users per lookup batch.
        """
        print("=== 一括ブロック処理開始 ===")

        remaining_users = self.get_remaining_users()
        total_targets = len(remaining_users)

        user_format = self.get_user_format()
        print(f"ユーザーファイル形式: {user_format}")

        if max_users:
            remaining_users = remaining_users[:max_users]
            print(f"処理制限: 最大{max_users}人まで処理")

        print(f"全対象ユーザー: {len(self.load_target_users())}人")
        print(f"既にブロック済み: {self.get_blocked_users_count()}人")
        print(f"残り処理対象: {len(remaining_users)}人")

        if not remaining_users:
            print("✓ 全てのユーザーが既にブロック済みです")
            return

        session_id = self.database.start_session(total_targets)
        
        # Wall-clock start, used for throughput metrics
        processing_start_time = time.time()
        
        stats = {"processed": 0, "blocked": 0, "skipped": 0, "errors": 0}

        print(f"\n処理開始: {len(remaining_users)}人を処理します")
        print(f"バッチサイズ: {batch_size}")
        print("-" * 50)

        # Both formats use batched lookups; only the lookup API differs
        if user_format == "user_id":
            self._process_users_batch(remaining_users, user_format, stats, delay, batch_size, session_id)
        else:
            self._process_screen_names_batch(remaining_users, user_format, stats, delay, batch_size, session_id)

        processing_end_time = time.time()
        total_processing_time = processing_end_time - processing_start_time
        
        if self.performance_monitor and total_processing_time > 0:
            # requests = processed + errors; success_rate = blocked / requests
            total_requests = stats["processed"] + stats["errors"]
            requests_per_second = total_requests / total_processing_time if total_processing_time > 0 else 0
            success_rate = stats["blocked"] / max(total_requests, 1)
            
            performance_metrics = {
                'processing_time': total_processing_time,
                'requests_per_second': requests_per_second,
                'success_rate': success_rate,
                'batch_size': batch_size,
                'total_processed': stats["processed"],
                'total_blocked': stats["blocked"],
                'total_errors': stats["errors"],
                'context': {
                    'user_format': user_format,
                    'delay_setting': delay,
                    'max_users_limit': max_users
                }
            }
            
            self.performance_monitor.record_processing_metrics(performance_metrics)
            
            window_data = {
                'window_start': processing_start_time,
                'window_end': processing_end_time,
                'total_processed': stats["processed"],
                'total_blocked': stats["blocked"],
                'total_errors': stats["errors"],
                'avg_processing_time': total_processing_time / max(total_requests, 1),
                'requests_per_second': requests_per_second,
                'success_rate': success_rate
            }
            
            self.performance_monitor.update_processing_window(window_data)
            
            alerts = self.performance_monitor.check_degradation_thresholds(performance_metrics)
            if alerts:
                print(f"\n⚠️ パフォーマンスアラート: {len(alerts)}件の問題を検出")
                for alert in alerts:
                    print(f"  {alert['severity']}: {alert['title']}")

        self.database.complete_session(session_id)

        self._print_completion_stats(remaining_users, stats)

    def process_retries(self, max_retries: Optional[int] = None) -> None:
        """Retry failed users, up to max_retries candidates (None = all)."""
        print("=== リトライ処理開始 ===")

        retry_candidates = self.get_retry_candidates()

        if not retry_candidates:
            print("リトライ対象のユーザーがいません")
            return

        if max_retries:
            retry_candidates = retry_candidates[:max_retries]

        print(f"リトライ対象: {len(retry_candidates)}人")
        print("-" * 50)

        stats = {"processed": 0, "blocked": 0, "skipped": 0, "errors": 0}

        for i, candidate in enumerate(retry_candidates, 1):
            self._process_retry_user(candidate, i, len(retry_candidates), stats)

        print("\n" + "=" * 50)
        print("=== リトライ処理完了 ===")
        print(f"処理対象: {len(retry_candidates)}人")
        print(f"ブロック成功: {stats['blocked']}人")
        print(f"スキップ: {stats['skipped']}人")
        print(f"エラー: {stats['errors']}人")

    def _process_users_batch(
        self,
        user_ids: List[str],
        user_format: str,
        stats: Dict[str, int],
        delay: float,
        batch_size: int,
        session_id: int,
    ) -> None:
        """Process user IDs in batches; sleep `delay` seconds between batches."""
        total_count = len(user_ids)
        processed_count = 0
        
        for i in range(0, len(user_ids), batch_size):
            batch_ids = user_ids[i:i + batch_size]
            batch_start = i + 1
            batch_end = min(i + batch_size, total_count)
            
            print(f"\n[BATCH {batch_start}-{batch_end}/{total_count}] {len(batch_ids)}ユーザーを一括取得中...")
            
            unchecked_ids = []
            
            # Fetch permanent failures for the whole batch in one query (avoids N+1)
            permanent_failures = self.database.get_permanent_failures_batch(batch_ids, user_format)
            
            for user_id in batch_ids:
                if self.is_already_blocked(user_id, user_format):
                    print(f"  ℹ スキップ: {user_id} 既にブロック済み")
                    stats["skipped"] += 1
                    processed_count += 1
                elif user_id in permanent_failures:
                    failure_info = permanent_failures[user_id]
                    user_status = failure_info.get("user_status", "unknown") if failure_info else "unknown"
                    print(f"  ⚠ スキップ: {user_id} 既知の永続的失敗 ({user_status})")
                    stats["skipped"] += 1
                    processed_count += 1
                else:
                    unchecked_ids.append(user_id)
            
            if not unchecked_ids:
                print(f"  → 全{len(batch_ids)}ユーザーが処理済み（ブロック済み/永続的失敗）")
                continue
            
            try:
                users_info = self.api.get_users_info_batch(unchecked_ids, batch_size)
                
                for user_id in unchecked_ids:
                    processed_count += 1
                    user_info = users_info.get(user_id)
                    
                    if not user_info:
                        print(f"  ✗ エラー: {user_id} ユーザー情報取得失敗（詳細は上記ログを参照）")
                        stats["errors"] += 1
                        self.database.record_block_result(
                            None, user_id, None, False, 404, "ユーザー情報取得失敗"
                        )
                        continue
                    
                    screen_name = user_info.get("screen_name") or user_id
                    
                    if self._check_user_unavailable(user_info, screen_name, stats):
                        continue
                    
                    if self._check_follow_relationship(user_info, screen_name, stats):
                        continue
                    
                    if self._check_already_blocking(user_info, screen_name, stats):
                        continue
                    
                    self._execute_block(user_info, screen_name, stats)
                    stats["processed"] += 1
                
                self.database.update_session(
                    session_id,
                    stats["processed"],
                    stats["blocked"],
                    stats["skipped"],
                    stats["errors"],
                )
                
                print(
                    f"  → バッチ完了: {batch_end}/{total_count} "
                    f"(ブロック: {stats['blocked']}, スキップ: {stats['skipped']}, エラー: {stats['errors']})"
                )
                
                # Wait between batches, not after the last one
                if i + batch_size < len(user_ids):
                    time.sleep(delay)
                    
            except Exception as e:
                import traceback
                error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
                print(f"  ✗ バッチ処理エラー: {error_msg}")
                print(f"  デバッグ情報: バッチサイズ={len(unchecked_ids)}, 開始インデックス={i}")
                if self.api.debug_mode:
                    print(f"  スタックトレース:\n{traceback.format_exc()}")
                # A batch-level failure marks every unchecked user in the batch as an error
                for user_id in unchecked_ids:
                    processed_count += 1
                    stats["errors"] += 1
                    self.database.record_block_result(
                        None, user_id, None, False, 0, f"バッチ処理エラー: {error_msg}"
                    )

    def _process_screen_names_batch(
        self,
        screen_names: List[str],
        user_format: str,
        stats: Dict[str, int],
        delay: float,
        batch_size: int,
        session_id: int,
    ) -> None:
        """Process screen names in batches; sleep `delay` seconds after each executed block."""
        total_count = len(screen_names)
        processed_count = 0
        
        for i in range(0, len(screen_names), batch_size):
            batch_names = screen_names[i:i + batch_size]
            batch_start = i + 1
            batch_end = min(i + batch_size, total_count)
            
            print(f"\n[BATCH {batch_start}-{batch_end}/{total_count}] {len(batch_names)}ユーザーを一括取得中...")
            
            unchecked_names = []
            
            # Fetch permanent failures for the whole batch in one query (avoids N+1)
            permanent_failures = self.database.get_permanent_failures_batch(batch_names, user_format)
            
            for screen_name in batch_names:
                if self.is_already_blocked(screen_name, user_format):
                    print(f"  ℹ スキップ: @{screen_name} 既にブロック済み")
                    stats["skipped"] += 1
                    processed_count += 1
                elif screen_name in permanent_failures:
                    failure_info = permanent_failures[screen_name]
                    user_status = failure_info.get("user_status", "unknown") if failure_info else "unknown"
                    print(f"  ⚠ スキップ: @{screen_name} 既知の永続的失敗 ({user_status})")
                    stats["skipped"] += 1
                    processed_count += 1
                else:
                    unchecked_names.append(screen_name)
            
            if not unchecked_names:
                print(f"  → 全{len(batch_names)}ユーザーが処理済み（ブロック済み/永続的失敗）")
                continue
            
            try:
                users_info = self.api.get_users_info_by_screen_names(unchecked_names, batch_size)
                
                for screen_name in unchecked_names:
                    processed_count += 1
                    user_info = users_info.get(screen_name)
                    
                    if not user_info:
                        print(f"  ✗ エラー: @{screen_name} ユーザー情報取得失敗（詳細は上記ログを参照）")
                        stats["errors"] += 1
                        self.database.record_block_result(
                            screen_name, None, None, False, 404, "ユーザー情報取得失敗"
                        )
                        continue
                    
                    if self._check_user_unavailable(user_info, screen_name, stats):
                        continue
                    
                    if self._check_follow_relationship(user_info, screen_name, stats):
                        continue
                    
                    if self._check_already_blocking(user_info, screen_name, stats):
                        continue
                    
                    self._execute_block(user_info, screen_name, stats)
                    
                    # Wait between users, not after the last one
                    if processed_count < total_count:
                        time.sleep(delay)
                
                self.database.update_session(
                    session_id,
                    processed_count,
                    stats["blocked"],
                    stats["skipped"],
                    stats["errors"],
                )
                
                print(
                    f"  進捗: {processed_count}/{total_count} 完了 "
                    f"(ブロック: {stats['blocked']}, スキップ: {stats['skipped']}, エラー: {stats['errors']})"
                )
                
            except Exception as e:
                import traceback
                error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
                print(f"  ✗ バッチ処理エラー: {error_msg}")
                print(f"  デバッグ情報: バッチサイズ={len(unchecked_names)}, 開始インデックス={i}")
                if hasattr(self.api, 'debug_mode') and self.api.debug_mode:
                    print(f"  スタックトレース:\n{traceback.format_exc()}")
                # A batch-level failure marks every unchecked user in the batch as an error
                for screen_name in unchecked_names:
                    processed_count += 1
                    stats["errors"] += 1
                    self.database.record_block_result(
                        screen_name, None, None, False, 0, f"バッチ処理エラー: {error_msg}"
                    )

    def _process_single_user(
        self,
        user_identifier: str,
        user_format: str,
        current_index: int,
        total_count: int,
        stats: Dict[str, int],
        delay: float,
    ) -> None:
        """Process one user: skip checks, lookup, block, then sleep `delay` seconds."""
        if user_format == "user_id":
            print(
                f"[{current_index}/{total_count}] ユーザーID {user_identifier} を処理中..."
            )
        else:
            print(f"[{current_index}/{total_count}] @{user_identifier} を処理中...")

        lookup_key = str(user_identifier)

        try:
            if self.is_already_blocked(lookup_key, user_format):
                print("  ℹ スキップ: 既にブロック済み")
                stats["skipped"] += 1
                return

            # Intended: skip known permanent failures before any API call (NOTE: currently never skips, see Database.is_permanent_failure)
            if self.database.is_permanent_failure(lookup_key, user_format):
                failure_info = self.database.get_permanent_failure_info(lookup_key, user_format)
                user_status = failure_info.get("user_status", "unknown") if failure_info else "unknown"
                error_message = failure_info.get("error_message", "") if failure_info else ""
                
                if user_format == "user_id":
                    print(f"  ⚠ スキップ: 既知の永続的失敗 ({user_status}) - ユーザーID: {lookup_key}")
                else:
                    print(f"  ⚠ スキップ: 既知の永続的失敗 ({user_status}) - ユーザー: @{lookup_key}")
                    
                if error_message and not error_message.endswith("(permanent)"):
                    print(f"    理由: {error_message}")
                
                stats["skipped"] += 1
                return

            if user_format == "user_id":
                user_info = self.api.get_user_info_by_id(user_identifier)
            else:
                user_info = self.api.get_user_info(user_identifier)

            if not user_info:
                print("  ✗ エラー: ユーザー情報取得失敗（詳細は上記ログを参照）")
                stats["errors"] += 1
                fallback_screen_name = (
                    str(user_identifier) if user_format == "screen_name" else None
                )
                self.database.record_block_result(
                    fallback_screen_name, None, None, False, 404, "ユーザー情報取得失敗"
                )
                return

            screen_name = user_info.get("screen_name") or str(user_identifier)

            if self._check_user_unavailable(user_info, screen_name, stats):
                return

            if self._check_follow_relationship(user_info, screen_name, stats):
                return

            if self._check_already_blocking(user_info, screen_name, stats):
                return

            self._execute_block(user_info, screen_name, stats)

            stats["processed"] += 1

            time.sleep(delay)

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
            print(f"  ✗ 処理エラー: {error_msg}")
            print(f"  デバッグ情報: ユーザー={user_identifier}, フォーマット={user_format}")
            if hasattr(self.api, 'debug_mode') and self.api.debug_mode:
                print(f"  スタックトレース:\n{traceback.format_exc()}")
            stats["errors"] += 1
            self.database.record_block_result(
                lookup_key if user_format == "screen_name" else None,
                None,
                None,
                False,
                0,
                error_msg,
            )

    def _process_retry_user(
        self,
        candidate: Dict[str, Any],
        current_index: int,
        total_count: int,
        stats: Dict[str, int],
    ) -> None:
        """Retry one failed candidate (lookup only; see note below)."""
        screen_name = candidate["screen_name"]
        user_id = candidate["user_id"]
        retry_count = candidate["retry_count"] + 1

        print(
            f"[{current_index}/{total_count}] @{screen_name} をリトライ中... (試行回数: {retry_count})"
        )

        try:
            # Intended: skip known permanent failures (NOTE: currently never skips, see Database.is_permanent_failure)
            if self.database.is_permanent_failure(screen_name, "screen_name"):
                failure_info = self.database.get_permanent_failure_info(screen_name, "screen_name")
                user_status = failure_info.get("user_status", "unknown") if failure_info else "unknown"
                print(f"  ⚠ スキップ: 既知の永続的失敗 ({user_status}) - ユーザー: @{screen_name} - リトライ不要")
                stats["skipped"] += 1
                return

            user_info = self.api.get_user_info(screen_name)

            if not user_info:
                print("  ✗ ユーザー情報取得失敗（詳細は上記ログを参照）")
                stats["errors"] += 1
                self.database.record_block_result(
                    screen_name,
                    user_id,
                    candidate["display_name"],
                    False,
                    404,
                    "ユーザー情報取得失敗 (リトライ)",
                    None,
                    retry_count,
                )
                return

            # NOTE: the block is not re-executed here; only the lookup is repeated and the user is counted as processed

            stats["processed"] += 1
            time.sleep(2.0)

        except Exception as e:
            import traceback
            error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else type(e).__name__
            print(f"  ✗ リトライ処理エラー: {error_msg}")
            print(f"  デバッグ情報: ユーザー=@{screen_name}, リトライ回数={retry_count}")
            if hasattr(self.api, 'debug_mode') and self.api.debug_mode:
                print(f"  スタックトレース:\n{traceback.format_exc()}")
            stats["errors"] += 1
            self.database.record_block_result(
                screen_name,
                user_id,
                candidate["display_name"],
                False,
                0,
                f"リトライ処理エラー: {error_msg}",
                None,
                retry_count,
            )

    def _check_user_unavailable(
        self, user_info: Dict[str, Any], screen_name: str, stats: Dict[str, int]
    ) -> bool:
        """Record and skip users flagged unavailable; return True if skipped.

        NOTE: every such user is currently recorded as retryable, because should_retry returns a tuple (always truthy) so the "(permanent)" branch is unreachable.
        """
        if user_info.get("unavailable", False):
            user_status = user_info.get("user_status", "unavailable")
            print(f"  ⚠ スキップ: ユーザー利用不可 ({user_status})")
            stats["skipped"] += 1

            if self.retry_manager.should_retry(
                user_status, 0, f"User {user_status}", 0
            ):
                print("    → リトライ対象として記録")
                self.database.record_block_result(
                    screen_name,
                    user_info.get("id"),
                    user_info.get("name"),
                    False,
                    0,
                    f"User {user_status}",
                    user_status,
                    0,
                )
            else:
                self.database.record_block_result(
                    screen_name,
                    user_info.get("id"),
                    user_info.get("name"),
                    False,
                    0,
                    f"User {user_status} (permanent)",
                    user_status,
                    0,
                )
            return True
        return False

    def _check_follow_relationship(
        self, user_info: Dict[str, Any], screen_name: str, stats: Dict[str, int]
    ) -> bool:
        """Skip users with a follow relationship (following or followed by); return True if skipped."""
        if user_info["following"] or user_info["followed_by"]:
            print(
                f"  ⚠ スキップ: フォロー関係あり "
                f"(フォロー中: {user_info['following']}, フォロワー: {user_info['followed_by']})"
            )
            stats["skipped"] += 1
            self.database.record_block_result(
                screen_name,
                user_info["id"],
                user_info["name"],
                False,
                0,
                "フォロー関係あり",
                user_info.get("user_status", "active"),
            )
            return True
        return False

    def _check_already_blocking(
        self, user_info: Dict[str, Any], screen_name: str, stats: Dict[str, int]
    ) -> bool:
        """Record and skip users the account already blocks; return True if skipped."""
        if user_info["blocking"]:
            print("  ℹ スキップ: 既にブロック済み")
            stats["skipped"] += 1
            self.database.record_block_result(
                screen_name,
                user_info["id"],
                user_info["name"],
                True,
                200,
                "既にブロック済み",
                user_info.get("user_status", "active"),
            )
            return True
        return False

    def _execute_block(
        self, user_info: Dict[str, Any], screen_name: str, stats: Dict[str, int]
    ) -> None:
        """Block the user via the API and record the outcome.

        NOTE: the retryable/permanent split below is currently ineffective (should_retry returns a tuple, so every failure is recorded as retryable), and block_user returns "message" while this reads "error_message", so the stored error message is always "Unknown error".
        """
        print(f"  → ブロック実行: {user_info['name']} (ID: {user_info['id']})")
        block_result = self.api.block_user(user_info["id"], screen_name)

        if block_result.get("success", False):
            print("  ✓ ブロック成功")
            stats["blocked"] += 1
            self.database.record_block_result(
                screen_name,
                user_info["id"],
                user_info["name"],
                True,
                block_result.get("status_code", 200),
                None,
                user_info.get("user_status", "active"),
            )
        else:
            error_msg = (
                block_result.get("error_message", "Unknown error")[:200]
                if block_result.get("error_message")
                else "Unknown error"
            )
            status_code = block_result.get("status_code", 0)
            print(f"  ✗ ブロック失敗: {status_code} - {error_msg}")

            # Intended: classify as retryable or permanent (NOTE: should_retry returns a tuple, so the else branch is unreachable)
            user_status = user_info.get("user_status", "active")
            status_code = block_result.get("status_code", 0)
            error_message = block_result.get("error_message", "Unknown error")
            
            if self.retry_manager.should_retry(
                user_status,
                status_code,
                error_message,
                0,
            ):
                print("    → リトライ対象として記録")
                stats["errors"] += 1
                self.database.record_block_result(
                    screen_name,
                    user_info["id"],
                    user_info["name"],
                    False,
                    status_code,
                    error_message,
                    user_status,
                    0,
                )
            else:
                print("    → 永続的な失敗として記録")
                stats["errors"] += 1
                self.database.record_block_result(
                    screen_name,
                    user_info["id"],
                    user_info["name"],
                    False,
                    status_code,
                    f"{error_message} (permanent)",
                    user_status,
                    0,
                )

    def _print_completion_stats(
        self, remaining_users: List[str], stats: Dict[str, int]
    ) -> None:
        print("\n" + "=" * 50)
        print("=== 一括ブロック処理完了 ===")
        print(f"処理対象: {len(remaining_users)}人")
        print(f"ブロック成功: {stats['blocked']}人")
        print(f"スキップ: {stats['skipped']}人")
        print(f"エラー: {stats['errors']}人")
        print(f"総ブロック数: {self.get_blocked_users_count()}人")

        remaining_after = len(self.get_remaining_users())
        print(f"残り未処理: {remaining_after}人")

        if remaining_after == 0:
            print("🎉 全ての対象ユーザーの処理が完了しました！")
