import numpy as np
import pandas as pd
from scipy import stats
from datetime import datetime, timedelta
import json
from db import get_db
from algorithms import load_signals
from time_analysis import compute_monthly_counts, compute_cusum, detect_trend
from data_import import load_reports
from config_manager import get_risk_weights, DEFAULT_WEIGHTS


DEFAULT_WEIGHTS_CONFIG = DEFAULT_WEIGHTS

SIGNAL_STRENGTH_MAP = {
    "强信号": 100,
    "中等信号": 60,
    "弱信号": 30,
    "无信号": 0,
}

RISK_LEVELS = [
    (80, 100, "极高风险", "#d62728", "red"),
    (60, 79, "高风险", "#ff7f0e", "orange"),
    (40, 59, "中等风险", "#feca57", "yellow"),
    (20, 39, "低风险", "#2ca02c", "green"),
    (0, 19, "极低风险", "#7f7f7f", "gray"),
]


def get_risk_level(score):
    for lower, upper, name, color, _ in RISK_LEVELS:
        if lower <= score <= upper:
            return name, color
    return "极低风险", "#7f7f7f"


def get_risk_level_info(level_name):
    for lower, upper, name, color, short in RISK_LEVELS:
        if name == level_name:
            return {"lower": lower, "upper": upper, "color": color, "short": short}
    return {"lower": 0, "upper": 19, "color": "#7f7f7f", "short": "gray"}


class BayesianNetwork:
    def __init__(self):
        self.nodes = [
            "signal_strength",
            "report_frequency",
            "severity",
            "trend",
            "overall_risk",
        ]
        self.cpt = self._build_cpt()

    def _build_cpt(self):
        states = ["low", "medium", "high"]
        cpt = {}

        cpt["signal_strength"] = {"low": 0.5, "medium": 0.3, "high": 0.2}
        cpt["report_frequency"] = {"low": 0.6, "medium": 0.25, "high": 0.15}
        cpt["severity"] = {"low": 0.7, "medium": 0.2, "high": 0.1}
        cpt["trend"] = {"low": 0.5, "medium": 0.3, "high": 0.2}

        cpt["overall_risk"] = {}
        for s in states:
            for r in states:
                for sev in states:
                    for t in states:
                        key = f"{s}_{r}_{sev}_{t}"
                        scores = []
                        if s == "high":
                            scores.append(70)
                        elif s == "medium":
                            scores.append(40)
                        else:
                            scores.append(15)

                        if r == "high":
                            scores.append(60)
                        elif r == "medium":
                            scores.append(35)
                        else:
                            scores.append(10)

                        if sev == "high":
                            scores.append(75)
                        elif sev == "medium":
                            scores.append(40)
                        else:
                            scores.append(10)

                        if t == "high":
                            scores.append(65)
                        elif t == "medium":
                            scores.append(35)
                        else:
                            scores.append(10)

                        weighted = np.mean(scores)

                        if weighted >= 60:
                            risk_dist = {"low": 0.05, "medium": 0.25, "high": 0.70}
                        elif weighted >= 35:
                            risk_dist = {"low": 0.20, "medium": 0.55, "high": 0.25}
                        else:
                            risk_dist = {"low": 0.70, "medium": 0.25, "high": 0.05}

                        cpt["overall_risk"][key] = risk_dist

        return cpt

    def _discretize(self, value, thresholds):
        if value < thresholds[0]:
            return "low"
        elif value < thresholds[1]:
            return "medium"
        else:
            return "high"

    def infer(self, evidence):
        signal_state = self._discretize(evidence.get("signal_strength", 0), [30, 70])
        freq_state = self._discretize(evidence.get("report_frequency", 0), [30, 65])
        sev_state = self._discretize(evidence.get("severity", 0), [25, 60])
        trend_state = self._discretize(evidence.get("trend", 0), [30, 60])

        parent_key = f"{signal_state}_{freq_state}_{sev_state}_{trend_state}"

        risk_dist = self.cpt["overall_risk"].get(parent_key, {"low": 0.5, "medium": 0.3, "high": 0.2})

        high_prob = risk_dist["high"]
        medium_prob = risk_dist["medium"]
        low_prob = risk_dist["low"]

        bayesian_score = high_prob * 100 + medium_prob * 50 + low_prob * 15

        return {
            "bayesian_score": bayesian_score,
            "risk_distribution": risk_dist,
            "parent_states": {
                "signal_strength": signal_state,
                "report_frequency": freq_state,
                "severity": sev_state,
                "trend": trend_state,
            },
        }


