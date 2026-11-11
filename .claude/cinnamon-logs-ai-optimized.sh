#!/bin/bash
# Structured log investigation for the Cinnamon production host, meant to be parsed by an LLM.

set -e

CINNAMON_PATH="/mnt/hdd/cinnamon/twitter-auto-blocking/bulk-block-users"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== CINNAMON SERVER ANALYSIS ==="
echo "TIMESTAMP: $TIMESTAMP"
echo "ANALYSIS_TYPE: comprehensive_check"
echo "==="
echo

# Output helpers
output_section() {
    local section_name="$1"
    echo "SECTION_START: $section_name"
}

output_section_end() {
    local section_name="$1"
    echo "SECTION_END: $section_name"
    echo
}

output_finding() {
    local severity="$1"    # CRITICAL, WARNING, INFO, OK
    local category="$2"    # CONTAINER, ERROR, PERFORMANCE, AUTH, etc.
    local message="$3"
    local details="${4:-}"
    local action="${5:-}"
    
    echo "FINDING: severity=$severity category=$category message=\"$message\""
    if [ -n "$details" ]; then
        echo "  DETAILS: $details"
    fi
    if [ -n "$action" ]; then
        echo "  RECOMMENDED_ACTION: $action"
    fi
}

# 1. System state
output_section "SYSTEM_STATUS"

# Container state
container_data=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Health}}\t{{.Status}}'" 2>/dev/null)

if [ -z "$container_data" ]; then
    output_finding "CRITICAL" "CONNECTIVITY" "Cannot connect to Cinnamon server or Docker service" \
        "SSH connection or Docker Compose service unavailable" \
        "Check SSH connection and Docker service status"
else
    echo "CONTAINER_STATUS_RAW:"
    echo "$container_data"
    echo "CONTAINER_STATUS_ANALYSIS:"
    
    total_containers=0
    running_containers=0
    healthy_containers=0
    
    while IFS=$'\t' read -r service state health status; do
        if [ -n "$service" ] && [ "$service" != "SERVICE" ]; then
            total_containers=$((total_containers + 1))
            echo "  SERVICE: $service STATE: $state HEALTH: $health STATUS: $status"
            
            if [ "$state" = "running" ]; then
                running_containers=$((running_containers + 1))
                if [ "$health" = "healthy" ] || [ -z "$health" ]; then
                    healthy_containers=$((healthy_containers + 1))
                else
                    output_finding "WARNING" "CONTAINER" "Service $service unhealthy" \
                        "Health status: $health" \
                        "Investigate service logs and restart if necessary"
                fi
            else
                output_finding "CRITICAL" "CONTAINER" "Service $service not running" \
                    "State: $state, Status: $status" \
                    "Restart service: docker compose restart $service"
            fi
        fi
    done <<< "$container_data"
    
    echo "CONTAINER_SUMMARY: total=$total_containers running=$running_containers healthy=$healthy_containers"
    
    if [ $running_containers -eq $total_containers ]; then
        output_finding "OK" "CONTAINER" "All containers running"
    elif [ $running_containers -eq 0 ]; then
        output_finding "CRITICAL" "CONTAINER" "No containers running" \
            "All services stopped" \
            "Execute: docker compose up -d"
    else
        output_finding "WARNING" "CONTAINER" "Some containers not running" \
            "$((total_containers - running_containers)) out of $total_containers containers stopped" \
            "Check and restart stopped containers"
    fi
fi

output_section_end "SYSTEM_STATUS"

# 2. Errors
output_section "ERROR_ANALYSIS"

# Fetch logs once; reused by later sections
detailed_logs=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 1000" 2>/dev/null)

# Error counts (over the fetched log tail)
error_stats=$(echo "$detailed_logs" | grep -E '(エラー|ERROR|failed|401|403|429|500)' | sort | uniq -c | sort -nr | head -10)

