"""Retry decisions and adaptive backoff, with detailed classification of HTTP 403 errors."""

import time
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timedelta


class ErrorClassifier:
    """Classifies HTTP 403 responses into error types by keyword matching."""
    
    # Keys are symbolic names; values are the strings returned by classify_403_error
    # and used as keys in AdaptiveBackoffStrategy.
    ERROR_TYPES = {
        "RATE_LIMIT": "rate_limit",
        "AUTH_REQUIRED": "auth_required",
        "PERMISSION_DENIED": "permission_denied",
        "ACCOUNT_RESTRICTED": "account_restricted",
        "HEADER_ISSUE": "header_issue",
        "UNKNOWN_403": "unknown_403",
        "ANTI_BOT": "anti_bot",
        "IP_BLOCKED": "ip_blocked",
    }
    
    @staticmethod
    def classify_403_error(response_text: str = "", headers: Dict[str, str] = None, 
                          status_code: int = 403) -> Tuple[str, str, int]:
        """Classify a 403 response.

        Rules are checked in order and the first match wins.

        Args:
            response_text: Response body; matched case-insensitively.
            headers: Response headers; only ``x-rate-limit-remaining`` is inspected.
            status_code: HTTP status. Anything other than 403 returns "NOT_403".

        Returns:
            (error_type, description, priority_level). error_type is a value of
            ERROR_TYPES, or "NOT_403" for non-403 input. priority_level is
            1 = fixable immediately, 2 = needs adjustment, 3 = serious
            (0 for non-403).
        """
        if status_code != 403:
            return "NOT_403", "Not a 403 error", 0
        
        response_lower = response_text.lower() if response_text else ""
        headers = headers or {}
        
        if ("rate limit" in response_lower or 
            "too many requests" in response_lower or
            headers.get("x-rate-limit-remaining") == "0"):
            return ErrorClassifier.ERROR_TYPES["RATE_LIMIT"], "API rate limit exceeded", 1
        
        if ("authorization" in response_lower or 
            "authenticate" in response_lower or
            "invalid token" in response_lower or
            "credential" in response_lower):
            return ErrorClassifier.ERROR_TYPES["AUTH_REQUIRED"], "Authentication required or invalid", 2
        
        if ("permission" in response_lower or 
            "access denied" in response_lower or
            "not authorized" in response_lower or
            "forbidden" in response_lower):
            return ErrorClassifier.ERROR_TYPES["PERMISSION_DENIED"], "Insufficient permissions", 2
        
        if ("account" in response_lower and 
            ("restricted" in response_lower or "limited" in response_lower or
             "suspended" in response_lower or "locked" in response_lower)):
            return ErrorClassifier.ERROR_TYPES["ACCOUNT_RESTRICTED"], "Account restrictions detected", 3
        
        if ("header" in response_lower or 
            "user-agent" in response_lower or
            "missing" in response_lower and "required" in response_lower):
            return ErrorClassifier.ERROR_TYPES["HEADER_ISSUE"], "Header validation failed", 1
        
        if ("bot" in response_lower or 
            "automated" in response_lower or
            "suspicious" in response_lower or
            "unusual activity" in response_lower or
            "verification" in response_lower):
            return ErrorClassifier.ERROR_TYPES["ANTI_BOT"], "Anti-bot system triggered", 2
        
        if ("ip" in response_lower and 
            ("blocked" in response_lower or "restricted" in response_lower)):
            return ErrorClassifier.ERROR_TYPES["IP_BLOCKED"], "IP address blocked or restricted", 3
        
        # Twitter-specific "Unknown error" body (treated as likely anti-bot).
        if "unknown error" in response_lower:
            return ErrorClassifier.ERROR_TYPES["UNKNOWN_403"], "Twitter Unknown Error - likely anti-bot", 2
        
        return ErrorClassifier.ERROR_TYPES["UNKNOWN_403"], "Unclassified 403 Forbidden error", 2