def calculate_signal_strength_factor(device_name, signals_df=None, weights=None):
    if weights is None:
        weights = get_risk_weights()
    if signals_df is None:
        signals_df = load_signals()

    if signals_df.empty:
        return 0, 0

    device_signals = signals_df[signals_df["device_name"] == device_name]
    if device_signals.empty:
        return 0, 0

    max_strength_score = 0
    for _, row in device_signals.iterrows():
        strength = row.get("signal_strength", "无信号")
        score = SIGNAL_STRENGTH_MAP.get(strength, 0)
        if score > max_strength_score:
            max_strength_score = score

    weighted_score = max_strength_score * weights["signal_strength"]
    return max_strength_score, weighted_score


def calculate_report_frequency_factor(device_name, reports_df=None, weights=None):
    if weights is None:
        weights = get_risk_weights()
    if reports_df is None:
        reports_df = load_reports()

    if reports_df.empty:
        return 0, 0

    reports_df = reports_df.copy()
    reports_df["report_date"] = pd.to_datetime(reports_df["report_date"])

    cutoff_date = datetime.now() - timedelta(days=180)
    device_reports = reports_df[
        (reports_df["device_name"] == device_name) &
        (reports_df["report_date"] >= cutoff_date)
    ]

    monthly_counts = compute_monthly_counts(device_reports, device_name)
    if monthly_counts.empty:
        monthly_avg = 0
    else:
        monthly_avg = monthly_counts["count"].mean()

    device_class = None
    device_info = reports_df[reports_df["device_name"] == device_name].iloc[0] if len(reports_df[reports_df["device_name"] == device_name]) > 0 else None
    if device_info is not None and device_info.get("device_class_code"):
        device_class = str(device_info["device_class_code"])[:4]

    if device_class:
        similar_devices = reports_df[
            reports_df["device_class_code"].str.slice(0, 4) == device_class
        ]["device_name"].unique()
    else:
        similar_devices = reports_df["device_name"].unique()

    similar_monthly_avgs = []
    for dev in similar_devices:
        if dev == device_name:
            continue
        dev_reports = reports_df[
            (reports_df["device_name"] == dev) &
            (reports_df["report_date"] >= cutoff_date)
        ]
        dev_monthly = compute_monthly_counts(dev_reports, dev)
        if not dev_monthly.empty:
            similar_monthly_avgs.append(dev_monthly["count"].mean())

    if not similar_monthly_avgs:
        similar_avg = monthly_avg if monthly_avg > 0 else 1
    else:
        similar_avg = np.mean(similar_monthly_avgs)
        if similar_avg == 0:
            similar_avg = 1

    ratio = monthly_avg / similar_avg if similar_avg > 0 else 0

    if ratio >= 3:
        raw_score = 100
    elif ratio >= 1:
        raw_score = 50 + (ratio - 1) * 25
    elif ratio >= 0.5:
        raw_score = 10 + (ratio - 0.5) * 80
    else:
        raw_score = ratio * 20

    raw_score = max(0, min(100, raw_score))
    weighted_score = raw_score * weights["report_frequency"]

    return raw_score, weighted_score


def calculate_severity_factor(device_name, reports_df=None, weights=None):
    if weights is None:
        weights = get_risk_weights()
    if reports_df is None:
        reports_df = load_reports()

    if reports_df.empty:
        return 0, 0

    device_reports = reports_df[reports_df["device_name"] == device_name]
    if device_reports.empty:
        return 0, 0

    total = len(device_reports)
    death_count = len(device_reports[device_reports["event_type"] == "死亡"])
    severe_count = len(device_reports[
        (device_reports["severity"] == "严重") &
        (device_reports["event_type"] != "死亡")
    ])

    death_ratio = death_count / total if total > 0 else 0
    severe_ratio = severe_count / total if total > 0 else 0

    raw_score = (death_ratio * 100) + (severe_ratio * 50)
    raw_score = max(0, min(100, raw_score))

    weighted_score = raw_score * weights["severity"]

    return raw_score, weighted_score


