#!/bin/bash
# Log investigation for the Cinnamon production host (read-only ssh queries).

set -e

CINNAMON_PATH="/mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users"

echo "=== Cinnamonサーバー ログ調査 ==="
echo "実行時刻: $(date '+%Y-%m-%d %H:%M:%S')"
echo

# 1. Container state
echo "📊 コンテナ状態:"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose ps"
echo

# 2. Error counts
echo "🔍 エラー統計 (最新1000行):"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 1000 | grep -E '(エラー|error|failed|401|403|429|500)' | sort | uniq -c | sort -nr | head -20"
echo

# 3. Authentication errors
echo "🔒 認証エラーの詳細:"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 500 | grep -A3 -B3 '認証エラー\|Authentication failed\|401' | tail -20"
echo

# 4. 403 errors
echo "🚫 403エラーの詳細:"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 500 | grep -A5 -B5 'Status Code: 403' | tail -30"
echo

# 5. Rate limit lines
echo "⏱️ レートリミット状況:"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 200 | grep -E 'Rate Limit:' | tail -10"
echo

# 6. Per-service progress
echo "📈 各サービスの処理統計:"
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    echo "--- $service ---"
    ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs $service --tail 100 | grep -E '(ブロック成功|スキップ|エラー).*:' | tail -3"
done
echo

# 7. Latest stats block
echo "📊 最新の完了統計:"
ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 500 | grep -A10 '=== 処理統計 ===' | tail -20"
echo

# 8. Running vs total containers
echo "🔄 現在の稼働状況:"
RUNNING_CONTAINERS=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose ps --filter 'status=running' --format '{{.Service}}'" | wc -l)
TOTAL_CONTAINERS=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose ps --format '{{.Service}}'" | wc -l)
echo "稼働中: $RUNNING_CONTAINERS/$TOTAL_CONTAINERS コンテナ"

if [ $RUNNING_CONTAINERS -lt $TOTAL_CONTAINERS ]; then
    echo "⚠️ 停止中のコンテナ:"
    ssh Cinnamon "cd $CINNAMON_PATH && docker compose ps --filter 'status=exited'"
fi

echo
echo "=== 調査完了 ==="