class AdaptiveBackoffStrategy:
    """Computes retry delays from the error type, retry count and recent success rate."""
    
    def __init__(self):
        self.error_history = []  # list of (timestamp, error_type, success)
        self.success_rate_window = 300  # seconds
        
    def calculate_backoff_delay(self, error_type: str, retry_count: int, 
                              base_delay: int = 30) -> int:
        """Compute the backoff delay in seconds.

        Scaled by error type, retry_count and recent success rate, then clamped to a per-type range.

        Args:
            error_type: A value of ErrorClassifier.ERROR_TYPES; unknown types are not scaled.
            retry_count: Number of retries so far (0-based).
            base_delay: Base delay in seconds.
        """
        # Longer waits for errors that are less likely to clear quickly.
        type_multipliers = {
            "rate_limit": 2.0,
            "auth_required": 1.5,
            "permission_denied": 1.0,
            "account_restricted": 3.0,
            "header_issue": 0.5,      # likely fixable by changing headers, so retry sooner
            "unknown_403": 2.5,
            "anti_bot": 3.0,
            "ip_blocked": 4.0,
        }
        
        # Back off harder when recent attempts for this error type mostly fail, less when they mostly succeed.
        success_rate = self._calculate_recent_success_rate(error_type)
        success_multiplier = 1.0
        if success_rate < 0.3:
            success_multiplier = 2.0
        elif success_rate < 0.5:
            success_multiplier = 1.5
        elif success_rate > 0.8:
            success_multiplier = 0.8
        
        base_multiplier = type_multipliers.get(error_type, 1.0)
        exponential_factor = min(2 ** retry_count, 8)
        
        total_delay = int(base_delay * base_multiplier * exponential_factor * success_multiplier)
        
        min_delay = 5 if error_type == "header_issue" else 10
        max_delay = 1800 if error_type in ["ip_blocked", "account_restricted"] else 600
        
        return max(min_delay, min(total_delay, max_delay))
    
    def _calculate_recent_success_rate(self, error_type: str) -> float:
        """Return the success rate (0.0-1.0) for error_type within the window; 0.5 if no data."""
        current_time = time.time()
        cutoff_time = current_time - self.success_rate_window
        
        relevant_history = [
            entry for entry in self.error_history 
            if entry[0] >= cutoff_time and entry[1] == error_type
        ]
        
        if not relevant_history:
            return 0.5
        
        success_count = sum(1 for entry in relevant_history if entry[2])
        return success_count / len(relevant_history)
    
    def record_attempt(self, error_type: str, success: bool):
        """Record an attempt outcome and drop history older than twice the success-rate window."""
        current_time = time.time()
        self.error_history.append((current_time, error_type, success))
        
        cutoff_time = current_time - self.success_rate_window * 2
        self.error_history = [
            entry for entry in self.error_history if entry[0] >= cutoff_time
        ]


