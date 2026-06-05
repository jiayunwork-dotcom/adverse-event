import numpy as np
import pandas as pd
from scipy import stats
from datetime import datetime, timedelta
import json
from db import get_db
from algorithms import load_signals
from time_analysis import compute_monthly_counts, compute_cusum, detect_trend
from data_import import load_reports


WEIGHTS = {
    "signal_strength": 0.40,
    "report_frequency": 0.25,
    "severity": 0.20,
    "trend": 0.15,
}

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


def calculate_signal_strength_factor(device_name, signals_df=None):
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

    weighted_score = max_strength_score * WEIGHTS["signal_strength"]
    return max_strength_score, weighted_score


def calculate_report_frequency_factor(device_name, reports_df=None):
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
    weighted_score = raw_score * WEIGHTS["report_frequency"]

    return raw_score, weighted_score


def calculate_severity_factor(device_name, reports_df=None):
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

    weighted_score = raw_score * WEIGHTS["severity"]

    return raw_score, weighted_score


def calculate_trend_factor(device_name, reports_df=None):
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

    weighted_score = raw_score * WEIGHTS["trend"]

    return raw_score, weighted_score


def calculate_risk_score(device_name, signals_df=None, reports_df=None, detection_run_id=None):
    if reports_df is None:
        reports_df = load_reports()
    if signals_df is None:
        signals_df = load_signals()

    signal_score, signal_weighted = calculate_signal_strength_factor(device_name, signals_df)
    freq_score, freq_weighted = calculate_report_frequency_factor(device_name, reports_df)
    severity_score, severity_weighted = calculate_severity_factor(device_name, reports_df)
    trend_score, trend_weighted = calculate_trend_factor(device_name, reports_df)

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
                        detection_run_id = ?, updated_at = CURRENT_TIMESTAMP
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
                        detection_run_id, result["device_name"],
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
                        prediction_values, is_upgrade_alert, detection_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["device_name"], result["total_score"], result["risk_level"],
                        result["signal_strength_weighted"], result["signal_strength_score"],
                        result["report_frequency_weighted"], result["report_frequency_score"],
                        result["severity_weighted"], result["severity_score"],
                        result["trend_weighted"], result["trend_score"],
                        result["bayesian_risk"], result["prediction_trend"],
                        pred_json, 1 if result["is_upgrade_alert"] else 0, detection_run_id,
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

    all_devices = reports_df["device_name"].unique().tolist()
    results = []

    for device in all_devices:
        result = calculate_risk_score(device, signals_df, reports_df, detection_run_id)
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
