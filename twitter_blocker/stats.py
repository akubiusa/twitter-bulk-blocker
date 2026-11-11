"""Prints processing statistics from the database."""

from typing import Any, Dict, List

from .manager import BulkBlockManager


def show_stats(manager: BulkBlockManager) -> None:
    """Print overall progress, failure breakdown and retry candidates."""
    total_targets = len(manager.load_target_users())
    blocked_count = manager.get_blocked_users_count()
    remaining_count = len(manager.get_remaining_users())
    retry_candidates = manager.get_retry_candidates()

    detailed_stats = manager.database.get_detailed_stats()
    
    # Permanent failures count as processed. Effectively only "suspended": get_detailed_stats has no not_found/deactivated keys (they are folded into "unavailable", not counted here).
    permanent_failures = (
        detailed_stats.get("suspended", 0) + 
        detailed_stats.get("not_found", 0) + 
        detailed_stats.get("deactivated", 0)
    )
    
    processed_count = blocked_count + permanent_failures
    
    # Completion rate counts blocked + permanent failures against total targets
    if total_targets > 0:
        actual_completion_rate = min(100.0, (processed_count / total_targets) * 100)
        effective_remaining = max(0, total_targets - processed_count)
    else:
        actual_completion_rate = 100.0
        effective_remaining = 0

    print("=== 処理統計 ===")
    print(f"全対象ユーザー: {total_targets:,}人")
    print(f"ブロック済み: {blocked_count:,}人")
    if permanent_failures > 0:
        print(f"永続的失敗: {permanent_failures:,}人 (suspended/not_found/deactivated)")
        print(f"実質完了率: {actual_completion_rate:.1f}% (処理済み: {processed_count:,}/{total_targets:,})")
        print(f"実質未処理: {effective_remaining:,}人")
    else:
        print(f"完了率: {actual_completion_rate:.1f}%")
        print(f"残り未処理: {remaining_count:,}人")

    if detailed_stats["failed"] > 0:
        print(f"失敗: {detailed_stats['failed']}人")
        if detailed_stats["failed_max_retries"] > 0:
            print(f"  - リトライ上限到達: {detailed_stats['failed_max_retries']}人")
        if detailed_stats["failed_retryable"] > 0:
            print(f"  - リトライ可能: {detailed_stats['failed_retryable']}人")
        _show_failure_breakdown(manager)

    if actual_completion_rate >= 100.0:
        print("🎉 処理状況: 完全完了（100%）")
        print("📋 説明: 全ユーザーが処理済み（ブロック成功 + 技術的にブロック不可能）")
    elif effective_remaining > 0:
        print(f"🔄 処理状況: 継続中 ({effective_remaining:,}人が未処理)")
    
    if detailed_stats["follow_relationship"] > 0:
        print(f"\nフォロー関係でスキップ: {detailed_stats['follow_relationship']}人")

    if detailed_stats["suspended"] > 0:
        print(f"suspended: {detailed_stats['suspended']}人")

    if detailed_stats.get("not_found", 0) > 0:
        print(f"not_found (削除済み): {detailed_stats['not_found']}人")
        
    if detailed_stats.get("deactivated", 0) > 0:
        print(f"deactivated (無効化済み): {detailed_stats['deactivated']}人")

    if detailed_stats["unavailable"] > 0:
        print(f"利用不可: {detailed_stats['unavailable']}人")

    if len(retry_candidates) > 0:
        print(f"\nリトライ候補: {len(retry_candidates)}人")
        _show_retry_details(retry_candidates)


def _show_retry_details(retry_candidates: List[Dict[str, Any]]) -> None:
    """Print retry candidate counts by user status. The HTTP-code part is currently dead: get_retry_candidates dicts carry no response_code."""
    status_counts = {}
    code_counts = {}
    
    for candidate in retry_candidates:
        user_status = candidate.get("user_status", "unknown")
        response_code = candidate.get("response_code")
        
        if user_status != "unknown":
            status_counts[user_status] = status_counts.get(user_status, 0) + 1
        
        if response_code:
            code_counts[response_code] = code_counts.get(response_code, 0) + 1
    
    for status, count in status_counts.items():
        print(f"  - {status}: {count}人")
    
    if code_counts:
        print("  - HTTPエラー:")
        for code, count in sorted(code_counts.items()):
            print(f"    {code}: {count}人")


def _show_failure_breakdown(manager: BulkBlockManager) -> None:
    """Print failure counts by user status, HTTP status code and error type."""
    breakdown = manager.database.get_failure_breakdown()
    
    if breakdown["by_status"]:
        print("  - ステータス別:")
        for status, count in breakdown["by_status"].items():
            print(f"    {status}: {count}人")
    
    if breakdown["by_response_code"]:
        print("  - HTTPエラー別:")
        for code, count in sorted(breakdown["by_response_code"].items()):
            print(f"    {code}: {count}人")
    
    if breakdown["by_error_type"]:
        print("  - エラータイプ別:")
        for error_type, count in breakdown["by_error_type"].items():
            print(f"    {error_type}: {count}人")
        
        # When errors are classified as "other", show sample raw messages
        if breakdown["by_error_type"].get("other", 0) > 0:
            print("  - エラーメッセージサンプル (other):")
            error_samples = manager.database.get_error_message_samples(3)
            for i, sample in enumerate(error_samples, 1):
                print(f"    {i}. {sample}")