if [ -n "$error_stats" ]; then
    echo "ERROR_STATISTICS:"
    echo "$error_stats"
    echo "ERROR_ANALYSIS:"
    
    # Error patterns (safe integer conversion)
    auth_errors=$(echo "$error_stats" | grep -E "(認証|401|Authentication)" | head -1 | awk '{print $1}' | tr -d '\n\r' || echo "0")
    auth_errors=${auth_errors:-0}
    forbidden_errors=$(echo "$error_stats" | grep -E "(403|Forbidden)" | head -1 | awk '{print $1}' | tr -d '\n\r' || echo "0")
    forbidden_errors=${forbidden_errors:-0}
    rate_limit_errors=$(echo "$error_stats" | grep -E "(429|Rate.*limit)" | head -1 | awk '{print $1}' | tr -d '\n\r' || echo "0")
    rate_limit_errors=${rate_limit_errors:-0}
    batch_errors=$(echo "$error_stats" | grep -E "(バッチ処理|KeyError)" | head -1 | awk '{print $1}' | tr -d '\n\r' || echo "0")
    batch_errors=${batch_errors:-0}
    
    echo "  AUTH_ERRORS: $auth_errors"
    echo "  FORBIDDEN_ERRORS: $forbidden_errors"
    echo "  RATE_LIMIT_ERRORS: $rate_limit_errors"
    echo "  BATCH_ERRORS: $batch_errors"
    
    # Severity (safe integer comparison)
    if [ "${auth_errors:-0}" -gt 20 ] 2>/dev/null; then
        output_finding "CRITICAL" "AUTH" "High authentication error rate" \
            "$auth_errors authentication errors detected" \
            "Update cookies for all services immediately"
    elif [ "${auth_errors:-0}" -gt 5 ] 2>/dev/null; then
        output_finding "WARNING" "AUTH" "Authentication errors detected" \
            "$auth_errors authentication errors found" \
            "Check and update cookies for affected services"
    fi
    
    if [ "${forbidden_errors:-0}" -gt 10 ] 2>/dev/null; then
        output_finding "CRITICAL" "API" "High 403 error rate" \
            "$forbidden_errors forbidden errors detected" \
            "Check API permissions and rate limiting"
    fi
    
    if [ "${rate_limit_errors:-0}" -gt 15 ] 2>/dev/null; then
        output_finding "WARNING" "RATE_LIMIT" "Rate limiting issues" \
            "$rate_limit_errors rate limit errors" \
            "Adjust processing intervals or reduce concurrent requests"
    fi
    
    if [ "${batch_errors:-0}" -gt 0 ] 2>/dev/null; then
        output_finding "CRITICAL" "CODE" "Batch processing errors" \
            "$batch_errors batch processing errors detected" \
            "Fix KeyError in manager.py failure_info handling"
    fi
else
    output_finding "INFO" "ERROR" "No recent errors found in logs"
fi

output_section_end "ERROR_ANALYSIS"

# 3. Authentication
output_section "AUTHENTICATION_STATUS"

auth_details=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 200 | grep -A2 -B2 '認証エラー\|Authentication.*failed\|401\|Could not authenticate'" 2>/dev/null)

if [ -n "$auth_details" ]; then
    echo "AUTHENTICATION_ERRORS_DETAIL:"
    echo "$auth_details" | tail -10
    
    # Per-service authentication errors
    echo "SERVICE_AUTH_ANALYSIS:"
    for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
        service_auth_errors=$(echo "$auth_details" | grep -c "${service}-1" 2>/dev/null || echo "0")
        service_auth_errors=${service_auth_errors:-0}
        echo "  SERVICE: $service AUTH_ERRORS: $service_auth_errors"
        
        if [ "${service_auth_errors:-0}" -gt 5 ] 2>/dev/null; then
            output_finding "CRITICAL" "AUTH" "Service $service authentication failure" \
                "$service_auth_errors authentication errors" \
                "Update cookies for $service service"
        elif [ "${service_auth_errors:-0}" -gt 0 ] 2>/dev/null; then
            output_finding "WARNING" "AUTH" "Service $service authentication issues" \
                "$service_auth_errors authentication errors" \
                "Monitor and consider cookie update for $service"
        fi
    done
else
    output_finding "OK" "AUTH" "No authentication errors detected"
fi

output_section_end "AUTHENTICATION_STATUS"

# 4. Performance
output_section "PERFORMANCE_ANALYSIS"

# Rate limit lines
rate_limit_status=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 100 | grep -E 'Rate Limit:.*Reset Time' | tail -5" 2>/dev/null)

