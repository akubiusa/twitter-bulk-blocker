#!/bin/bash
# Non-interactive entry point that dispatches to the Cinnamon monitoring scripts.

set -e

SCRIPT_DIR="$(dirname "$0")"
ANALYSIS_MODE="${1:-basic}"  # basic, advanced, trend, realtime, quick, emergency
TIME_RANGE="${2:-6}"         # hours (trend mode)
MONITOR_INTERVAL="${3:-60}"  # seconds (realtime mode)

show_header() {
    echo "=== CINNAMON MONITORING SUITE ==="
    echo "MODE: $ANALYSIS_MODE"
    echo "TIME_RANGE: $TIME_RANGE hours"
    echo "TIMESTAMP: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "==="
    echo
}

show_usage() {
    echo "Usage: $0 [mode] [time_range] [monitor_interval]"
    echo "Modes:"
    echo "  basic      - Basic log investigation (default)"
    echo "  advanced   - Advanced comprehensive analysis"
    echo "  trend      - Error trend analysis"
    echo "  realtime   - Real-time monitoring (non-interactive)"
    echo "  quick      - Quick 5-minute diagnosis"
    echo "  emergency  - Emergency diagnosis mode"
    echo "  ai         - AI-optimized structured output"
    echo "Examples:"
    echo "  $0 basic"
    echo "  $0 advanced"
    echo "  $0 trend 12"
    echo "  $0 quick"
    echo "  $0 ai"
}

# Quick diagnosis
quick_diagnosis() {
    echo -e "${YELLOW}🎯 クイック診断開始${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Connectivity
    echo "1. 🔌 接続テスト中..."
    if ssh Cinnamon "echo 'Connection OK'" > /dev/null 2>&1; then
        echo -e "   ${GREEN}✅ SSH接続正常${NC}"
    else
        echo -e "   ${RED}❌ SSH接続失敗${NC}"
        return 1
    fi
    
    # Containers
    echo "2. 📦 コンテナ状態確認..."
    containers=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose ps --format '{{.Service}}\t{{.State}}'" 2>/dev/null)
    running_count=$(echo "$containers" | grep -c "running" 2>/dev/null || echo "0")
    total_count=$(echo "$containers" | wc -l)
    
    echo -e "   📊 稼働状況: ${running_count}/${total_count} コンテナ稼働中"
    
    if [ $running_count -eq $total_count ]; then
        echo -e "   ${GREEN}✅ 全コンテナ正常稼働${NC}"
    else
        echo -e "   ${YELLOW}⚠️  一部コンテナに問題${NC}"
    fi
    
    # Recent errors
    echo "3. 🚨 直近エラー確認..."
    recent_errors=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '10m' | grep -c 'エラー\\|ERROR\\|failed\\|401\\|403'" 2>/dev/null || echo "0")
    
    if [ $recent_errors -eq 0 ]; then
        echo -e "   ${GREEN}✅ 直近10分間エラーなし${NC}"
    elif [ $recent_errors -lt 5 ]; then
        echo -e "   ${YELLOW}⚠️  軽微なエラー ${recent_errors}件${NC}"
    else
        echo -e "   ${RED}🚨 エラー多発 ${recent_errors}件${NC}"
    fi
    
    # Progress
    echo "4. ⚡ 処理状況確認..."
    recent_blocks=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '5m' | grep -c 'ブロック成功'" 2>/dev/null || echo "0")
    
    if [ $recent_blocks -gt 10 ]; then
        echo -e "   ${GREEN}✅ 処理正常 (${recent_blocks}件/5分)${NC}"
    elif [ $recent_blocks -gt 0 ]; then
        echo -e "   ${YELLOW}⚠️  処理やや低調 (${recent_blocks}件/5分)${NC}"
    else
        echo -e "   ${RED}🚨 処理停滞中${NC}"
    fi
    
    # Verdict
    echo
    echo "📋 クイック診断結果:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ $running_count -eq $total_count ] && [ $recent_errors -lt 3 ] && [ $recent_blocks -gt 5 ]; then
        echo -e "${GREEN}🟢 総合判定: 正常動作中${NC}"
        echo "   推奨アクション: 継続監視"
    elif [ $recent_errors -gt 10 ] || [ $recent_blocks -eq 0 ]; then
        echo -e "${RED}🔴 総合判定: 要緊急対応${NC}"
        echo "   推奨アクション: 緊急診断モード実行"
    else
        echo -e "${YELLOW}🟡 総合判定: 要注意${NC}"
        echo "   推奨アクション: 詳細調査実行"
    fi
    
    echo
}