class RetryManager:
    """Decides whether a failed request should be retried and how long to wait."""

    # User states that will never succeed on retry.
    PERMANENT_FAILURES = [
        "not_found",
        "deactivated",
        "suspended",
    ]

    # User states that may recover.
    TEMPORARY_FAILURES = [
        "unavailable",
    ]

    RETRYABLE_STATUS_CODES = [
        403,  # Forbidden (Twitter API temporary restriction, including "Unknown error")
        429,
        500,
        502,
        503,
        504,
    ]

    # Matched against the lowercased error message.
    RETRYABLE_MESSAGES = [
        "temporarily unavailable",
        "rate limit",
        "timeout",
        "server error",
        "unknown error",  # Twitter API 403 "Unknown error"
    ]

    MAX_RETRIES = 10
    
    def __init__(self):
        self.error_classifier = ErrorClassifier()
        self.backoff_strategy = AdaptiveBackoffStrategy()

    def should_retry(
        self,
        user_status: str,
        status_code: int,
        error_message: str,
        retry_count: int,
        response_text: str = "",
        response_headers: Dict[str, str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Decide whether to retry.

        Checks in order: retry limit, permanent/temporary user status, 403 classification,
        retryable status codes, retryable messages, null status code.

        Args:
            user_status: User state string (see PERMANENT_FAILURES / TEMPORARY_FAILURES).
            status_code: HTTP status code, or None if there was no response.
            error_message: Error message text.
            retry_count: Number of retries so far.
            response_text: Response body, used for 403 classification.
            response_headers: Response headers, used for 403 classification.

        Returns:
            (should_retry, error_classification). The classification is a reason string
            such as "max_retries_exceeded", an ErrorClassifier type for 403, or
            "status_code_<code>"; it is "no_retry_condition_met" when nothing matched.
        """
        if retry_count >= self.MAX_RETRIES:
            return False, "max_retries_exceeded"

        if user_status in self.PERMANENT_FAILURES:
            return False, "permanent_failure"

        if user_status in self.TEMPORARY_FAILURES:
            return True, "temporary_failure"

        if status_code == 403:
            error_type, description, priority = self.error_classifier.classify_403_error(
                response_text=response_text,
                headers=response_headers,
                status_code=status_code
            )
            
            # Only serious restrictions are given up on; every other 403 is retried.
            non_retryable_types = ["account_restricted", "ip_blocked"]
            if error_type in non_retryable_types and priority >= 3:
                return False, error_type
            
            return True, error_type
        
        # Other retryable status codes (403 is handled above).
        if status_code and status_code in self.RETRYABLE_STATUS_CODES:
            return True, f"status_code_{status_code}"

        if error_message:
            error_lower = error_message.lower()
            for msg in self.RETRYABLE_MESSAGES:
                if msg in error_lower:
                    return True, "message_based_retry"
            
            # Matches the Japanese failure message emitted by this tool's own user lookup.
            if "ユーザー情報取得失敗" in error_message:
                return True, "japanese_error_message"

        # No status code and not explicitly permanent: assume a transient network failure.
        if status_code is None and error_message and "permanent" not in error_message.lower():
            return True, "null_status_retry"

        return False, "no_retry_condition_met"

    def get_retry_delay(self, retry_count: int, base_delay: int = 30, status_code: int = None, 
                       error_message: str = "", error_classification: str = "", 
                       response_text: str = "", response_headers: Dict[str, str] = None) -> int:
        """Return the retry delay in seconds.

        Args:
            retry_count: Number of retries so far (0-based).
            base_delay: Base delay in seconds.
            status_code: HTTP status code.
            error_message: Error message text (used only for the 403 "unknown error" fallback).
            error_classification: Classification from should_retry; enables adaptive backoff for 403.
            response_text: Unused.
            response_headers: Unused.
        """
        if status_code == 403 and error_classification:
            return self.backoff_strategy.calculate_backoff_delay(
                error_classification, retry_count, base_delay
            )
        
        # 403 "Unknown error" without a classification: 3x the normal exponential delay.
        if status_code == 403 and "unknown error" in error_message.lower():
            return base_delay * 3 * (2**retry_count)
        
        return base_delay * (2**retry_count)
    
    def record_retry_result(self, error_classification: str, success: bool):
        """Feed a retry outcome into the adaptive backoff history; ignored if no classification."""
        if error_classification:
            self.backoff_strategy.record_attempt(error_classification, success)
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Summarize attempts recorded in the last 5 minutes (total, success rate, per-type counts)."""
        current_time = time.time()
        recent_errors = [
            entry for entry in self.backoff_strategy.error_history 
            if current_time - entry[0] <= 300  # seconds
        ]
        
        if not recent_errors:
            return {"total_attempts": 0, "success_rate": 0.0, "error_types": {}}
        
        error_type_stats = {}
        for _, error_type, success in recent_errors:
            if error_type not in error_type_stats:
                error_type_stats[error_type] = {"total": 0, "success": 0}
            error_type_stats[error_type]["total"] += 1
            if success:
                error_type_stats[error_type]["success"] += 1
        
        total_success = sum(1 for entry in recent_errors if entry[2])
        overall_success_rate = total_success / len(recent_errors)
        
        return {
            "total_attempts": len(recent_errors),
            "success_rate": overall_success_rate,
            "error_types": error_type_stats,
            "time_window_minutes": 5
        }
