import numpy as np
import pandas as pd
from scipy import stats
from db import get_db


def compute_monthly_counts(df, device_name=None):
    if device_name:
        df = df[df["device_name"] == device_name]
    df = df.copy()
    df["report_date"] = pd.to_datetime(df["report_date"])
    df["year_month"] = df["report_date"].dt.to_period("M")
    monthly = df.groupby("year_month").size().reset_index(name="count")
    monthly["year_month"] = monthly["year_month"].astype(str)
    return monthly


def compute_cusum(monthly_counts, baseline_months=6):
    if len(monthly_counts) < baseline_months + 1:
        return monthly_counts, []

    counts = monthly_counts["count"].values.astype(float)
    mu0 = np.mean(counts[:baseline_months])
    sigma = np.std(counts[:baseline_months], ddof=1) if len(counts[:baseline_months]) > 1 else 1.0
    if sigma == 0:
        sigma = 1.0
    delta = sigma
    h = 5 * sigma

    cusum_values = np.zeros(len(counts))
    alerts = []
    S = 0.0

    for t in range(len(counts)):
        if t < baseline_months:
            cusum_values[t] = 0
        else:
            S = max(0, S + (counts[t] - mu0 - delta / 2))
            cusum_values[t] = S
            if S > h:
                alerts.append({
                    "month": monthly_counts["year_month"].iloc[t],
                    "cusum_value": S,
                    "baseline_mean": mu0,
                    "baseline_std": sigma,
                    "threshold": h,
                    "observed": counts[t],
                })

    monthly_counts = monthly_counts.copy()
    monthly_counts["cusum"] = cusum_values
    monthly_counts["threshold"] = h
    return monthly_counts, alerts


def seasonal_decompose_simple(series_values, period=12):
    n = len(series_values)
    if n < 2 * period:
        return series_values, np.zeros(n)
    values = np.array(series_values, dtype=float)
    seasonal = np.zeros(period)
    for i in range(period):
        indices = np.arange(i, n, period)
        seasonal[i] = np.mean(values[indices]) - np.mean(values)
    full_seasonal = np.tile(seasonal, (n // period) + 1)[:n]
    deseasonalized = values - full_seasonal
    return deseasonalized, full_seasonal


def detect_trend(monthly_counts, baseline_months=6):
    if len(monthly_counts) < baseline_months + 3:
        return None, None, None, None

    counts = monthly_counts["count"].values.astype(float)
    deseasonalized, _ = seasonal_decompose_simple(counts[baseline_months:])

    x = np.arange(len(deseasonalized))
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, deseasonalized)

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_value ** 2,
        "p_value": p_value,
        "is_increasing": p_value < 0.05 and slope > 0,
    }, deseasonalized, x, (slope * x + intercept)


def save_cusum_alerts(alerts, device_name):
    if not alerts:
        return
    with get_db() as conn:
        for alert in alerts:
            conn.execute(
                "INSERT INTO cusum_alerts (device_name, alert_month, baseline_mean, baseline_std, cusum_value, threshold, is_alert) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (
                    device_name,
                    alert["month"],
                    alert["baseline_mean"],
                    alert["baseline_std"],
                    alert["cusum_value"],
                    alert["threshold"],
                ),
            )


def load_cusum_alerts(device_name=None):
    with get_db() as conn:
        if device_name:
            rows = conn.execute(
                "SELECT * FROM cusum_alerts WHERE device_name = ? ORDER BY alert_month",
                (device_name,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM cusum_alerts ORDER BY alert_month").fetchall()
        return [dict(r) for r in rows]