def calculate_trend_factor(device_name, reports_df=None, weights=None):
    if weights is None:
        weights = get_risk_weights()
    if reports_df is None:
        reports_df = load_reports()

    if reports_df.empty:
        return 0, 0

    device_reports = reports_df[reports_df["device_name"] == device_name]
    if device_reports.empty:
        return 0, 0

    monthly = compute_monthly_counts(device_reports, device_name)

    has_cusum_alert = False
    if len(monthly) >= 7:
        _, alerts = compute_cusum(monthly)
        has_cusum_alert = len(alerts) > 0

    trend_result = None
    if len(monthly) >= 9:
        trend_result, _, _, _ = detect_trend(monthly)

    if has_cusum_alert:
        raw_score = 100
    elif trend_result and trend_result["is_increasing"]:
        raw_score = 70
    elif trend_result and trend_result["slope"] < 0:
        raw_score = 0
    else:
        raw_score = 20

    weighted_score = raw_score * weights["trend"]

    return raw_score, weighted_score


def calculate_risk_score(device_name, signals_df=None, reports_df=None, detection_run_id=None, weights=None):
    if weights is None:
        weights = get_risk_weights()
    if reports_df is None:
        reports_df = load_reports()
    if signals_df is None:
        signals_df = load_signals()

    signal_score, signal_weighted = calculate_signal_strength_factor(device_name, signals_df, weights)
    freq_score, freq_weighted = calculate_report_frequency_factor(device_name, reports_df, weights)
    severity_score, severity_weighted = calculate_severity_factor(device_name, reports_df, weights)
    trend_score, trend_weighted = calculate_trend_factor(device_name, reports_df, weights)

    total_score = signal_weighted + freq_weighted + severity_weighted + trend_weighted
    total_score = max(0, min(100, total_score))

    bayesian = BayesianNetwork()
    bayesian_result = bayesian.infer({
        "signal_strength": signal_score,
        "report_frequency": freq_score,
        "severity": severity_score,
        "trend": trend_score,
    })

    bayesian_risk = bayesian_result["bayesian_score"]
    final_score = (total_score * 0.7) + (bayesian_risk * 0.3)
    final_score = max(0, min(100, final_score))

    risk_level, risk_color = get_risk_level(final_score)

    prediction_trend, predictions, is_upgrade_alert = predict_risk_trend(
        device_name, final_score, risk_level
    )

    return {
        "device_name": device_name,
        "total_score": final_score,
        "risk_level": risk_level,
        "risk_color": risk_color,
        "signal_strength_score": signal_score,
        "signal_strength_weighted": signal_weighted,
        "report_frequency_score": freq_score,
        "report_frequency_weighted": freq_weighted,
        "severity_score": severity_score,
        "severity_weighted": severity_weighted,
        "trend_score": trend_score,
        "trend_weighted": trend_weighted,
        "bayesian_risk": bayesian_risk,
        "bayesian_details": bayesian_result,
        "prediction_trend": prediction_trend,
        "prediction_values": predictions,
        "is_upgrade_alert": is_upgrade_alert,
        "detection_run_id": detection_run_id,
        "weights": weights,
    }


