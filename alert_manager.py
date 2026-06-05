from db import get_db
import pandas as pd
from datetime import datetime, timedelta


def generate_alerts(signals_df, detection_run_id=None):
    if signals_df.empty:
        return []

    alerts = []
    strong_signals = signals_df[signals_df["signal_strength"].isin(["强信号", "中等信号"])]

    for _, row in strong_signals.iterrows():
        alert = {
            "device_name": row["device_name"],
            "event_type": row["event_type"],
            "signal_strength": row["signal_strength"],
            "prr_value": row["prr_value"],
            "report_count": row["report_count"],
            "detection_run_id": detection_run_id,
        }
        alerts.append(alert)

    if alerts:
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO signal_alerts 
                (device_name, event_type, signal_strength, prr_value, report_count, detection_run_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        a["device_name"],
                        a["event_type"],
                        a["signal_strength"],
                        a["prr_value"],
                        a["report_count"],
                        a["detection_run_id"],
                    )
                    for a in alerts
                ],
            )

    return alerts


def get_recent_alerts(days=7):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sa.*, s.id as signal_id
            FROM signal_alerts sa
            LEFT JOIN signals s ON sa.device_name = s.device_name AND sa.event_type = s.event_type
            WHERE sa.created_at >= datetime('now', '-{} days')
            ORDER BY sa.created_at DESC
            """.format(days)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_alerts(limit=100):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sa.*, s.id as signal_id
            FROM signal_alerts sa
            LEFT JOIN signals s ON sa.device_name = s.device_name AND sa.event_type = s.event_type
            ORDER BY sa.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
