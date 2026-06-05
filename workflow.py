import pandas as pd
from datetime import datetime
from db import get_db


def get_signal_workflow_status(signal_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM signal_workflow WHERE signal_id = ? ORDER BY created_at DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        return dict(row) if row else None


def get_all_signal_workflow():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sw.*, s.device_name, s.event_type, s.signal_strength, s.report_count
            FROM signal_workflow sw
            JOIN signals s ON sw.signal_id = s.id
            WHERE s.signal_strength != '无信号'
              AND sw.id IN (
                SELECT MAX(id) FROM signal_workflow GROUP BY signal_id
            )
            ORDER BY
                CASE s.signal_strength
                    WHEN '强信号' THEN 0
                    WHEN '中等信号' THEN 1
                    WHEN '弱信号' THEN 2
                    ELSE 3
                END,
                s.report_count DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def init_workflow_for_signals():
    with get_db() as conn:
        signals = conn.execute(
            "SELECT id FROM signals WHERE signal_strength != '无信号'"
        ).fetchall()
        existing = conn.execute("SELECT DISTINCT signal_id FROM signal_workflow").fetchall()
        existing_ids = {r["signal_id"] for r in existing}
        for s in signals:
            if s["id"] not in existing_ids:
                conn.execute(
                    "INSERT INTO signal_workflow (signal_id, status, operator, notes) VALUES (?, '待评估', '系统', '自动创建')",
                    (s["id"],),
                )


def update_signal_status(signal_id, new_status, operator="分析员", notes=""):
    valid_statuses = {"待评估", "评估中", "确认信号", "排除"}
    if new_status not in valid_statuses:
        raise ValueError(f"无效状态: {new_status}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO signal_workflow (signal_id, status, operator, notes) VALUES (?, ?, ?, ?)",
            (signal_id, new_status, operator, notes),
        )


def set_action_measure(signal_id, action_measure, operator="分析员", notes=""):
    with get_db() as conn:
        latest = conn.execute(
            "SELECT status FROM signal_workflow WHERE signal_id = ? ORDER BY created_at DESC LIMIT 1",
            (signal_id,),
        ).fetchone()
        if latest and latest["status"] == "确认信号":
            conn.execute(
                "INSERT INTO signal_workflow (signal_id, status, action_measure, operator, notes) VALUES (?, '确认信号', ?, ?, ?)",
                (signal_id, action_measure, operator, notes),
            )
        else:
            raise ValueError("只有确认信号才能设置行动措施")


def get_kanban_data():
    with get_db() as conn:
        signals = conn.execute(
            "SELECT * FROM signals WHERE signal_strength != '无信号'"
        ).fetchall()
        signal_map = {s["id"]: dict(s) for s in signals}

        workflows = conn.execute(
            """
            SELECT sw.* FROM signal_workflow sw
            WHERE sw.id IN (
                SELECT MAX(id) FROM signal_workflow GROUP BY signal_id
            )
            """
        ).fetchall()

        kanban = {"待评估": [], "评估中": [], "确认信号": [], "排除": []}
        for w in workflows:
            sid = w["signal_id"]
            status = w["status"]
            if sid in signal_map:
                entry = {**signal_map[sid], "workflow_id": w["id"], "operator": w["operator"], "notes": w["notes"], "action_measure": w["action_measure"]}
                kanban[status].append(entry)

        for key in kanban:
            kanban[key].sort(
                key=lambda x: (
                    {"强信号": 0, "中等信号": 1, "弱信号": 2, "无信号": 3}.get(x.get("signal_strength", "无信号"), 3),
                    -x.get("report_count", 0),
                )
            )

        return kanban


def get_signal_with_workflow(signal_id):
    with get_db() as conn:
        signal = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if not signal:
            return None
        workflows = conn.execute(
            "SELECT * FROM signal_workflow WHERE signal_id = ? ORDER BY created_at",
            (signal_id,),
        ).fetchall()
        return {
            "signal": dict(signal),
            "workflow_history": [dict(w) for w in workflows],
        }
