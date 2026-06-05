import numpy as np
import pandas as pd
from db import get_db


def find_similar_devices(device_name, df=None):
    if df is None:
        from data_import import load_reports
        df = load_reports()

    target = df[df["device_name"] == device_name]
    if target.empty:
        return pd.DataFrame()

    target_code = target["device_class_code"].dropna().unique()
    if len(target_code) == 0:
        return pd.DataFrame()

    prefix = target_code[0][:4]
    similar = df[df["device_class_code"].str[:4] == prefix]
    devices = similar["device_name"].unique().tolist()
    if device_name in devices:
        devices.remove(device_name)

    if not devices:
        return pd.DataFrame()

    return df[df["device_name"].isin(devices)]


def compare_similar_devices(device_name, df=None):
    if df is None:
        from data_import import load_reports
        df = load_reports()

    similar_df = find_similar_devices(device_name, df)
    if similar_df.empty:
        return pd.DataFrame()

    target_df = df[df["device_name"] == device_name]
    all_devices = [device_name] + similar_df["device_name"].unique().tolist()

    with get_db() as conn:
        signals_rows = conn.execute("SELECT device_name, COUNT(*) as sig_count FROM signals WHERE signal_strength != '无信号' GROUP BY device_name").fetchall()
        signal_counts = {r["device_name"]: r["sig_count"] for r in signals_rows}

    date_min = pd.to_datetime(df["report_date"]).min()
    date_max = pd.to_datetime(df["report_date"]).max()
    years_span = max((date_max - date_min).days / 365.25, 0.1)

    results = []
    for dev in all_devices:
        dev_df = df[df["device_name"] == dev]
        total_reports = len(dev_df)
        report_rate = total_reports / years_span
        sig_count = signal_counts.get(dev, 0)

        results.append({
            "device_name": dev,
            "total_reports": total_reports,
            "report_rate_per_year": round(report_rate, 2),
            "signal_count": sig_count,
            "is_target": dev == device_name,
        })

    result_df = pd.DataFrame(results)
    if len(result_df) > 1:
        mean_rate = result_df["report_rate_per_year"].mean()
        std_rate = result_df["report_rate_per_year"].std()
        if std_rate > 0:
            result_df["z_score"] = (result_df["report_rate_per_year"] - mean_rate) / std_rate
            result_df["is_outlier"] = result_df["z_score"] > 2
        else:
            result_df["z_score"] = 0
            result_df["is_outlier"] = False

    return result_df
