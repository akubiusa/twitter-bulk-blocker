"""SQLite persistence for block history and processing sessions."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class DatabaseManager:
    """Manages the SQLite database; each method opens and closes its own connection."""

    def __init__(self, db_file: str):
        self.db_file = db_file
        self.init_database()

    def init_database(self) -> None:
        """Create the DB directory and tables if missing."""
        try:
            db_path = Path(self.db_file)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            # One row per user_id; failed rows keep retry bookkeeping.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS block_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    screen_name TEXT NOT NULL,
                    user_id TEXT,
                    display_name TEXT,
                    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'blocked',
                    response_code INTEGER,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP,
                    user_status TEXT,
                    UNIQUE(user_id)
                )
            """
            )

            # One row per processing session.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS process_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_targets INTEGER,
                    processed INTEGER DEFAULT 0,
                    blocked INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    completed BOOLEAN DEFAULT FALSE
                )
            """
            )

            conn.commit()
            conn.close()
            print(f"データベース初期化完了: {self.db_file}")
        except Exception as e:
            if 'conn' in locals():
                conn.close()
            print(f"データベース初期化エラー: {e}")
            raise

    def is_already_blocked(
        self, identifier: str, user_format: str = "screen_name"
    ) -> bool:
        """Return True if the user has a row with status 'blocked'.

        Args:
            identifier: user_id or screen_name, depending on user_format.
            user_format: "user_id" or "screen_name" (anything else is treated as screen_name).
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if user_format == "user_id":
            cursor.execute(
                """
                SELECT screen_name, user_id, blocked_at, status 
                FROM block_history 
                WHERE user_id = ? AND status = 'blocked'
            """,
                (str(identifier),),
            )
        else:
            cursor.execute(
                """
                SELECT screen_name, user_id, blocked_at, status 
                FROM block_history 
                WHERE screen_name = ? AND status = 'blocked'
            """,
                (str(identifier),),
            )

        result = cursor.fetchone()
        conn.close()

        return result is not None

    def get_blocked_users_count(self) -> int:
        """Return the number of rows with status 'blocked'."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM block_history WHERE status = 'blocked'")
        count = cursor.fetchone()[0]

        conn.close()
        return count

    def get_blocked_users_set(self, user_format: str) -> set:
        """Return the set of blocked user_ids (user_format == "user_id") or screen_names."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if user_format == "user_id":
            cursor.execute(
                "SELECT user_id FROM block_history WHERE status = 'blocked' AND user_id IS NOT NULL"
            )
        else:
            cursor.execute(
                "SELECT screen_name FROM block_history WHERE status = 'blocked' AND screen_name IS NOT NULL"
            )

        blocked_users = {row[0] for row in cursor.fetchall()}
        conn.close()

        return blocked_users

    def record_block_result(
        self,
        screen_name: Optional[str],
        user_id: Optional[str],
        display_name: Optional[str],
        success: bool,
        status_code: int,
        error_message: Optional[str] = None,
        user_status: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        """Upsert a block result (INSERT OR REPLACE, keyed by UNIQUE user_id).

        Args:
            success: True stores status 'blocked', False stores 'failed'.
            status_code: HTTP status code of the block request.
            retry_count: Retries so far; last_retry_at is set to the current time.
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        status = "blocked" if success else "failed"
        current_time = datetime.now().isoformat()

        cursor.execute(
            """
            INSERT OR REPLACE INTO block_history 
            (screen_name, user_id, display_name, status, response_code, error_message, user_status, retry_count, last_retry_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                screen_name,
                user_id,
                display_name,
                status,
                status_code,
                error_message,
                user_status,
                retry_count,
                current_time,
            ),
        )

        conn.commit()
        conn.close()

    def start_session(self, total_targets: int) -> int:
        """Insert a process_log row and return its id."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO process_log (total_targets)
            VALUES (?)
        """,
            (total_targets,),
        )

        session_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return session_id

    def update_session(
        self, session_id: int, processed: int, blocked: int, skipped: int, errors: int
    ) -> None:
        """Overwrite the progress counters of a session."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE process_log 
            SET processed = ?, blocked = ?, skipped = ?, errors = ?
            WHERE id = ?
        """,
            (processed, blocked, skipped, errors, session_id),
        )

        conn.commit()
        conn.close()

    def complete_session(self, session_id: int) -> None:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE process_log 
            SET completed = TRUE
            WHERE id = ?
        """,
            (session_id,),
        )

        conn.commit()
        conn.close()

    def get_retry_candidates(self) -> List[Dict[str, Any]]:
        """Return failed users that are retryable and past their backoff delay.

        Only rows below the retry limit with a transient-looking failure qualify,
        oldest last_retry_at first. Rows with NULL last_retry_at (set by reset_retry_counts /
        reset_failed_users) have no backoff pending and are always returned.

        Returns:
            Dicts with screen_name, user_id, display_name, retry_count, user_status, last_error.
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT screen_name, user_id, display_name, status, response_code, 
                   error_message, user_status, retry_count, last_retry_at
            FROM block_history 
            WHERE status = 'failed' 
            AND retry_count < 10
            AND (
                user_status IN ('unavailable') OR
                response_code IN (429, 500, 502, 503, 504) OR
                response_code IS NULL OR
                error_message LIKE '%temporarily%' OR
                error_message LIKE '%rate limit%' OR
                error_message LIKE '%timeout%' OR
                error_message LIKE '%server error%' OR
                error_message LIKE '%ユーザー情報取得失敗%'
            )
            ORDER BY last_retry_at ASC
        """
        )

        candidates = []
        current_time = datetime.now()

        for row in cursor.fetchall():
            (
                screen_name,
                user_id,
                display_name,
                status,
                response_code,
                error_message,
                user_status,
                retry_count,
                last_retry_str,
            ) = row

            if last_retry_str:
                last_retry = datetime.fromisoformat(last_retry_str)
                required_delay = self._get_retry_delay(retry_count)
                if (current_time - last_retry).total_seconds() < required_delay:
                    continue

            candidates.append(
                {
                    "screen_name": screen_name,
                    "user_id": user_id,
                    "display_name": display_name,
                    "retry_count": retry_count,
                    "user_status": user_status,
                    "last_error": error_message,
                }
            )

        conn.close()
        return candidates

    def get_detailed_stats(self) -> Dict[str, int]:
        """Return failure counters from block_history.

        Keys: failed, failed_max_retries (retry limit reached), failed_retryable,
        follow_relationship (any status), suspended, unavailable (also counts
        not_found and deactivated). All 0 if the tables are not populated yet.
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        stats = {
            "failed": 0,
            "failed_max_retries": 0,
            "failed_retryable": 0,
            "follow_relationship": 0,
            "suspended": 0,
            "unavailable": 0,
        }

        try:
            cursor.execute("SELECT COUNT(*) FROM block_history WHERE status = 'failed'")
            stats["failed"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM block_history WHERE status = 'failed' AND retry_count >= 10")
            stats["failed_max_retries"] = cursor.fetchone()[0]

            # Same transient criteria as get_retry_candidates, minus the NULL response_code and
            # "ユーザー情報取得失敗" conditions.
            cursor.execute(
                """
                SELECT COUNT(*) FROM block_history 
                WHERE status = 'failed' 
                AND retry_count < 10
                AND (
                    user_status IN ('unavailable') OR
                    response_code IN (429, 500, 502, 503, 504) OR
                    error_message LIKE '%temporarily%' OR
                    error_message LIKE '%rate limit%' OR
                    error_message LIKE '%timeout%' OR
                    error_message LIKE '%server error%'
                )
                """
            )
            stats["failed_retryable"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM block_history WHERE error_message LIKE '%フォロー関係%'"
            )
            stats["follow_relationship"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM block_history WHERE user_status = 'suspended'"
            )
            stats["suspended"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM block_history WHERE user_status IN ('unavailable', 'not_found', 'deactivated')"
            )
            stats["unavailable"] = cursor.fetchone()[0]

        except sqlite3.OperationalError:
            pass

        conn.close()
        return stats

    def get_failure_breakdown(self) -> Dict[str, Any]:
        """Return counts of failed rows grouped by user_status, response_code and error type.

        Returns:
            Dict with keys by_status, by_response_code and by_error_type (each a value -> count dict).
            The error type is inferred by LIKE-matching error_message (English and Japanese keywords).
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        breakdown = {
            "by_status": {},
            "by_response_code": {},
            "by_error_type": {},
        }

        try:
            cursor.execute(
                """
                SELECT user_status, COUNT(*) 
                FROM block_history 
                WHERE status = 'failed' AND user_status IS NOT NULL 
                GROUP BY user_status
                """
            )
            for status, count in cursor.fetchall():
                breakdown["by_status"][status] = count

            cursor.execute(
                """
                SELECT response_code, COUNT(*) 
                FROM block_history 
                WHERE status = 'failed' AND response_code IS NOT NULL 
                GROUP BY response_code
                """
            )
            for code, count in cursor.fetchall():
                breakdown["by_response_code"][code] = count

            # Branch order matters: the first matching keyword wins.
            cursor.execute(
                """
                SELECT 
                    CASE 
                        WHEN error_message LIKE '%フォロー関係%' OR error_message LIKE '%follow%' THEN 'follow_relationship'
                        WHEN error_message LIKE '%rate limit%' OR error_message LIKE '%レート制限%' OR error_message LIKE '%429%' THEN 'rate_limit'
                        WHEN error_message LIKE '%timeout%' OR error_message LIKE '%タイムアウト%' OR error_message LIKE '%timed out%' THEN 'timeout'
                        WHEN error_message LIKE '%server error%' OR error_message LIKE '%サーバーエラー%' OR error_message LIKE '%500%' OR error_message LIKE '%502%' OR error_message LIKE '%503%' OR error_message LIKE '%504%' THEN 'server_error'
                        WHEN error_message LIKE '%temporarily%' OR error_message LIKE '%一時的%' OR error_message LIKE '%temporary%' THEN 'temporary'
                        WHEN error_message LIKE '%network%' OR error_message LIKE '%ネットワーク%' OR error_message LIKE '%connection%' THEN 'network_error'
                        WHEN error_message LIKE '%unauthorized%' OR error_message LIKE '%認証%' OR error_message LIKE '%401%' THEN 'auth_error'
                        WHEN error_message LIKE '%forbidden%' OR error_message LIKE '%403%' THEN 'forbidden'
                        WHEN error_message LIKE '%not found%' OR error_message LIKE '%404%' OR error_message LIKE '%見つからない%' THEN 'not_found_error'
                        ELSE 'other'
                    END as error_type,
                    COUNT(*)
                FROM block_history 
                WHERE status = 'failed' AND error_message IS NOT NULL 
                GROUP BY error_type
                """
            )
            for error_type, count in cursor.fetchall():
                breakdown["by_error_type"][error_type] = count

        except sqlite3.OperationalError:
            pass

        conn.close()
        return breakdown

    def get_error_message_samples(self, limit: int = 10) -> List[str]:
        """Return up to `limit` distinct error messages of failed rows, most recently retried first (for debugging)."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT DISTINCT error_message
            FROM block_history 
            WHERE status = 'failed' AND error_message IS NOT NULL 
            ORDER BY last_retry_at DESC
            LIMIT ?
            """,
            (limit,)
        )

        samples = [row[0] for row in cursor.fetchall()]
        conn.close()
        return samples

    def reset_retry_counts(self) -> int:
        """Reset retry_count and last_retry_at of all failed rows; return the number of rows updated."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE block_history 
            SET retry_count = 0, last_retry_at = NULL
            WHERE status = 'failed'
            """
        )

        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected_rows

    def delete_failed_rows_without_user_id(
        self, screen_name: str, below_retry_count: Optional[int] = None
    ) -> int:
        """Delete failed rows of screen_name that have no user_id; return the number of rows deleted.

        Such rows are never replaced by a later record_block_result, because UNIQUE(user_id) does not match NULL.
        Rows with a user_id and rows that are not failed are never touched.

        Args:
            below_retry_count: When set, only rows with a smaller retry_count are deleted, so a freshly recorded NULL-user_id row survives.
        """
        conn = sqlite3.connect(self.db_file)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM block_history
                WHERE screen_name = ? AND user_id IS NULL AND status = 'failed'
                AND (? IS NULL OR retry_count < ?)
                """,
                (str(screen_name), below_retry_count, below_retry_count),
            )
            deleted_rows = cursor.rowcount
            conn.commit()
        finally:
            conn.close()

        return deleted_rows

    def clear_error_messages(self, identifiers: Optional[List[str]] = None, user_format: str = "screen_name") -> int:
        """Set error_message to NULL on failed rows.

        Args:
            identifiers: Restrict to these users; None or an empty list means all failed rows.
            user_format: "user_id" or "screen_name" (anything else is treated as screen_name).

        Returns:
            Number of rows updated.
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        if identifiers:
            placeholders = ",".join("?" * len(identifiers))
            str_identifiers = [str(id_) for id_ in identifiers]
            
            if user_format == "user_id":
                query = f"""
                    UPDATE block_history 
                    SET error_message = NULL
                    WHERE status = 'failed' AND user_id IN ({placeholders})
                """
            else:
                query = f"""
                    UPDATE block_history 
                    SET error_message = NULL
                    WHERE status = 'failed' AND screen_name IN ({placeholders})
                """
            cursor.execute(query, str_identifiers)
        else:
            cursor.execute(
                """
                UPDATE block_history 
                SET error_message = NULL
                WHERE status = 'failed'
                """
            )

        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected_rows

    def reset_failed_users(self, identifiers: Optional[List[str]] = None, user_format: str = "screen_name", 
                          reset_error_message: bool = True, reset_retry_count: bool = True,
                          reset_response_code: bool = True, reset_user_status: bool = True) -> int:
        """Reset selected fields of failed rows to their initial state.

        Args:
            identifiers: Restrict to these users; None or an empty list means all failed rows.
            user_format: "user_id" or "screen_name" (anything else is treated as screen_name).
            reset_error_message: Set error_message to NULL.
            reset_retry_count: Set retry_count to 0 and last_retry_at to NULL.
            reset_response_code: Set response_code to NULL.
            reset_user_status: Set user_status to NULL.

        Returns:
            Number of rows updated (0 if no reset flag is set).
        """
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        reset_fields = []
        if reset_error_message:
            reset_fields.append("error_message = NULL")
        if reset_retry_count:
            reset_fields.append("retry_count = 0")
            reset_fields.append("last_retry_at = NULL")
        if reset_response_code:
            reset_fields.append("response_code = NULL")
        if reset_user_status:
            reset_fields.append("user_status = NULL")
        
        if not reset_fields:
            conn.close()
            return 0
        
        set_clause = ", ".join(reset_fields)

        if identifiers:
            placeholders = ",".join("?" * len(identifiers))
            str_identifiers = [str(id_) for id_ in identifiers]
            
            if user_format == "user_id":
                query = f"""
                    UPDATE block_history 
                    SET {set_clause}
                    WHERE status = 'failed' AND user_id IN ({placeholders})
                """
            else:
                query = f"""
                    UPDATE block_history 
                    SET {set_clause}
                    WHERE status = 'failed' AND screen_name IN ({placeholders})
                """
            cursor.execute(query, str_identifiers)
        else:
            cursor.execute(
                f"""
                UPDATE block_history 
                SET {set_clause}
                WHERE status = 'failed'
                """
            )

        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected_rows

    def is_permanent_failure(self, identifier: str, user_format: str = "screen_name") -> bool:
        """Return True if the user has a failed row that RetryManager says should not be retried."""
        from .retry import RetryManager
        
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()

            if user_format == "user_id":
                cursor.execute(
                    """
                    SELECT user_status, response_code, error_message, retry_count
                    FROM block_history 
                    WHERE user_id = ? AND status = 'failed'
                """,
                    (str(identifier),),
                )
            else:
                cursor.execute(
                    """
                    SELECT user_status, response_code, error_message, retry_count
                    FROM block_history 
                    WHERE screen_name = ? AND status = 'failed'
                """,
                    (str(identifier),),
                )

            result = cursor.fetchone()

        if not result:
            return False

        user_status, response_code, error_message, retry_count = result

        retry_manager = RetryManager()
        return not retry_manager.should_retry(
            user_status or "unknown",
            response_code or 0,
            error_message or "",
            retry_count or 0
        )[0]

    def get_permanent_failure_info(self, identifier: str, user_format: str = "screen_name") -> Optional[Dict[str, Any]]:
        """Return details of the user's failed row, or None if there is none.

        Note: the row is not checked against the retry policy; permanent_failure is always True.
        """
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()

            if user_format == "user_id":
                cursor.execute(
                    """
                    SELECT screen_name, user_id, display_name, user_status, 
                           response_code, error_message, retry_count, blocked_at
                    FROM block_history 
                    WHERE user_id = ? AND status = 'failed'
                """,
                    (str(identifier),),
                )
            else:
                cursor.execute(
                    """
                    SELECT screen_name, user_id, display_name, user_status, 
                           response_code, error_message, retry_count, blocked_at
                    FROM block_history 
                    WHERE screen_name = ? AND status = 'failed'
                """,
                    (str(identifier),),
                )

            result = cursor.fetchone()

        if not result:
            return None

        (screen_name, user_id, display_name, user_status, 
         response_code, error_message, retry_count, blocked_at) = result

        return {
            "screen_name": screen_name,
            "user_id": user_id,
            "display_name": display_name,
            "user_status": user_status or "unknown",
            "response_code": response_code,
            "error_message": error_message,
            "retry_count": retry_count,
            "blocked_at": blocked_at,
            "permanent_failure": True
        }

    def get_permanent_failures_batch(self, identifiers: List[str], user_format: str = "screen_name") -> Dict[str, Dict[str, Any]]:
        """Batch version of is_permanent_failure plus get_permanent_failure_info.

        Returns:
            Dict keyed by user_id or screen_name (per user_format) of failed users that
            RetryManager says should not be retried.
        """
        from .retry import RetryManager
        
        if not identifiers:
            return {}
        
        retry_manager = RetryManager()
        results = {}
        
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            placeholders = ",".join("?" * len(identifiers))
            str_identifiers = [str(id_) for id_ in identifiers]
            
            if user_format == "user_id":
                query = f"""
                    SELECT user_id, screen_name, display_name, user_status, 
                           response_code, error_message, retry_count, blocked_at
                    FROM block_history 
                    WHERE user_id IN ({placeholders}) AND status = 'failed'
                """
            else:
                query = f"""
                    SELECT screen_name, user_id, display_name, user_status, 
                           response_code, error_message, retry_count, blocked_at
                    FROM block_history 
                    WHERE screen_name IN ({placeholders}) AND status = 'failed'
                """
            
            cursor.execute(query, str_identifiers)
            rows = cursor.fetchall()
        
        for row in rows:
            if user_format == "user_id":
                user_id, screen_name, display_name, user_status, response_code, error_message, retry_count, blocked_at = row
                key = user_id
            else:
                screen_name, user_id, display_name, user_status, response_code, error_message, retry_count, blocked_at = row
                key = screen_name

            is_permanent = not retry_manager.should_retry(
                user_status or "unknown",
                response_code or 0,
                error_message or "",
                retry_count or 0
            )[0]
            
            if is_permanent:
                results[key] = {
                    "screen_name": screen_name,
                    "user_id": user_id,
                    "display_name": display_name,
                    "user_status": user_status or "unknown",
                    "response_code": response_code,
                    "error_message": error_message,
                    "retry_count": retry_count,
                    "blocked_at": blocked_at,
                    "permanent_failure": True
                }
        
        return results

    def _get_retry_delay(self, retry_count: int, base_delay: int = 30) -> int:
        """Return the exponential backoff delay in seconds."""
        return base_delay * (2**retry_count)
