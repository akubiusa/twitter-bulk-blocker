"""User status history, trend and anomaly analysis, and 403 risk scoring, stored in SQLite."""

import json
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .database import DatabaseManager


class UserStatusMonitor:
    """Per-session monitor of user status history, predictions and alerts."""
    
    def __init__(self, database_manager: DatabaseManager):
        self.db = database_manager
        self.session_id = self._generate_session_id()
        self.init_monitoring_tables()
    
    def _generate_session_id(self) -> str:
        """Return a session ID of the form status_<epoch>_<YYYYmmdd_HHMMSS>."""
        return f"status_{int(time.time())}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def init_monitoring_tables(self):
        """Create the user_status_history, user_status_alerts and status_change_predictions tables if missing."""
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    total_users INTEGER NOT NULL,
                    blocked_users INTEGER NOT NULL,
                    failed_users INTEGER NOT NULL,
                    active_failed INTEGER NOT NULL,
                    suspended_failed INTEGER NOT NULL,
                    permanent_failures INTEGER NOT NULL,
                    completion_rate REAL NOT NULL,
                    runtime_hours REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_status_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    metrics_json TEXT,
                    predictions_json TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS status_change_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    service_name TEXT NOT NULL,
                    prediction_type TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    estimated_time_hours REAL,
                    predicted_change_count INTEGER,
                    factors_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            print(f"👥 ユーザーステータス監視テーブル初期化完了: {self.db.db_file}")
    
    def record_service_status(self, service_data: Dict[str, Any]) -> None:
        """Insert a user_status_history row for a service.

        Args:
            service_data: Must contain service_name, total_users, blocked_users, failed_users,
                active_failed, suspended_failed, permanent_failures and completion_rate (0-1).
                Optional: runtime_hours (defaults to 0).
        """
        current_time = time.time()
        
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO user_status_history 
                (timestamp, session_id, service_name, total_users, blocked_users, 
                 failed_users, active_failed, suspended_failed, permanent_failures, 
                 completion_rate, runtime_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                current_time,
                self.session_id,
                service_data['service_name'],
                service_data['total_users'],
                service_data['blocked_users'],
                service_data['failed_users'],
                service_data['active_failed'],
                service_data['suspended_failed'],
                service_data['permanent_failures'],
                service_data['completion_rate'],
                service_data.get('runtime_hours', 0)
            ))
    
    def analyze_status_changes(self, service_name: str) -> Dict[str, Any]:
        """Analyze the last 24 hours of history for one service.

        Side effect: predictions are saved to status_change_predictions.

        Returns:
            {"status": "insufficient_data", ...} if fewer than 2 rows exist, otherwise a dict
            with trends, predictions, anomalies and risk_assessment.
        """
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp, active_failed, suspended_failed, total_users, 
                       completion_rate, runtime_hours
                FROM user_status_history 
                WHERE service_name = ? AND timestamp > ?
                ORDER BY timestamp DESC
            """, (service_name, time.time() - 24*3600))
            
            history_data = cursor.fetchall()
            
            if len(history_data) < 2:
                return {"status": "insufficient_data", "message": "分析に十分なデータがありません"}
            
            analysis = {
                "service_name": service_name,
                "data_points": len(history_data),
                "time_span_hours": (history_data[0][0] - history_data[-1][0]) / 3600,
                "trends": self._analyze_trends(history_data),
                "predictions": self._predict_status_changes(history_data, service_name),
                "anomalies": self._detect_anomalies(history_data),
                "risk_assessment": {}
            }
            
            analysis["risk_assessment"] = self._assess_403_error_risk(analysis)
            
            return analysis
    
    def _analyze_trends(self, history_data: List[Tuple]) -> Dict[str, Any]:
        """Derive per-series trends and an overall direction from history rows.

        Args:
            history_data: Rows of (timestamp, active_failed, suspended_failed, total_users,
                completion_rate, runtime_hours) in any order.
        """
        if len(history_data) < 3:
            return {"insufficient_data": True}
        
        # Oldest first.
        sorted_data = sorted(history_data, key=lambda x: x[0])
        
        trends = {
            "active_failed_trend": self._calculate_trend([row[1] for row in sorted_data]),
            "suspended_trend": self._calculate_trend([row[2] for row in sorted_data]),
            "completion_rate_trend": self._calculate_trend([row[4] for row in sorted_data]),
            "overall_direction": "unknown"
        }
        
        active_trend = trends["active_failed_trend"]["direction"]
        completion_trend = trends["completion_rate_trend"]["direction"]
        
        if active_trend == "increasing" and completion_trend == "decreasing":
            trends["overall_direction"] = "deteriorating"
        elif active_trend == "decreasing" and completion_trend == "increasing":
            trends["overall_direction"] = "improving"
        elif active_trend == "stable" and completion_trend == "stable":
            trends["overall_direction"] = "stable"
        else:
            trends["overall_direction"] = "mixed"
        
        return trends
    
    def _calculate_trend(self, values: List[float]) -> Dict[str, Any]:
        """Compute direction, slope and change rate of a series.

        Slope is a least-squares fit against the sample index (not elapsed time).
        Returns direction, change_rate (percent, first to last value), confidence and slope;
        with fewer than 2 values, direction is "unknown" and slope is omitted.
        """
        if len(values) < 2:
            return {"direction": "unknown", "change_rate": 0, "confidence": 0}
        
        n = len(values)
        x_values = list(range(n))
        
        x_mean = sum(x_values) / n
        y_mean = sum(values) / n
        
        numerator = sum((x_values[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))
        
        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator
        
        if abs(slope) < 0.01:  # |slope| below 0.01 per sample counts as stable
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"
        
        if values[0] != 0:
            change_rate = ((values[-1] - values[0]) / values[0]) * 100
        else:
            change_rate = 0
        
        confidence = min(100, (n - 1) * 20)
        
        return {
            "direction": direction,
            "change_rate": change_rate,
            "confidence": confidence,
            "slope": slope
        }
    
    def _predict_status_changes(self, history_data: List[Tuple], service_name: str) -> Dict[str, Any]:
        """Extrapolate active_failed for the "1_hour", "3_hours" and "6_hours" scenarios from the last 5 data points and save the result.

        NOTE: the slope is per sample, not per hour; it is applied 1x/3x/6x as if samples were hourly.

        Returns:
            {"prediction_available": False} if fewer than 3 rows exist, otherwise a dict with
            predicted_scenarios keyed "1_hour", "3_hours" and "6_hours".
        """
        if len(history_data) < 3:
            return {"prediction_available": False}
        
        sorted_data = sorted(history_data, key=lambda x: x[0])
        current_active = sorted_data[-1][1]  # latest active_failed count
        
        recent_data = sorted_data[-5:]
        active_values = [row[1] for row in recent_data]
        
        trend = self._calculate_trend(active_values)
        
        predictions = {
            "prediction_available": True,
            "current_active_failed": current_active,
            "trend_direction": trend["direction"],
            "predicted_scenarios": {}
        }
        
        if trend["direction"] == "increasing":
            hourly_increase = abs(trend["slope"])
            predictions["predicted_scenarios"] = {
                "1_hour": {
                    "active_failed": current_active + hourly_increase,
                    "risk_level": "low" if hourly_increase < 10 else "medium"
                },
                "3_hours": {
                    "active_failed": current_active + hourly_increase * 3,
                    "risk_level": "medium" if hourly_increase < 10 else "high"
                },
                "6_hours": {
                    "active_failed": current_active + hourly_increase * 6,
                    "risk_level": "high" if hourly_increase > 5 else "medium"
                }
            }
        elif trend["direction"] == "stable":
            predictions["predicted_scenarios"] = {
                "1_hour": {"active_failed": current_active, "risk_level": "low"},
                "3_hours": {"active_failed": current_active, "risk_level": "low"},
                "6_hours": {"active_failed": current_active, "risk_level": "low"}
            }
        else:  # decreasing
            predictions["predicted_scenarios"] = {
                "1_hour": {"active_failed": max(0, current_active - abs(trend["slope"])), "risk_level": "low"},
                "3_hours": {"active_failed": max(0, current_active - abs(trend["slope"]) * 3), "risk_level": "low"},
                "6_hours": {"active_failed": max(0, current_active - abs(trend["slope"]) * 6), "risk_level": "low"}
            }
        
        self._save_predictions(service_name, predictions)
        
        return predictions
    
    def _save_predictions(self, service_name: str, predictions: Dict[str, Any]) -> None:
        """Save each scenario of `predictions` to status_change_predictions (no-op if unavailable)."""
        if not predictions.get("prediction_available"):
            return
        
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            for time_horizon, scenario in predictions["predicted_scenarios"].items():
                confidence = 0.8 if predictions["trend_direction"] == "stable" else 0.6
                
                cursor.execute("""
                    INSERT INTO status_change_predictions 
                    (session_id, service_name, prediction_type, confidence_score,
                     estimated_time_hours, predicted_change_count, factors_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.session_id,
                    service_name,
                    f"active_failed_{time_horizon}",
                    confidence,
                    int(time_horizon.split('_')[0]),
                    scenario["active_failed"],
                    json.dumps({"trend": predictions["trend_direction"], "risk": scenario["risk_level"]})
                ))
    
    def _detect_anomalies(self, history_data: List[Tuple]) -> List[Dict[str, Any]]:
        """Detect active_failed outliers (beyond 2 standard deviations) and sudden completion_rate jumps.

        Returns an empty list when fewer than 5 rows exist.
        """
        anomalies = []
        
        if len(history_data) < 5:
            return anomalies
        
        sorted_data = sorted(history_data, key=lambda x: x[0])
        
        active_values = [row[1] for row in sorted_data]
        avg_active = sum(active_values) / len(active_values)
        std_active = (sum((x - avg_active) ** 2 for x in active_values) / len(active_values)) ** 0.5
        
        for i, row in enumerate(sorted_data):
            active_failed = row[1]
            if abs(active_failed - avg_active) > 2 * std_active:
                anomalies.append({
                    "type": "active_failed_spike",
                    "timestamp": row[0],
                    "value": active_failed,
                    "expected_range": f"{avg_active - 2*std_active:.0f} - {avg_active + 2*std_active:.0f}",
                    "severity": "high" if abs(active_failed - avg_active) > 3 * std_active else "medium"
                })
        
        completion_rates = [row[4] for row in sorted_data]
        for i in range(1, len(completion_rates)):
            rate_change = abs(completion_rates[i] - completion_rates[i-1])
            if rate_change > 0.1:  # completion_rate is a 0-1 fraction
                anomalies.append({
                    "type": "completion_rate_jump",
                    "timestamp": sorted_data[i][0],
                    "value": completion_rates[i],
                    "change": rate_change,
                    "severity": "high" if rate_change > 0.2 else "medium"
                })
        
        return anomalies
    
    def _assess_403_error_risk(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Score 403-error risk (0-100) from trends, predictions and anomalies in `analysis`.

        Returns:
            Dict with risk_level (LOW/MEDIUM/HIGH/CRITICAL at scores 30/50/70),
            risk_score, risk_factors and recommendations.
        """
        risk_factors = []
        risk_score = 0
        
        trends = analysis.get("trends", {})
        predictions = analysis.get("predictions", {})
        anomalies = analysis.get("anomalies", [])
        
        if trends.get("active_failed_trend", {}).get("direction") == "increasing":
            risk_factors.append("Active失敗数の増加傾向")
            risk_score += 30
        
        if trends.get("completion_rate_trend", {}).get("direction") == "decreasing":
            risk_factors.append("完了率の低下傾向")
            risk_score += 25
        
        if predictions.get("prediction_available"):
            for scenario in predictions.get("predicted_scenarios", {}).values():
                if scenario.get("risk_level") == "high":
                    risk_factors.append("高リスク予測シナリオの存在")
                    risk_score += 20
                    break
        
        high_severity_anomalies = [a for a in anomalies if a.get("severity") == "high"]
        if high_severity_anomalies:
            risk_factors.append(f"高重要度異常値 ({len(high_severity_anomalies)}件)")
            risk_score += len(high_severity_anomalies) * 15
        
        if risk_score >= 70:
            risk_level = "CRITICAL"
        elif risk_score >= 50:
            risk_level = "HIGH"
        elif risk_score >= 30:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        
        return {
            "risk_level": risk_level,
            "risk_score": min(100, risk_score),
            "risk_factors": risk_factors,
            "recommendations": self._generate_risk_recommendations(risk_level, risk_factors)
        }
    
    def _generate_risk_recommendations(self, risk_level: str, risk_factors: List[str]) -> List[str]:
        """Return recommendation strings for a risk level plus extras matched on risk_factors text.

        The factor matching is by substring of the Japanese factor strings produced by _assess_403_error_risk.
        """
        recommendations = []
        
        if risk_level == "CRITICAL":
            recommendations.extend([
                "🚨 緊急対応: システム停止を検討",
                "🔍 詳細調査: active失敗の急増原因を特定",
                "🛠️ 即座修正: Cookie再読み込み・ヘッダー変更",
                "📊 監視強化: 1時間以内の再チェック"
            ])
        elif risk_level == "HIGH":
            recommendations.extend([
                "⚠️ 予防的対応: 処理速度の調整",
                "🔄 システム調整: バックオフ時間の延長",
                "📈 監視頻度: 2時間以内の再チェック",
                "🛡️ 対策準備: 緊急停止手順の確認"
            ])
        elif risk_level == "MEDIUM":
            recommendations.extend([
                "📊 継続監視: トレンドの注意深い観察",
                "🔧 予防保守: システム設定の最適化",
                "📅 定期チェック: 4-6時間後の再確認"
            ])
        else:  # LOW
            recommendations.extend([
                "✅ 現状維持: 安定した状態を継続",
                "📋 定期監視: 通常の監視スケジュール"
            ])
        
        for factor in risk_factors:
            if "Active失敗数の増加" in factor:
                recommendations.append("🔍 Active失敗の詳細分析: エラータイプの分類確認")
            if "完了率の低下" in factor:
                recommendations.append("📈 処理効率の改善: バッチサイズ・遅延の調整")
            if "高重要度異常値" in factor:
                recommendations.append("🕵️ 異常値調査: 特定時間帯の詳細ログ確認")
        
        return recommendations
    
    def create_status_alert(self, service_name: str, alert_type: str, severity: str,
                           title: str, description: str = "",
                           metrics: Dict = None, predictions: Dict = None) -> None:
        """Insert a user_status_alerts row; metrics and predictions are stored as JSON."""
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO user_status_alerts 
                (session_id, service_name, alert_type, severity, title, 
                 description, metrics_json, predictions_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.session_id,
                service_name,
                alert_type,
                severity,
                title,
                description,
                json.dumps(metrics or {}),
                json.dumps(predictions or {})
            ))
    
    def get_monitoring_summary(self) -> Dict[str, Any]:
        """Return the latest row per service and unresolved alert counts for this session."""
        with sqlite3.connect(self.db.db_file) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT service_name, active_failed, completion_rate, 
                       MAX(timestamp) as latest_timestamp
                FROM user_status_history 
                WHERE session_id = ?
                GROUP BY service_name
            """, (self.session_id,))
            
            services_status = cursor.fetchall()
            
            cursor.execute("""
                SELECT COUNT(*) as total_alerts,
                       COUNT(CASE WHEN severity = 'CRITICAL' THEN 1 END) as critical_alerts,
                       COUNT(CASE WHEN severity = 'HIGH' THEN 1 END) as high_alerts
                FROM user_status_alerts 
                WHERE session_id = ? AND resolved = FALSE
            """, (self.session_id,))
            
            alert_counts = cursor.fetchone()
        
        summary = {
            "session_id": self.session_id,
            "monitoring_active": True,
            "services_monitored": len(services_status),
            "services_status": [
                {
                    "service_name": row[0],
                    "active_failed": row[1],
                    "completion_rate": row[2],
                    "last_updated": datetime.fromtimestamp(row[3]).isoformat()
                }
                for row in services_status
            ],
            "alerts": {
                "total": alert_counts[0] if alert_counts else 0,
                "critical": alert_counts[1] if alert_counts else 0,
                "high": alert_counts[2] if alert_counts else 0
            }
        }
        
        return summary