def predict_risk_trend(device_name, current_score, current_level, history_points=None):
    if history_points is None:
        history_points = get_risk_score_history(device_name, limit=10)

    predictions = []
    prediction_trend = "稳"
    is_upgrade_alert = False

    if len(history_points) >= 3:
        scores = [h["total_score"] for h in history_points]
        x = np.arange(len(scores))

        slope, intercept, r_value, p_value, std_err = stats.linregress(x, scores)

        for months_ahead in range(1, 4):
            next_x = len(scores) + months_ahead - 1
            predicted = max(0, min(100, slope * next_x + intercept))
            predictions.append({
                "months_ahead": months_ahead,
                "predicted_score": predicted,
                "predicted_level": get_risk_level(predicted)[0],
            })

        if slope > 1:
            prediction_trend = "升"
        elif slope < -1:
            prediction_trend = "降"
        else:
            prediction_trend = "稳"

        current_level_rank = _get_level_rank(current_level)
        for pred in predictions:
            pred_level_rank = _get_level_rank(pred["predicted_level"])
            if pred_level_rank < current_level_rank:
                is_upgrade_alert = True
                break
    else:
        for months_ahead in range(1, 4):
            predictions.append({
                "months_ahead": months_ahead,
                "predicted_score": current_score,
                "predicted_level": current_level,
            })

    return prediction_trend, predictions, is_upgrade_alert


def _get_level_rank(level_name):
    rank_map = {
        "极高风险": 0,
        "高风险": 1,
        "中等风险": 2,
        "低风险": 3,
        "极低风险": 4,
    }
    return rank_map.get(level_name, 4)


def save_risk_scores(risk_results, detection_run_id=None):
    with get_db() as conn:
        for result in risk_results:
            existing = conn.execute(
                "SELECT id FROM risk_scores WHERE device_name = ?",
                (result["device_name"],)
            ).fetchone()

            pred_json = json.dumps(result["prediction_values"], ensure_ascii=False)

            weights = result.get("weights", {})
            if existing:
                conn.execute(
                    """
                    UPDATE risk_scores SET
                        total_score = ?, risk_level = ?,
                        signal_strength_factor = ?, signal_strength_score = ?,
                        report_frequency_factor = ?, report_frequency_score = ?,
                        severity_factor = ?, severity_score = ?,
                        trend_factor = ?, trend_score = ?,
                        bayesian_risk = ?, prediction_trend = ?,
                        prediction_values = ?, is_upgrade_alert = ?,
                        detection_run_id = ?,
                        weight_signal_strength = ?, weight_report_frequency = ?,
                        weight_severity = ?, weight_trend = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE device_name = ?
                    """,
                    (
                        result["total_score"], result["risk_level"],
                        result["signal_strength_weighted"], result["signal_strength_score"],
                        result["report_frequency_weighted"], result["report_frequency_score"],
                        result["severity_weighted"], result["severity_score"],
                        result["trend_weighted"], result["trend_score"],
                        result["bayesian_risk"], result["prediction_trend"],
                        pred_json, 1 if result["is_upgrade_alert"] else 0,
                        detection_run_id,
                        weights.get("signal_strength", 0.40),
                        weights.get("report_frequency", 0.25),
                        weights.get("severity", 0.20),
                        weights.get("trend", 0.15),
                        result["device_name"],
                    )
                )
            else:
                conn.execute(
                    """
                    INSERT INTO risk_scores (
                        device_name, total_score, risk_level,
                        signal_strength_factor, signal_strength_score,
                        report_frequency_factor, report_frequency_score,
                        severity_factor, severity_score,
                        trend_factor, trend_score,
                        bayesian_risk, prediction_trend,
                        prediction_values, is_upgrade_alert, detection_run_id,
                        weight_signal_strength, weight_report_frequency,
                        weight_severity, weight_trend
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["device_name"], result["total_score"], result["risk_level"],
                        result["signal_strength_weighted"], result["signal_strength_score"],
                        result["report_frequency_weighted"], result["report_frequency_score"],
                        result["severity_weighted"], result["severity_score"],
                        result["trend_weighted"], result["trend_score"],
                        result["bayesian_risk"], result["prediction_trend"],
                        pred_json, 1 if result["is_upgrade_alert"] else 0, detection_run_id,
                        weights.get("signal_strength", 0.40),
                        weights.get("report_frequency", 0.25),
                        weights.get("severity", 0.20),
                        weights.get("trend", 0.15),
                    )
                )

            conn.execute(
                """
                INSERT INTO risk_score_history (
                    device_name, total_score, risk_level,
                    signal_strength_score, report_frequency_score,
                    severity_score, trend_score, bayesian_risk, detection_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["device_name"], result["total_score"], result["risk_level"],
                    result["signal_strength_score"], result["report_frequency_score"],
                    result["severity_score"], result["trend_score"],
                    result["bayesian_risk"], detection_run_id,
                )
            )

            for pred in result["prediction_values"]:
                pred_date = (datetime.now() + timedelta(days=30 * pred["months_ahead"])).date()
                conn.execute(
                    """
                    INSERT INTO risk_predictions (
                        device_name, prediction_date, predicted_score,
                        predicted_level, prediction_months_ahead, model_type
                    ) VALUES (?, ?, ?, ?, ?, 'linear')
                    """,
                    (
                        result["device_name"], str(pred_date), pred["predicted_score"],
                        pred["predicted_level"], pred["months_ahead"],
                    )
                )


