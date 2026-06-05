from db import get_db
import pandas as pd


STRENGTH_ORDER = {"无信号": 0, "弱信号": 1, "中等信号": 2, "强信号": 3}


def create_detection_run(total_reports, signals_df, config_id=None):
    if signals_df.empty:
        strong = medium = weak = 0
    else:
        strong = len(signals_df[signals_df["signal_strength"] == "强信号"])
        medium = len(signals_df[signals_df["signal_strength"] == "中等信号"])
        weak = len(signals_df[signals_df["signal_strength"] == "弱信号"])

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO detection_runs 
            (total_reports, total_signals, strong_signals, medium_signals, weak_signals, config_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (total_reports, len(signals_df), strong, medium, weak, config_id),
        )
        return cursor.lastrowid


def save_signal_history(detection_run_id, signals_df):
    if signals_df.empty:
        return

    history_records = []
    for _, row in signals_df.iterrows():
        history_records.append(
            (
                detection_run_id,
                row["device_name"],
                row["event_type"],
                int(row.get("report_count", 0)),
                row.get("prr_value"),
                row.get("ror_value"),
                row.get("ic_value"),
                row.get("ebgm_value"),
                int(row.get("signal_count", 0)),
                row.get("signal_strength", "无信号"),
            )
        )

    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO signal_history 
            (detection_run_id, device_name, event_type, report_count, prr_value, 
             ror_value, ic_value, ebgm_value, signal_count, signal_strength)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            history_records,
        )


def get_last_detection_run():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM detection_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_signal_history(detection_run_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM signal_history WHERE detection_run_id = ?",
            (detection_run_id,),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])


def detect_changes(current_run_id, current_signals_df, previous_run_id=None):
    if previous_run_id is None:
        last_run = get_last_detection_run()
        if last_run and last_run["id"] < current_run_id:
            previous_run_id = last_run["id"]
        else:
            return []

    previous_df = get_signal_history(previous_run_id)
    if previous_df.empty:
        previous_map = {}
    else:
        previous_map = {
            (r["device_name"], r["event_type"]): r["signal_strength"]
            for _, r in previous_df.iterrows()
        }

    current_map = {
        (r["device_name"], r["event_type"]): r["signal_strength"]
        for _, r in current_signals_df.iterrows()
    }

    all_pairs = set(previous_map.keys()) | set(current_map.keys())
    changes = []

    for pair in all_pairs:
        prev_strength = previous_map.get(pair, "无信号")
        curr_strength = current_map.get(pair, "无信号")

        if prev_strength != curr_strength:
            prev_order = STRENGTH_ORDER.get(prev_strength, 0)
            curr_order = STRENGTH_ORDER.get(curr_strength, 0)

            if prev_strength == "无信号" and curr_strength != "无信号":
                change_type = "新增"
            elif curr_strength == "无信号" and prev_strength != "无信号":
                change_type = "消失"
            elif curr_order > prev_order:
                change_type = "升级"
            else:
                change_type = "降级"

            changes.append(
                {
                    "detection_run_id": current_run_id,
                    "device_name": pair[0],
                    "event_type": pair[1],
                    "previous_strength": prev_strength,
                    "current_strength": curr_strength,
                    "change_type": change_type,
                }
            )

    if changes:
        with get_db() as conn:
            conn.executemany(
                """
                INSERT INTO signal_changes 
                (detection_run_id, device_name, event_type, previous_strength, 
                 current_strength, change_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c["detection_run_id"],
                        c["device_name"],
                        c["event_type"],
                        c["previous_strength"],
                        c["current_strength"],
                        c["change_type"],
                    )
                    for c in changes
                ],
            )

    return changes


def get_changes_for_run(detection_run_id):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sc.*, s.id as signal_id
            FROM signal_changes sc
            LEFT JOIN signals s ON sc.device_name = s.device_name AND sc.event_type = s.event_type
            WHERE sc.detection_run_id = ?
            ORDER BY 
                CASE sc.change_type
                    WHEN '升级' THEN 0
                    WHEN '降级' THEN 1
                    WHEN '新增' THEN 2
                    WHEN '消失' THEN 3
                    ELSE 4
                END,
                CASE sc.current_strength
                    WHEN '强信号' THEN 0
                    WHEN '中等信号' THEN 1
                    WHEN '弱信号' THEN 2
                    WHEN '无信号' THEN 3
                    ELSE 4
                END
            """,
            (detection_run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_changes():
    last_run = get_last_detection_run()
    if not last_run:
        return []
    return get_changes_for_run(last_run["id"])