# Hourly throughput
performance_analysis() {
    echo -e "${PURPLE}📈 パフォーマンス解析開始${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    echo "⏰ 時間別処理量分析 (過去6時間):"
    for hour in {0..5}; do
        start_time=$(date -d "$hour hours ago" '+%Y-%m-%d %H:00:00')
        end_time=$(date -d "$hour hours ago" '+%Y-%m-%d %H:59:59')
        hour_label=$(date -d "$hour hours ago" '+%H:00-%H:59')
        
        blocks=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '6h' --until '0h' | grep 'ブロック成功' | wc -l" 2>/dev/null || echo "0")
        
        # Bar chart, one block per 10 blocks
        bar_length=$((blocks / 10))
        bar=""
        for i in $(seq 1 $bar_length); do bar="${bar}█"; done
        
        echo "  $hour_label: $blocks件 $bar"
    done
    
    echo
    echo "🔍 詳細分析のため高度ログ調査またはトレンド分析を実行することを推奨します"
    echo
}

# Emergency diagnosis
emergency_diagnosis() {
    echo -e "${RED}🚨 緊急診断モード開始${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    echo "🔍 緊急事態チェックリスト:"
    echo
    
    # 1. All containers stopped
    echo "1. 📦 コンテナ完全停止チェック..."
    running_containers=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose ps --filter 'status=running' | wc -l" 2>/dev/null || echo "0")
    if [ $running_containers -eq 0 ]; then
        echo -e "   ${RED}🚨 CRITICAL: 全コンテナ停止中${NC}"
        echo "   推奨対応: docker compose up -d で再起動"
    else
        echo -e "   ${GREEN}✅ OK: コンテナ稼働中${NC}"
    fi
    
    # 2. Authentication error spike
    echo "2. 🔐 認証エラー急増チェック..."
    auth_errors=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '30m' | grep -c '認証エラー\\|401\\|Could not authenticate'" 2>/dev/null || echo "0")
    if [ $auth_errors -gt 20 ]; then
        echo -e "   ${RED}🚨 CRITICAL: 認証エラー急増 (${auth_errors}件)${NC}"
        echo "   推奨対応: Cookie全面更新"
    elif [ $auth_errors -gt 10 ]; then
        echo -e "   ${YELLOW}⚠️ WARNING: 認証エラー増加 (${auth_errors}件)${NC}"
        echo "   推奨対応: 該当サービスのCookie更新"
    else
        echo -e "   ${GREEN}✅ OK: 認証状況正常${NC}"
    fi
    
    # 3. Rate limit exhaustion
    echo "3. 📡 レートリミット枯渇チェック..."
    rate_errors=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '30m' | grep -c '429\\|Rate limit exceeded'" 2>/dev/null || echo "0")
    if [ $rate_errors -gt 15 ]; then
        echo -e "   ${RED}🚨 CRITICAL: レートリミット枯渇 (${rate_errors}件)${NC}"
        echo "   推奨対応: 処理間隔調整またはサービス停止"
    else
        echo -e "   ${GREEN}✅ OK: レートリミット正常${NC}"
    fi
    
    # 4. Processing fully stalled
    echo "4. ⚡ 処理完全停止チェック..."
    recent_activity=$(ssh Cinnamon "cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose logs --since '15m' | grep -c 'ブロック成功\\|進捗'" 2>/dev/null || echo "0")
    if [ $recent_activity -eq 0 ]; then
        echo -e "   ${RED}🚨 CRITICAL: 処理完全停止${NC}"
        echo "   推奨対応: サービス再起動"
    else
        echo -e "   ${GREEN}✅ OK: 処理継続中${NC}"
    fi
    
    echo
    echo "🎯 緊急対応推奨アクション:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if [ $running_containers -eq 0 ]; then
        echo -e "${RED}1. ${BOLD}即座にコンテナ再起動${NC}"
        echo "   ssh Cinnamon 'cd /mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users && docker compose up -d'"
    fi
    
    if [ $auth_errors -gt 10 ]; then
        echo -e "${YELLOW}2. ${BOLD}認証情報更新${NC}"
        echo "   各サービスのCookieファイル更新"
    fi
    
    if [ $rate_errors -gt 15 ]; then
        echo -e "${YELLOW}3. ${BOLD}レートリミット対応${NC}"
        echo "   処理間隔調整またはサービス一時停止"
    fi
    
    echo
}