def calculate_all_risk_scores(detection_run_id=None):
    reports_df = load_reports()
    signals_df = load_signals()

    if reports_df.empty:
        return []

    weights = get_risk_weights()
    all_devices = reports_df["device_name"].unique().tolist()
    results = []

    for device in all_devices:
        result = calculate_risk_score(device, signals_df, reports_df, detection_run_id, weights)
        results.append(result)

    save_risk_scores(results, detection_run_id)

    return results


def load_risk_scores(filters=None):
    with get_db() as conn:
        query = "SELECT * FROM risk_scores WHERE 1=1"
        params = []

        if filters:
            if "risk_level" in filters:
                query += " AND risk_level = ?"
                params.append(filters["risk_level"])
            if "min_score" in filters:
                query += " AND total_score >= ?"
                params.append(filters["min_score"])

        query += " ORDER BY total_score DESC"
        rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            if r.get("prediction_values"):
                try:
                    r["prediction_values"] = json.loads(r["prediction_values"])
                except (json.JSONDecodeError, TypeError):
                    r["prediction_values"] = []
            results.append(r)

        return pd.DataFrame(results) if results else pd.DataFrame()


def get_risk_score_history(device_name, limit=10):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM risk_score_history
            WHERE device_name = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (device_name, limit)
        ).fetchall()

        history = [dict(r) for r in rows]
        history.reverse()
        return history