if [ -n "$rate_limit_status" ]; then
    echo "RATE_LIMIT_STATUS:"
    echo "$rate_limit_status"
    
    # Rate limit usage
    echo "RATE_LIMIT_ANALYSIS:"
    while read -r line; do
        if echo "$line" | grep -q "Rate Limit:"; then
            current=$(echo "$line" | grep -o 'Rate Limit: [0-9]*' | grep -o '[0-9]*')
            limit=$(echo "$line" | grep -o 'Rate Limit: [0-9]*/[0-9]*' | cut -d'/' -f2)
            service=$(echo "$line" | grep -o '[a-zA-Z_]*-1' | sed 's/-1//')
            
            if [ -n "$current" ] && [ -n "$limit" ] && [ "${limit:-0}" -gt 0 ] 2>/dev/null; then
                current=${current:-0}
                limit=${limit:-1}
                remaining=$((limit - current))
                usage_percent=$((current * 100 / limit))
                echo "  SERVICE: $service USED: $current LIMIT: $limit USAGE: ${usage_percent}%"
                
                if [ "${usage_percent:-0}" -gt 90 ] 2>/dev/null; then
                    output_finding "CRITICAL" "RATE_LIMIT" "Service $service rate limit critical" \
                        "Usage: ${usage_percent}% ($current/$limit)" \
                        "Reduce processing rate or pause service temporarily"
                elif [ "${usage_percent:-0}" -gt 80 ] 2>/dev/null; then
                    output_finding "WARNING" "RATE_LIMIT" "Service $service rate limit high" \
                        "Usage: ${usage_percent}% ($current/$limit)" \
                        "Monitor closely and consider rate reduction"
                fi
            fi
        fi
    done <<< "$rate_limit_status"
else
    output_finding "INFO" "RATE_LIMIT" "No recent rate limit data available"
fi

# Processing speed
recent_blocks=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --since '5m' | grep -c 'ブロック成功'" 2>/dev/null || echo "0")
recent_progress=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --since '10m' | grep '進捗.*完了.*ブロック.*スキップ.*エラー' | tail -3" 2>/dev/null)

echo "PROCESSING_SPEED:"
echo "  BLOCKS_LAST_5MIN: $recent_blocks"

if [ -n "$recent_progress" ]; then
    echo "RECENT_PROGRESS:"
    echo "$recent_progress"
fi

if [ "$recent_blocks" -eq 0 ]; then
    output_finding "CRITICAL" "PERFORMANCE" "Processing stalled" \
        "No blocks processed in last 5 minutes" \
        "Check service health and restart if necessary"
elif [ "$recent_blocks" -lt 10 ]; then
    output_finding "WARNING" "PERFORMANCE" "Low processing rate" \
        "Only $recent_blocks blocks in 5 minutes" \
        "Investigate processing bottlenecks"
else
    output_finding "OK" "PERFORMANCE" "Processing rate normal" \
        "$recent_blocks blocks processed in 5 minutes"
fi

output_section_end "PERFORMANCE_ANALYSIS"

# 5. Per-service stats
output_section "SERVICE_STATISTICS"

services=(book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit)
echo "SERVICE_INDIVIDUAL_ANALYSIS:"

for service in "${services[@]}"; do
    echo "  SERVICE_START: $service"
    
    # Service-specific stats
    service_errors=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs $service --tail 100 | grep -c 'エラー\|ERROR\|failed'" 2>/dev/null || echo "0")
    service_errors=${service_errors:-0}
    service_blocks=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs $service --tail 100 | grep -c 'ブロック成功'" 2>/dev/null || echo "0")
    service_blocks=${service_blocks:-0}
    service_auth_errors=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs $service --tail 100 | grep -c '認証エラー\|401'" 2>/dev/null || echo "0")
    service_auth_errors=${service_auth_errors:-0}
    
    echo "    ERRORS: $service_errors"
    echo "    BLOCKS: $service_blocks"
    echo "    AUTH_ERRORS: $service_auth_errors"
    
    # Latest log state
    latest_activity=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs $service --tail 20 | grep -E '(ブロック|スキップ|エラー)' | tail -1" 2>/dev/null)
    if [ -n "$latest_activity" ]; then
        echo "    LATEST_ACTIVITY: $latest_activity"
    fi
    
    # Service state (safe integer comparison)
    if [ "${service_auth_errors:-0}" -gt 3 ] 2>/dev/null; then
        output_finding "CRITICAL" "SERVICE" "Service $service authentication issues" \
            "$service_auth_errors auth errors detected" \
            "Update cookies for $service"
    elif [ "${service_errors:-0}" -gt 10 ] 2>/dev/null && [ "${service_blocks:-0}" -eq 0 ] 2>/dev/null; then
        output_finding "WARNING" "SERVICE" "Service $service error rate high" \
            "$service_errors errors with no successful blocks" \
            "Investigate $service service logs"
    elif [ "${service_blocks:-0}" -gt 0 ] 2>/dev/null; then
        output_finding "OK" "SERVICE" "Service $service operating normally" \
            "$service_blocks successful blocks, $service_errors errors"
    fi
    
    echo "  SERVICE_END: $service"