# Tool settings
tool_settings() {
    echo -e "${BLUE}🔧 ツール設定${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    echo "📂 利用可能なスクリプト:"
    ls -la "$SCRIPT_DIR"/cinnamon-*.sh | while read line; do
        filename=$(echo "$line" | awk '{print $9}' | sed 's|.*/||')
        size=$(echo "$line" | awk '{print $5}')
        echo "  📜 $filename (${size} bytes)"
    done
    
    echo
    echo "🔧 設定オプション:"
    echo "  • WEBHOOK_URL環境変数: Webhookアラート先URL"
    echo "  • 監視間隔: リアルタイム監視の実行間隔"
    echo "  • ログ保持期間: 分析対象ログの期間"
    echo
}

# Help text
show_help() {
    echo -e "${CYAN}📚 ヘルプ・ドキュメント${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo
    echo -e "${BOLD}📖 各ツールの詳細説明:${NC}"
    echo
    echo -e "${GREEN}🔍 基本ログ調査 (cinnamon-logs.sh):${NC}"
    echo "  • オリジナルの基本監視機能"
    echo "  • コンテナ状態、エラー統計、レートリミット確認"
    echo "  • 日常的な定期チェックに最適"
    echo
    echo -e "${GREEN}🚀 高度ログ調査 (cinnamon-logs-advanced.sh):${NC}"
    echo "  • 包括的なシステム分析"
    echo "  • リソース監視、パフォーマンス分析、自動診断"
    echo "  • 問題発生時の詳細調査に最適"
    echo
    echo -e "${PURPLE}📊 エラートレンド分析 (cinnamon-trend-analyzer.sh):${NC}"
    echo "  • 時系列でのエラーパターン分析"
    echo "  • 異常検知と予測機能"
    echo "  • 長期的なトレンド把握に最適"
    echo
    echo -e "${PURPLE}⚡ リアルタイム監視 (cinnamon-realtime-monitor.sh):${NC}"
    echo "  • 継続的な監視とアラート"
    echo "  • 自動修復候補の提示"
    echo "  • 24/7監視運用に最適"
    echo
    echo -e "${BOLD}🔧 使用方法例:${NC}"
    echo "  日常チェック     → 基本ログ調査"
    echo "  問題発生時       → 高度ログ調査 + 緊急診断モード"
    echo "  パフォーマンス   → トレンド分析 + パフォーマンス解析"
    echo "  継続監視         → リアルタイム監視"
    echo
    echo -e "${BOLD}🚨 トラブルシューティング:${NC}"
    echo "  接続失敗   → SSH設定とCinnamonサーバー状態確認"
    echo "  権限エラー → スクリプトファイルの実行権限確認"
    echo "  データなし → Docker Composeサービス状態確認"
    echo
}

# Main
main() {
    show_header
    
    case $ANALYSIS_MODE in
        "basic")
            echo "EXECUTING: Basic log investigation"
            "$SCRIPT_DIR/cinnamon-logs.sh"
            ;;
        "advanced")
            echo "EXECUTING: Advanced comprehensive analysis"
            "$SCRIPT_DIR/cinnamon-logs-advanced.sh"
            ;;
        "trend")
            echo "EXECUTING: Error trend analysis (${TIME_RANGE}h)"
            "$SCRIPT_DIR/cinnamon-trend-analyzer.sh" "$TIME_RANGE"
            ;;
        "realtime")
            echo "EXECUTING: Real-time monitoring (${MONITOR_INTERVAL}s)"
            # Single sample only
            "$SCRIPT_DIR/cinnamon-realtime-monitor.sh" "$MONITOR_INTERVAL" "single"
            ;;
        "quick")
            echo "EXECUTING: Quick diagnosis"
            quick_diagnosis
            ;;
        "emergency")
            echo "EXECUTING: Emergency diagnosis"
            emergency_diagnosis
            ;;
        "ai")
            echo "EXECUTING: AI-optimized analysis"
            "$SCRIPT_DIR/cinnamon-logs-ai-optimized.sh"
            ;;
        "help"|"--help"|"-h")
            show_usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown analysis mode '$ANALYSIS_MODE'"
            show_usage
            exit 1
            ;;
    esac
    
    echo "ANALYSIS_COMPLETED: $(date '+%Y-%m-%d %H:%M:%S')"
}

main "$@"