def get_risk_score_detail(device_name):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM risk_scores WHERE device_name = ?",
            (device_name,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        if result.get("prediction_values"):
            try:
                result["prediction_values"] = json.loads(result["prediction_values"])
            except (json.JSONDecodeError, TypeError):
                result["prediction_values"] = []

        return result


def get_risk_level_counts():
    df = load_risk_scores()
    if df.empty:
        return {}

    counts = df["risk_level"].value_counts().to_dict()
    result = {}
    for level, _, name, _, _ in RISK_LEVELS:
        result[name] = counts.get(name, 0)

    return result


def get_upgrade_alerts():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM risk_scores
            WHERE is_upgrade_alert = 1
            ORDER BY total_score DESC
            """
        ).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            if r.get("prediction_values"):
                try:
                    r["prediction_values"] = json.loads(r["prediction_values"])
                except (json.JSONDecodeError, TypeError):
                    r["prediction_values"] = []
            results.append(r)

        return results


def generate_comparison_summary(devices_data):
    if not devices_data:
        return ""

    sorted_devices = sorted(devices_data, key=lambda x: x["total_score"], reverse=True)
    highest = sorted_devices[0]

    factors = []
    if highest["signal_strength_score"] >= 60:
        factors.append(f"信号强度因子({highest['signal_strength_score']:.0f}分)")
    if highest["report_frequency_score"] >= 50:
        factors.append(f"报告频率因子({highest['report_frequency_score']:.0f}分)")
    if highest["severity_score"] >= 40:
        factors.append(f"严重程度因子({highest['severity_score']:.0f}分)")
    if highest["trend_score"] >= 50:
        factors.append(f"趋势因子({highest['trend_score']:.0f}分)")

    if not factors:
        factors = ["多个风险因子共同作用"]

    trend_desc = {
        "升": "且呈上升趋势",
        "降": "且呈下降趋势",
        "稳": "趋势平稳"
    }.get(highest.get("prediction_trend", "稳"), "趋势平稳")

    summary = f"{highest['device_name']}综合风险最高({highest['total_score']:.0f}分)，"
    summary += f"主要由{'和'.join(factors)}驱动，{trend_desc}。"

    if len(sorted_devices) >= 2:
        lowest = sorted_devices[-1]
        summary += f"相比之下，{lowest['device_name']}风险最低({lowest['total_score']:.0f}分)。"

    return summary


def generate_risk_alerts(risk_results, detection_run_id=None):
    from config_manager import get_alert_config
    alert_config = get_alert_config()
    n = alert_config["continuous_rise_n"]
    m = alert_config["jump_m"]

    alerts = []

    for result in risk_results:
        device_name = result["device_name"]
        current_score = result["total_score"]
        history = get_risk_score_history(device_name, limit=n + 1)

        if len(history) >= n:
            scores = [h["total_score"] for h in history[-n:]]
            is_continuous_rise = all(scores[i] < scores[i + 1] for i in range(len(scores) - 1))
            if is_continuous_rise:
                prev_score = history[-2]["total_score"] if len(history) >= 2 else None
                change_amount = current_score - prev_score if prev_score else None
                alerts.append({
                    "device_name": device_name,
                    "alert_type": "continuous_rise",
                    "current_score": current_score,
                    "previous_score": prev_score,
                    "change_amount": change_amount,
                    "detection_run_id": detection_run_id,
                })

        if len(history) >= 2:
            prev_score = history[-2]["total_score"]
            change_amount = abs(current_score - prev_score)
            if change_amount >= m:
                alerts.append({
                    "device_name": device_name,
                    "alert_type": "jump",
                    "current_score": current_score,
                    "previous_score": prev_score,
                    "change_amount": current_score - prev_score,
                    "detection_run_id": detection_run_id,
                })

    if alerts:
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO risk_alerts (
                    device_name, alert_type, current_score,
                    previous_score, change_amount, detection_run_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        a["device_name"],
                        a["alert_type"],
                        a["current_score"],
                        a["previous_score"],
                        a["change_amount"],
                        a["detection_run_id"],
                    )
                    for a in alerts
                ],
            )

    return alerts


def get_active_risk_alerts(limit=10):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM risk_alerts
            WHERE is_confirmed = 0
            ORDER BY trigger_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_risk_alerts(limit=100):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM risk_alerts
            ORDER BY trigger_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def confirm_risk_alert(alert_id, confirmed_by="用户"):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE risk_alerts
            SET is_confirmed = 1, confirmed_by = ?, confirmed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (confirmed_by, alert_id),
        )


def get_last_score_change(device_name):
    history = get_risk_score_history(device_name, limit=2)
    if len(history) >= 2:
        return history[-1]["total_score"] - history[-2]["total_score"]
    return None


def has_active_alert(device_name):
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) as cnt FROM risk_alerts
            WHERE device_name = ? AND is_confirmed = 0
            """,
            (device_name,),
        ).fetchone()
        return row["cnt"] > 0


def calculate_simulated_score(factor_values, weights=None):
    if weights is None:
        weights = get_risk_weights()

    signal_score = factor_values.get("signal_strength", 0)
    freq_score = factor_values.get("report_frequency", 0)
    severity_score = factor_values.get("severity", 0)
    trend_score = factor_values.get("trend", 0)

    weighted_total = (
        signal_score * weights["signal_strength"] +
        freq_score * weights["report_frequency"] +
        severity_score * weights["severity"] +
        trend_score * weights["trend"]
    )
    weighted_total = max(0, min(100, weighted_total))

    bayesian = BayesianNetwork()
    bayesian_result = bayesian.infer({
        "signal_strength": signal_score,
        "report_frequency": freq_score,
        "severity": severity_score,
        "trend": trend_score,
    })
    bayesian_risk = bayesian_result["bayesian_score"]

    final_score = (weighted_total * 0.7) + (bayesian_risk * 0.3)
    final_score = max(0, min(100, final_score))

    risk_level, risk_color = get_risk_level(final_score)

    return {
        "total_score": final_score,
        "risk_level": risk_level,
        "risk_color": risk_color,
        "weighted_total": weighted_total,
        "bayesian_risk": bayesian_risk,
        "bayesian_distribution": bayesian_result["risk_distribution"],
        "weights": weights,
    }


