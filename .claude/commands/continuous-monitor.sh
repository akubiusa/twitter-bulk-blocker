#!/bin/bash
# Runs check-cinnamon in a loop with an adaptive interval.

echo "=== CINNAMON SERVER CONTINUOUS MONITORING STARTED ==="
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Monitoring will run indefinitely with adaptive intervals (5-30 minutes)"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_CINNAMON_SCRIPT="$SCRIPT_DIR/check-cinnamon"

# Loop forever
while true; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔄 Executing check-cinnamon at $(date '+%Y-%m-%d %H:%M:%S')"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Run check-cinnamon and capture its output
    OUTPUT=$("$CHECK_CINNAMON_SCRIPT" 2>&1)
    EXIT_CODE=$?
    
    echo "$OUTPUT"
    
    # On script failure, retry soon
    if [ $EXIT_CODE -ne 0 ]; then
        echo "⚠️ WARNING: check-cinnamon script failed with exit code $EXIT_CODE"
        NEXT_INTERVAL="5 minutes"
    else
        # Interval recommended by check-cinnamon
        NEXT_INTERVAL=$(echo "$OUTPUT" | grep -E "Next check recommended:.*\(適応的間隔: ([0-9]+ minutes)\)" | sed -E 's/.*適応的間隔: ([0-9]+ minutes).*/\1/' | tail -1)
        
        # Fallback: derive the interval from the health score
        if [ -z "$NEXT_INTERVAL" ] || ! [[ "$NEXT_INTERVAL" =~ ^[0-9]+\ minutes$ ]]; then
            HEALTH_SCORE=$(echo "$OUTPUT" | grep "Overall Health Score:" | grep -o '[0-9]*' | head -1)
            
            if [ -n "$HEALTH_SCORE" ]; then
                if [ "$HEALTH_SCORE" -lt 50 ]; then
                    NEXT_INTERVAL="5 minutes"
                elif [ "$HEALTH_SCORE" -lt 80 ]; then
                    NEXT_INTERVAL="10 minutes"
                else
                    NEXT_INTERVAL="30 minutes"
                fi
                echo "ℹ️ Using health score ($HEALTH_SCORE/100) to determine interval: $NEXT_INTERVAL"
            else
                # Default
                NEXT_INTERVAL="10 minutes"
                echo "ℹ️ Using default interval: $NEXT_INTERVAL"
            fi
        fi
    fi
    
    # Critical alert markers
    if echo "$OUTPUT" | grep -q "🚨 URGENT\|🔴 HIGH RISK\|ATTENTION_REQUIRED"; then
        echo
        echo "🚨 ALERT: Critical issues detected! Next check in $NEXT_INTERVAL"
        echo
    fi
    
    # Minutes to seconds
    INTERVAL_SECONDS=$(echo "$NEXT_INTERVAL" | awk '{print $1 * 60}')
    
    echo
    echo "📊 Monitoring Summary:"
    echo "  • Current time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  • Next check: $(date -d "+$INTERVAL_SECONDS seconds" '+%Y-%m-%d %H:%M:%S')"
    echo "  • Interval: $NEXT_INTERVAL"
    echo
    echo "💤 Sleeping for $NEXT_INTERVAL..."
    echo
    
    # Wait until the next run
    timeout $INTERVAL_SECONDS sleep infinity || true
done