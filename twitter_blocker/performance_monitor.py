"""Performance metrics, bottleneck detection and degradation alerts, stored in SQLite."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .database import DatabaseManager


class PerformanceMonitor:
    """Per-session performance monitor backed by the shared SQLite database."""
    
    def __init__(self, database_manager: DatabaseManager):
        self.db = database_manager
        self.session_id = self._generate_session_id()
        self.baseline_performance = None
        self.performance_history = []
        self.init_performance_tables()
    
    def _generate_session_id(self) -> str:
        """Return a session ID of the form perf_<epoch>_<YYYYmmdd_HHMMSS>."""
        return f"perf_{int(time.time())}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def init_performance_tables(self):
        """Create the performance_metrics, processing_speed_stats and performance_alerts tables if missing."""
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT,
                    context_json TEXT,
                    runtime_hours REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processing_speed_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    time_window_start REAL NOT NULL,
                    time_window_end REAL NOT NULL,
                    total_processed INTEGER DEFAULT 0,
                    total_blocked INTEGER DEFAULT 0,
                    total_errors INTEGER DEFAULT 0,
                    avg_processing_time REAL,
                    requests_per_second REAL,
                    success_rate REAL,
                    bottleneck_detected BOOLEAN DEFAULT FALSE,
                    bottleneck_type TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,  -- LOW, MEDIUM, HIGH, CRITICAL
                    title TEXT NOT NULL,
                    description TEXT,
                    metrics_json TEXT,
                    recommendations_json TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            print(f"🚀 パフォーマンス監視テーブル初期化完了: {self.db.db_file}")
    
    def record_processing_metrics(self, metrics: Dict[str, Any]) -> None:
        """Insert one performance_metrics row per metric in `metrics`.

        Args:
            metrics: Metric name to numeric value. 'runtime_hours' is stored on every row
                and 'context' (a JSON-serializable dict) is stored as context_json;
                neither is recorded as a metric itself.
        """
        current_time = time.time()
        runtime_hours = metrics.get('runtime_hours', 0)
        
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            for metric_type, value in metrics.items():
                if metric_type in ['runtime_hours', 'context']:
                    continue
                
                cursor.execute("""
                    INSERT INTO performance_metrics 
                    (timestamp, session_id, metric_type, value, unit, context_json, runtime_hours)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    current_time,
                    self.session_id,
                    metric_type,
                    float(value),
                    self._get_metric_unit(metric_type),
                    json.dumps(metrics.get('context', {})),
                    runtime_hours
                ))
    
    def _get_metric_unit(self, metric_type: str) -> str:
        """Return the unit for a metric name, or 'unknown' if unregistered."""
        units = {
            'processing_time': 'seconds',
            'requests_per_second': 'rps',
            'success_rate': 'percentage',
            'memory_usage': 'MB',
            'cpu_usage': 'percentage',
            'cache_hit_rate': 'percentage',
            'batch_size': 'count',
            'retry_rate': 'percentage',
            'response_time': 'ms'
        }
        return units.get(metric_type, 'unknown')
    
    def update_processing_window(self, window_data: Dict[str, Any]) -> None:
        """Insert a processing_speed_stats row for a time window, flagging any bottleneck.

        Args:
            window_data: Must contain 'window_start' and 'window_end' (epoch seconds).
                Optional: total_processed, total_blocked, total_errors,
                avg_processing_time (seconds), requests_per_second, success_rate (0-1).
        """
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            bottleneck_detected, bottleneck_type = self._detect_bottleneck(window_data)
            
            cursor.execute("""
                INSERT INTO processing_speed_stats 
                (session_id, time_window_start, time_window_end, total_processed, 
                 total_blocked, total_errors, avg_processing_time, requests_per_second,
                 success_rate, bottleneck_detected, bottleneck_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.session_id,
                window_data['window_start'],
                window_data['window_end'],
                window_data.get('total_processed', 0),
                window_data.get('total_blocked', 0),
                window_data.get('total_errors', 0),
                window_data.get('avg_processing_time', 0),
                window_data.get('requests_per_second', 0),
                window_data.get('success_rate', 1.0),
                bottleneck_detected,
                bottleneck_type
            ))
    
    def _detect_bottleneck(self, window_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Check one window against fixed thresholds.

        Returns:
            (detected, comma-separated bottleneck names or None).
        """
        bottlenecks = []
        
        rps = window_data.get('requests_per_second', 0)
        if rps < 1.0:  # below 1 request/second
            bottlenecks.append('low_request_rate')
        
        avg_time = window_data.get('avg_processing_time', 0)
        if avg_time > 5.0:  # seconds
            bottlenecks.append('high_processing_time')
        
        success_rate = window_data.get('success_rate', 1.0)
        if success_rate < 0.8:  # below 80%
            bottlenecks.append('low_success_rate')
        
        total_requests = window_data.get('total_processed', 0) + window_data.get('total_errors', 0)
        if total_requests > 0:
            error_rate = window_data.get('total_errors', 0) / total_requests
            if error_rate > 0.2:  # above 20% of processed + errors
                bottlenecks.append('high_error_rate')
        
        return len(bottlenecks) > 0, ','.join(bottlenecks) if bottlenecks else None
    
    def analyze_performance_degradation(self) -> Dict[str, Any]:
        """Compare the last hour of this session against its first hour (runtime_hours <= 1.0).

        Returns:
            Dict with baseline_comparison, processing_speed_trends,
            degradation_patterns and recommendations.
        """
        current_time = time.time()
        
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT metric_type, AVG(value) as avg_value, COUNT(*) as count
                FROM performance_metrics 
                WHERE session_id = ? AND timestamp > ?
                GROUP BY metric_type
            """, (self.session_id, current_time - 3600))
            
            recent_metrics = {row[0]: {'avg': row[1], 'count': row[2]} for row in cursor.fetchall()}
            
            # Baseline: metrics recorded during the first hour of runtime.
            cursor.execute("""
                SELECT metric_type, AVG(value) as avg_value, COUNT(*) as count
                FROM performance_metrics 
                WHERE session_id = ? AND runtime_hours <= 1.0
                GROUP BY metric_type
            """, (self.session_id,))
            
            baseline_metrics = {row[0]: {'avg': row[1], 'count': row[2]} for row in cursor.fetchall()}
            
            cursor.execute("""
                SELECT AVG(requests_per_second) as avg_rps,
                       AVG(avg_processing_time) as avg_proc_time,
                       AVG(success_rate) as avg_success_rate,
                       COUNT(CASE WHEN bottleneck_detected THEN 1 END) as bottleneck_count,
                       COUNT(*) as total_windows
                FROM processing_speed_stats 
                WHERE session_id = ?
            """, (self.session_id,))
            
            speed_stats = cursor.fetchone()
        
        degradation_analysis = {
            "status": "analysis_complete",
            "baseline_comparison": self._compare_with_baseline(recent_metrics, baseline_metrics),
            "processing_speed_trends": {
                "avg_rps": speed_stats[0] if speed_stats else 0,
                "avg_processing_time": speed_stats[1] if speed_stats else 0,
                "avg_success_rate": speed_stats[2] if speed_stats else 1.0,
                "bottleneck_frequency": speed_stats[3] / max(speed_stats[4], 1) if speed_stats and speed_stats[4] > 0 else 0
            },
            "degradation_patterns": self._identify_degradation_patterns(recent_metrics, baseline_metrics),
            "recommendations": []
        }
        
        degradation_analysis["recommendations"] = self._generate_performance_recommendations(degradation_analysis)
        
        return degradation_analysis
    
    def _compare_with_baseline(self, recent: Dict, baseline: Dict) -> Dict[str, Any]:
        """Compute per-metric percent change of recent vs baseline averages.

        Metrics with a non-positive baseline average are omitted.
        "trend" is "improved" above +5%, "degraded" below -5%, else "stable",
        based on the sign of the change only, regardless of which direction is good for the metric.
        """
        comparison = {}
        
        for metric_type in set(recent.keys()) | set(baseline.keys()):
            recent_val = recent.get(metric_type, {}).get('avg', 0)
            baseline_val = baseline.get(metric_type, {}).get('avg', 0)
            
            if baseline_val > 0:
                change_percent = ((recent_val - baseline_val) / baseline_val) * 100
                comparison[metric_type] = {
                    "recent_avg": recent_val,
                    "baseline_avg": baseline_val,
                    "change_percent": change_percent,
                    "trend": "improved" if change_percent > 5 else "degraded" if change_percent < -5 else "stable"
                }
        
        return comparison
    
    def _identify_degradation_patterns(self, recent: Dict, baseline: Dict) -> Dict[str, bool]:
        """Flag known degradation patterns by thresholding percent change from baseline."""
        patterns = {
            "processing_time_increase": False,
            "request_rate_decrease": False,
            "success_rate_decline": False,
            "memory_leak_suspected": False,
            "cache_efficiency_drop": False
        }
        
        comparison = self._compare_with_baseline(recent, baseline)
        
        if "processing_time" in comparison:
            if comparison["processing_time"]["change_percent"] > 50:
                patterns["processing_time_increase"] = True
        
        if "requests_per_second" in comparison:
            if comparison["requests_per_second"]["change_percent"] < -30:
                patterns["request_rate_decrease"] = True
        
        if "success_rate" in comparison:
            if comparison["success_rate"]["change_percent"] < -10:
                patterns["success_rate_decline"] = True
        
        if "memory_usage" in comparison:
            if comparison["memory_usage"]["change_percent"] > 100:
                patterns["memory_leak_suspected"] = True
        
        if "cache_hit_rate" in comparison:
            if comparison["cache_hit_rate"]["change_percent"] < -20:
                patterns["cache_efficiency_drop"] = True
        
        return patterns
    
    def _generate_performance_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Map degradation patterns and speed trends to human-readable recommendation strings."""
        recommendations = []
        patterns = analysis.get("degradation_patterns", {})
        speed_trends = analysis.get("processing_speed_trends", {})
        
        if patterns.get("processing_time_increase"):
            recommendations.append("🐌 処理時間の大幅増加検出 - バッチサイズの調整を推奨")
            recommendations.append("🔧 データベース接続プールの最適化を検討")
        
        if patterns.get("request_rate_decrease"):
            recommendations.append("📉 リクエスト処理率低下 - 並行処理数の見直しが必要")
            recommendations.append("⚡ レート制限設定の緩和を検討")
        
        if patterns.get("success_rate_decline"):
            recommendations.append("❌ 成功率低下検出 - エラーハンドリングの強化が必要")
            recommendations.append("🔄 リトライ戦略の見直しを推奨")
        
        if patterns.get("memory_leak_suspected"):
            recommendations.append("🧠 メモリリーク疑い - キャッシュクリアの実行を推奨")
            recommendations.append("🔄 定期的なセッションリセットの実装を検討")
        
        if patterns.get("cache_efficiency_drop"):
            recommendations.append("💾 キャッシュ効率低下 - キャッシュTTLの調整が必要")
            recommendations.append("🗂️ キャッシュ戦略の見直しを推奨")
        
        bottleneck_freq = speed_trends.get("bottleneck_frequency", 0)
        if bottleneck_freq > 0.3:  # bottlenecks in more than 30% of windows
            recommendations.append(f"🚧 ボトルネック頻発 ({bottleneck_freq:.1%}) - システム全体の見直しが必要")
        
        avg_rps = speed_trends.get("avg_rps", 0)
        if avg_rps < 0.5:  # below 0.5 requests/second
            recommendations.append("🐢 極端な処理速度低下 - 緊急対応が必要")
            recommendations.append("🛠️ システム再起動の検討を推奨")
        
        return recommendations
    
    def create_performance_alert(self, alert_type: str, severity: str, 
                                title: str, description: str = "", 
                                metrics: Dict = None, recommendations: List[str] = None) -> None:
        """Insert a performance_alerts row; metrics and recommendations are stored as JSON."""
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO performance_alerts 
                (session_id, alert_type, severity, title, description, 
                 metrics_json, recommendations_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self.session_id,
                alert_type,
                severity,
                title,
                description,
                json.dumps(metrics or {}),
                json.dumps(recommendations or [])
            ))
    
    def check_degradation_thresholds(self, current_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Raise and persist alerts for severe degradation in `current_metrics`.

        Args:
            current_metrics: May contain requests_per_second, success_rate (0-1)
                and avg_processing_time (seconds).

        Returns:
            The alert dicts created (each already saved via create_performance_alert).
        """
        alerts = []
        
        rps = current_metrics.get('requests_per_second', 0)
        if rps < 0.1:  # below 0.1 requests/second
            alert = {
                "alert_type": "critical_speed_degradation",
                "severity": "CRITICAL",
                "title": "処理速度の重大な低下",
                "description": f"リクエスト処理速度が{rps:.3f}rpsまで低下",
                "recommendations": [
                    "即座にシステム調査を実行",
                    "ボトルネック原因の特定",
                    "緊急メンテナンスの検討"
                ]
            }
            alerts.append(alert)
            self.create_performance_alert(**alert)
        
        success_rate = current_metrics.get('success_rate', 1.0)
        if success_rate < 0.5:  # below 50%
            alert = {
                "alert_type": "critical_success_rate_drop",
                "severity": "HIGH",
                "title": "成功率の重大な低下",
                "description": f"処理成功率が{success_rate:.1%}まで低下",
                "recommendations": [
                    "エラーログの詳細確認",
                    "認証状態の再確認",
                    "Cookie再読み込みの実行"
                ]
            }
            alerts.append(alert)
            self.create_performance_alert(**alert)
        
        avg_time = current_metrics.get('avg_processing_time', 0)
        if avg_time > 10.0:  # seconds
            alert = {
                "alert_type": "high_processing_time",
                "severity": "MEDIUM",
                "title": "処理時間の異常増加",
                "description": f"平均処理時間が{avg_time:.1f}秒まで増加",
                "recommendations": [
                    "データベース接続状態の確認",
                    "キャッシュ効率の確認",
                    "バッチサイズの調整"
                ]
            }
            alerts.append(alert)
            self.create_performance_alert(**alert)
        
        return alerts
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Return the latest stats window and active alert counts for this session."""
        current_time = time.time()
        
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT requests_per_second, avg_processing_time, success_rate,
                       bottleneck_detected, bottleneck_type
                FROM processing_speed_stats 
                WHERE session_id = ?
                ORDER BY time_window_end DESC
                LIMIT 1
            """, (self.session_id,))
            
            latest_stats = cursor.fetchone()
            
            cursor.execute("""
                SELECT COUNT(*) as active_alerts,
                       COUNT(CASE WHEN severity = 'CRITICAL' THEN 1 END) as critical_alerts
                FROM performance_alerts 
                WHERE session_id = ? AND resolved = FALSE
            """, (self.session_id,))
            
            alert_stats = cursor.fetchone()
        
        summary = {
            "session_id": self.session_id,
            "monitoring_active": True,
            "latest_performance": {
                "requests_per_second": latest_stats[0] if latest_stats else 0,
                "avg_processing_time": latest_stats[1] if latest_stats else 0,
                "success_rate": latest_stats[2] if latest_stats else 1.0,
                "bottleneck_detected": latest_stats[3] if latest_stats else False,
                "bottleneck_type": latest_stats[4] if latest_stats else None
            },
            "alerts": {
                "active_count": alert_stats[0] if alert_stats else 0,
                "critical_count": alert_stats[1] if alert_stats else 0
            },
            "recommendations_available": True
        }
        
        return summary