def get_simulated_rank(simulated_score, risk_scores_df=None):
    if risk_scores_df is None:
        risk_scores_df = load_risk_scores()

    if risk_scores_df.empty:
        return None

    all_scores = risk_scores_df["total_score"].tolist()
    all_scores.append(simulated_score)
    all_scores.sort(reverse=True)

    rank = all_scores.index(simulated_score) + 1
    return rank


def save_simulator_scheme(scheme_name, factor_values, created_by="用户"):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO risk_simulator_schemes (
                scheme_name, signal_strength, report_frequency,
                severity, trend, created_by
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                scheme_name,
                factor_values.get("signal_strength", 0),
                factor_values.get("report_frequency", 0),
                factor_values.get("severity", 0),
                factor_values.get("trend", 0),
                created_by,
            ),
        )


def get_simulator_schemes():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM risk_simulator_schemes
            ORDER BY created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def delete_simulator_scheme(scheme_id):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM risk_simulator_schemes WHERE id = ?",
            (scheme_id,),
        )


def get_risk_scores_for_export():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT rs.*,
                   ra.is_confirmed as has_active_alert_raw
            FROM risk_scores rs
            LEFT JOIN risk_alerts ra ON rs.device_name = ra.device_name AND ra.is_confirmed = 0
            ORDER BY rs.total_score DESC
            """
        ).fetchall()

        results = []
        seen_devices = set()

        for row in rows:
            r = dict(row)
            device_name = r["device_name"]

            if device_name in seen_devices:
                continue
            seen_devices.add(device_name)

            risk_level = r.get("risk_level", "极低风险")
            level_info = get_risk_level_info(risk_level)

            last_change = get_last_score_change(device_name)

            history = get_risk_score_history(device_name, limit=1)
            bayesian_result = None
            if history:
                latest = history[0]
                bayesian = BayesianNetwork()
                bayesian_result = bayesian.infer({
                    "signal_strength": latest.get("signal_strength_score", 0),
                    "report_frequency": latest.get("report_frequency_score", 0),
                    "severity": latest.get("severity_score", 0),
                    "trend": latest.get("trend_score", 0),
                })

            if bayesian_result is None:
                bayesian_result = {
                    "risk_distribution": {"low": 0.0, "medium": 0.0, "high": 0.0}
                }

            has_active = has_active_alert(device_name)

            results.append({
                "device_name": device_name,
                "total_score": r.get("total_score", 0),
                "risk_level": risk_level,
                "risk_color_hex": level_info.get("color", "#7f7f7f"),
                "signal_strength_score": r.get("signal_strength_score", 0),
                "signal_strength_weighted": r.get("signal_strength_factor", 0),
                "report_frequency_score": r.get("report_frequency_score", 0),
                "report_frequency_weighted": r.get("report_frequency_factor", 0),
                "severity_score": r.get("severity_score", 0),
                "severity_weighted": r.get("severity_factor", 0),
                "trend_score": r.get("trend_score", 0),
                "trend_weighted": r.get("trend_factor", 0),
                "weight_signal_strength": r.get("weight_signal_strength", 0.40),
                "weight_report_frequency": r.get("weight_report_frequency", 0.25),
                "weight_severity": r.get("weight_severity", 0.20),
                "weight_trend": r.get("weight_trend", 0.15),
                "bayesian_risk": r.get("bayesian_risk", 0),
                "bayesian_prob_low": bayesian_result["risk_distribution"].get("low", 0),
                "bayesian_prob_medium": bayesian_result["risk_distribution"].get("medium", 0),
                "bayesian_prob_high": bayesian_result["risk_distribution"].get("high", 0),
                "last_score_change": last_change if last_change is not None else 0,
                "has_active_alert": has_active,
                "prediction_trend": r.get("prediction_trend", "稳"),
                "is_upgrade_alert": bool(r.get("is_upgrade_alert", 0)),
            })

        return results