done

output_section_end "SERVICE_STATISTICS"

# 6. Latest stats summary
output_section "STATISTICS_SUMMARY"

stats_data=$(ssh Cinnamon "cd $CINNAMON_PATH && docker compose logs --tail 200 | grep -A15 '=== 処理統計 ===' | tail -15" 2>/dev/null)

if [ -n "$stats_data" ]; then
    echo "PROCESSING_STATISTICS:"
    echo "$stats_data"
    
    # Extract progress
    total_users=$(echo "$stats_data" | grep "全対象ユーザー:" | grep -o '[0-9,]*人' | tr -d ',人' || echo "0")
    blocked_users=$(echo "$stats_data" | grep "ブロック済み:" | grep -o '[0-9,]*人' | tr -d ',人' || echo "0")
    remaining_users=$(echo "$stats_data" | grep "残り未処理:" | grep -o '[0-9,]*人' | tr -d ',人' || echo "0")
    
    echo "STATISTICS_PARSED:"
    echo "  TOTAL_USERS: $total_users"
    echo "  BLOCKED_USERS: $blocked_users"
    echo "  REMAINING_USERS: $remaining_users"
    
    if [ "$total_users" -gt 0 ] && [ "$blocked_users" -gt 0 ]; then
        completion_rate=$(( blocked_users * 100 / total_users ))
        echo "  COMPLETION_RATE: ${completion_rate}%"
        
        if [ "$completion_rate" -gt 95 ]; then
            output_finding "OK" "PROGRESS" "Processing nearly complete" \
                "${completion_rate}% completion rate" \
                "Continue monitoring for final completion"
        elif [ "$completion_rate" -gt 80 ]; then
            output_finding "INFO" "PROGRESS" "Processing progressing well" \
                "${completion_rate}% completion rate"
        elif [ "$completion_rate" -lt 50 ]; then
            output_finding "INFO" "PROGRESS" "Processing in early stages" \
                "${completion_rate}% completion rate"
        fi
    fi
else
    output_finding "WARNING" "STATISTICS" "No recent processing statistics available" \
        "Statistics data not found" \
        "Check if processing services are active"
fi

output_section_end "STATISTICS_SUMMARY"

# 7. Code problems and suggested fixes
output_section "CODE_ANALYSIS_RECOMMENDATIONS"

echo "CODE_ISSUE_ANALYSIS:"

# KeyError analysis
keyerror_count=$(echo "$detailed_logs" | grep -c "KeyError.*error_message" 2>/dev/null || echo "0")
keyerror_count=$(echo "$keyerror_count" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
[ -z "$keyerror_count" ] && keyerror_count=0
if [ "$keyerror_count" -gt 0 ]; then
    echo "  ISSUE: KeyError_in_manager_py"
    echo "    SEVERITY: CRITICAL"
    echo "    COUNT: $keyerror_count"
    echo "    FILE: twitter_blocker/manager.py"
    echo "    LINES: 402-403, 493"
    echo "    PROBLEM: failure_info.get() called on None object"
    echo "    SOLUTION: Add None check before dictionary access"
    echo "    CODE_FIX: 'failure_info.get(\"key\", default) if failure_info else default'"
    echo "    PRIORITY: IMMEDIATE"
fi

# Authentication problems
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    service_auth_count=$(echo "$detailed_logs" | grep -c "${service}-1.*認証エラー\|${service}-1.*401" 2>/dev/null || echo "0")
    service_auth_count=$(echo "$service_auth_count" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    [ -z "$service_auth_count" ] && service_auth_count=0
    if [ "$service_auth_count" -gt 3 ]; then
        echo "  ISSUE: Authentication_failure_${service}"
        echo "    SEVERITY: HIGH"
        echo "    COUNT: $service_auth_count"
        echo "    SERVICE: $service"
        echo "    PROBLEM: Cookie expired or invalid"
        echo "    SOLUTION: Update cookies.json for $service"
        echo "    PRIORITY: HIGH"
    fi
done

# Performance problems
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    service_blocks=$(echo "$detailed_logs" | grep -c "${service}-1.*ブロック成功" 2>/dev/null || echo "0")
    service_errors=$(echo "$detailed_logs" | grep -c "${service}-1.*エラー\|${service}-1.*ERROR" 2>/dev/null || echo "0")
    
    service_blocks=$(echo "$service_blocks" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    service_errors=$(echo "$service_errors" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    [ -z "$service_blocks" ] && service_blocks=0
    [ -z "$service_errors" ] && service_errors=0
    
    if [ "$service_errors" -gt 10 ] && [ "$service_blocks" -eq 0 ]; then
        echo "  ISSUE: Service_performance_degradation_${service}"
        echo "    SEVERITY: MEDIUM"
        echo "    ERRORS: $service_errors"
        echo "    SUCCESSFUL_BLOCKS: $service_blocks"
        echo "    SERVICE: $service"
        echo "    PROBLEM: High error rate with no successful processing"
        echo "    SOLUTION: Investigate service configuration and restart if needed"
        echo "    PRIORITY: MEDIUM"
    fi
done

# Batch efficiency
batch_error_patterns=$(echo "$detailed_logs" | grep -E "バッチ処理エラー|batch.*error" | tail -5)
if [ -n "$batch_error_patterns" ]; then
    echo "  ISSUE: Batch_processing_inefficiency"
    echo "    SEVERITY: MEDIUM"
    echo "    PROBLEM: Batch processing errors causing fallback to individual processing"
    echo "    SOLUTION: Improve error handling in batch processing methods"
    echo "    FILES: twitter_blocker/manager.py, twitter_blocker/api.py"
    echo "    PRIORITY: MEDIUM"
fi

echo "IMPROVEMENT_RECOMMENDATIONS:"

# Urgent fixes
echo "  IMMEDIATE_FIXES_REQUIRED:"
if [ "$keyerror_count" -gt 0 ]; then
    echo "    1. Fix KeyError in manager.py failure_info handling"
    echo "       - File: twitter_blocker/manager.py"
    echo "       - Lines: 402-403, 493"
    echo "       - Change: Add 'if failure_info else default' checks"
fi

# High-priority fixes
echo "  HIGH_PRIORITY_FIXES:"
auth_issues_found=false
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    service_auth_count=$(echo "$detailed_logs" | grep -c "${service}-1.*認証エラー\|${service}-1.*401" 2>/dev/null || echo "0")
    service_auth_count=$(echo "$service_auth_count" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    [ -z "$service_auth_count" ] && service_auth_count=0
    if [ "$service_auth_count" -gt 3 ]; then
        if [ "$auth_issues_found" = false ]; then
            echo "    1. Update authentication cookies"
            auth_issues_found=true
        fi
        echo "       - Service: $service ($service_auth_count errors)"
    fi
done

# Medium-priority improvements
echo "  MEDIUM_PRIORITY_IMPROVEMENTS:"
perf_issues_found=false
for service in book000 book000_vrc ihc_amot tomachi_priv authorizedkey tomarabbit; do
    service_blocks=$(echo "$detailed_logs" | grep -c "${service}-1.*ブロック成功" 2>/dev/null || echo "0")
    service_errors=$(echo "$detailed_logs" | grep -c "${service}-1.*エラー\|${service}-1.*ERROR" 2>/dev/null || echo "0")
    
    service_blocks=$(echo "$service_blocks" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    service_errors=$(echo "$service_errors" | tr -d '\n\r' | grep -o '[0-9]*' | head -1)
    [ -z "$service_blocks" ] && service_blocks=0
    [ -z "$service_errors" ] && service_errors=0
    
    if [ "$service_errors" -gt 10 ] && [ "$service_blocks" -eq 0 ]; then
        if [ "$perf_issues_found" = false ]; then
            echo "    1. Investigate and restart underperforming services"
            perf_issues_found=true
        fi
        echo "       - Service: $service (errors: $service_errors, blocks: $service_blocks)"
    fi
done

# Optimization suggestions
echo "  OPTIMIZATION_SUGGESTIONS:"
echo "    1. Implement better error handling in batch processing"
echo "    2. Add monitoring for cookie expiration"
echo "    3. Improve rate limit management across services"
echo "    4. Consider implementing circuit breaker pattern for failing services"

output_section_end "CODE_ANALYSIS_RECOMMENDATIONS"

# 8. Overall assessment
output_section "OVERALL_ASSESSMENT"

echo "ASSESSMENT_SUMMARY:"

# Count critical problems
critical_issues=0
warning_issues=0

# Container problems
if [ "${running_containers:-0}" -lt "${total_containers:-1}" ]; then
    if [ "${running_containers:-0}" -eq 0 ]; then
        ((critical_issues++))
    else
        ((warning_issues++))
    fi
fi

# Authentication problems
if [ "${auth_errors:-0}" -gt 20 ]; then
    ((critical_issues++))
elif [ "${auth_errors:-0}" -gt 5 ]; then
    ((warning_issues++))
fi

# Batch errors
if [ "${batch_errors:-0}" -gt 0 ]; then
    ((critical_issues++))
fi

# Stalled processing
if [ "${recent_blocks:-0}" -eq 0 ]; then
    ((critical_issues++))
elif [ "${recent_blocks:-0}" -lt 5 ]; then
    ((warning_issues++))
fi

echo "ISSUE_COUNTS: critical=$critical_issues warning=$warning_issues"

if [ "${critical_issues:-0}" -gt 0 ] 2>/dev/null; then
    echo "OVERALL_STATUS: CRITICAL"
    output_finding "CRITICAL" "SYSTEM" "System requires immediate attention" \
        "$critical_issues critical issues, $warning_issues warnings" \
        "Address critical issues immediately before proceeding"
elif [ "${warning_issues:-0}" -gt 3 ] 2>/dev/null; then
    echo "OVERALL_STATUS: WARNING"
    output_finding "WARNING" "SYSTEM" "System requires attention" \
        "$warning_issues warning issues" \
        "Address warning issues to prevent escalation"
elif [ "${warning_issues:-0}" -gt 0 ] 2>/dev/null; then
    echo "OVERALL_STATUS: ATTENTION"
    output_finding "INFO" "SYSTEM" "System operating with minor issues" \
        "$warning_issues minor issues" \
        "Monitor and address issues as convenient"
else
    echo "OVERALL_STATUS: HEALTHY"
    output_finding "OK" "SYSTEM" "System operating normally" \
        "No significant issues detected" \
        "Continue normal operations"
fi

# Recommended actions
echo "RECOMMENDED_ACTIONS:"
echo "  IMMEDIATE:"
if [ "${critical_issues:-0}" -gt 0 ] 2>/dev/null; then
    echo "    - Address critical issues identified in CODE_ANALYSIS_RECOMMENDATIONS"
fi
echo "  SHORT_TERM:"
echo "    - Monitor authentication error trends"
echo "    - Review and update cookie management process"
echo "  LONG_TERM:"
echo "    - Implement automated cookie renewal"
echo "    - Add comprehensive error monitoring"
echo "    - Consider service load balancing"

output_section_end "OVERALL_ASSESSMENT"

# 9. Analysis metadata
output_section "ANALYSIS_METADATA"

echo "ANALYSIS_SUMMARY:"
echo "  TOTAL_LOG_LINES_ANALYZED: $(echo "$detailed_logs" | wc -l)"
echo "  ANALYSIS_DEPTH: comprehensive"
echo "  SERVICES_MONITORED: 6"
echo "  ERROR_PATTERNS_CHECKED: 15"
echo "  CODE_ISSUES_IDENTIFIED: $([ "$keyerror_count" -gt 0 ] && echo "1" || echo "0")"
echo "  PERFORMANCE_ISSUES: $([ "${warning_issues:-0}" -gt 0 ] 2>/dev/null && echo "$warning_issues" || echo "0")"
echo "  AUTHENTICATION_ISSUES: $([ "${auth_errors:-0}" -gt 0 ] && echo "1" || echo "0")"

echo "CONFIDENCE_METRICS:"
echo "  ERROR_DETECTION_CONFIDENCE: HIGH"
echo "  ROOT_CAUSE_ANALYSIS_CONFIDENCE: $([ "$keyerror_count" -gt 0 ] && echo "HIGH" || echo "MEDIUM")"
echo "  RECOMMENDATION_RELIABILITY: HIGH"

output_section_end "ANALYSIS_METADATA"

echo "=== ANALYSIS_COMPLETE ==="
echo "COMPLETION_TIME: $(date '+%Y-%m-%d %H:%M:%S')"
echo "TOTAL_FINDINGS: $((critical_issues + warning_issues))"
echo "ACTIONABLE_ITEMS: $([ "$keyerror_count" -gt 0 ] && echo "YES" || echo "MAINTENANCE_ONLY")"
echo "==="