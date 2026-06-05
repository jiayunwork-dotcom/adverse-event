import json
import pandas as pd
from datetime import datetime
from db import get_db
from config_manager import get_active_config

REVIEWER_ROLES = ["初审员", "高级审阅员", "主管"]
ROLE_WEIGHTS = {"初审员": 1, "高级审阅员": 2, "主管": 999}
REPORT_STATUSES = ["草稿", "审阅中", "已批准", "已退回"]
ANNOTATION_TYPES = ["疑问", "建议", "反对", "确认"]
ANNOTATION_STATUSES = ["开放", "已解决"]
REVIEW_ACTIONS = ["提交审阅", "批准", "退回", "请求修改"]


def init_review_tables():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS reviewers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL CHECK(role IN ('初审员','高级审阅员','主管')),
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS report_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number INTEGER NOT NULL,
            generation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            generation_params TEXT,
            file_path TEXT,
            status TEXT NOT NULL DEFAULT '草稿' CHECK(status IN ('草稿','审阅中','已批准','已退回')),
            submitter TEXT,
            submitted_at TIMESTAMP,
            reject_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_report_status ON report_versions(status);
        CREATE INDEX IF NOT EXISTS idx_report_version ON report_versions(version_number);

        CREATE TABLE IF NOT EXISTS report_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_version_id INTEGER NOT NULL,
            signal_id INTEGER,
            device_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            signal_strength TEXT,
            report_count INTEGER,
            prr_value REAL,
            ror_value REAL,
            ic_value REAL,
            ebgm_value REAL,
            FOREIGN KEY (report_version_id) REFERENCES report_versions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_rs_report ON report_signals(report_version_id);
        CREATE INDEX IF NOT EXISTS idx_rs_signal ON report_signals(signal_id);

        CREATE TABLE IF NOT EXISTS review_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_version_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            decision TEXT CHECK(decision IN ('批准','退回','请求修改')),
            comments TEXT,
            FOREIGN KEY (report_version_id) REFERENCES report_versions(id),
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ra_report ON review_assignments(report_version_id);
        CREATE INDEX IF NOT EXISTS idx_ra_reviewer ON review_assignments(reviewer_id);

        CREATE TABLE IF NOT EXISTS review_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_version_id INTEGER NOT NULL,
            reviewer_id INTEGER,
            action TEXT NOT NULL CHECK(action IN ('提交审阅','批准','退回','请求修改')),
            comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_version_id) REFERENCES report_versions(id),
            FOREIGN KEY (reviewer_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_rh_report ON review_history(report_version_id);
        CREATE INDEX IF NOT EXISTS idx_rh_action ON review_history(action);

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_version_id INTEGER NOT NULL,
            signal_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            annotation_type TEXT NOT NULL CHECK(annotation_type IN ('疑问','建议','反对','确认')),
            author_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT '开放' CHECK(status IN ('开放','已解决')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_version_id) REFERENCES report_versions(id),
            FOREIGN KEY (author_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ann_report ON annotations(report_version_id);
        CREATE INDEX IF NOT EXISTS idx_ann_signal ON annotations(signal_id);
        CREATE INDEX IF NOT EXISTS idx_ann_status ON annotations(status);

        CREATE TABLE IF NOT EXISTS annotation_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            annotation_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            author_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (annotation_id) REFERENCES annotations(id),
            FOREIGN KEY (author_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ar_annotation ON annotation_replies(annotation_id);
        """)


def create_default_reviewers():
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) as cnt FROM reviewers").fetchone()
        if count["cnt"] == 0:
            default_reviewers = [
                ("张晓明", "初审员", "zhangxm@example.com"),
                ("李雪梅", "初审员", "lixm@example.com"),
                ("王建国", "高级审阅员", "wangjg@example.com"),
                ("陈丽华", "高级审阅员", "chenlh@example.com"),
                ("刘伟强", "主管", "liuwq@example.com"),
            ]
            for name, role, email in default_reviewers:
                conn.execute(
                    "INSERT INTO reviewers (name, role, email) VALUES (?, ?, ?)",
                    (name, role, email),
                )


def add_reviewer(name, role, email=None):
    if role not in REVIEWER_ROLES:
        raise ValueError(f"无效角色: {role}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reviewers (name, role, email) VALUES (?, ?, ?)",
            (name, role, email),
        )


def update_reviewer(reviewer_id, name=None, role=None, email=None):
    if role and role not in REVIEWER_ROLES:
        raise ValueError(f"无效角色: {role}")
    fields = []
    values = []
    if name:
        fields.append("name = ?")
        values.append(name)
    if role:
        fields.append("role = ?")
        values.append(role)
    if email is not None:
        fields.append("email = ?")
        values.append(email)
    values.append(reviewer_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE reviewers SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )


def delete_reviewer(reviewer_id):
    with get_db() as conn:
        conn.execute("DELETE FROM reviewers WHERE id = ?", (reviewer_id,))


def get_all_reviewers():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM reviewers ORDER BY role, name").fetchall()
        return [dict(r) for r in rows]


def get_reviewer(reviewer_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reviewers WHERE id = ?", (reviewer_id,)).fetchone()
        return dict(row) if row else None


def get_reviewer_by_name(name):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reviewers WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def create_report_version(signals_df, file_path, generation_params=None, submitter=None):
    if generation_params is None:
        config = get_active_config()
        generation_params = {
            "detection_config": config,
            "date_range": None,
            "filters": {},
        }
    with get_db() as conn:
        max_ver = conn.execute("SELECT MAX(version_number) as mv FROM report_versions").fetchone()
        version_number = (max_ver["mv"] or 0) + 1

        cursor = conn.execute(
            """
            INSERT INTO report_versions 
            (version_number, generation_params, file_path, status, submitter)
            VALUES (?, ?, ?, '草稿', ?)
            """,
            (version_number, json.dumps(generation_params, ensure_ascii=False), file_path, submitter),
        )
        report_version_id = cursor.lastrowid

        if not signals_df.empty:
            for _, row in signals_df.iterrows():
                conn.execute(
                    """
                    INSERT INTO report_signals
                    (report_version_id, signal_id, device_name, event_type, signal_strength,
                     report_count, prr_value, ror_value, ic_value, ebgm_value)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_version_id,
                        int(row.get("id")) if pd.notna(row.get("id")) else None,
                        str(row["device_name"]),
                        str(row["event_type"]),
                        str(row.get("signal_strength", "")),
                        int(row.get("report_count", 0)) if pd.notna(row.get("report_count")) else None,
                        float(row["prr_value"]) if pd.notna(row.get("prr_value")) else None,
                        float(row["ror_value"]) if pd.notna(row.get("ror_value")) else None,
                        float(row["ic_value"]) if pd.notna(row.get("ic_value")) else None,
                        float(row["ebgm_value"]) if pd.notna(row.get("ebgm_value")) else None,
                    ),
                )

        return report_version_id, version_number


def get_all_report_versions(status=None):
    with get_db() as conn:
        query = "SELECT * FROM report_versions"
        params = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY version_number DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_report_version(report_version_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not row:
            return None
        report = dict(row)
        if report.get("generation_params"):
            report["generation_params"] = json.loads(report["generation_params"])

        signals = conn.execute(
            "SELECT * FROM report_signals WHERE report_version_id = ? ORDER BY report_count DESC",
            (report_version_id,),
        ).fetchall()
        report["signals"] = [dict(s) for s in signals]
        return report


def get_report_signals(report_version_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM report_signals WHERE report_version_id = ? ORDER BY report_count DESC",
            (report_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def compare_report_versions(version1_id, version2_id):
    signals1 = {f"{s['device_name']}|{s['event_type']}": s for s in get_report_signals(version1_id)}
    signals2 = {f"{s['device_name']}|{s['event_type']}": s for s in get_report_signals(version2_id)}

    all_keys = set(signals1.keys()) | set(signals2.keys())
    changes = []

    for key in all_keys:
        s1 = signals1.get(key)
        s2 = signals2.get(key)
        device_name, event_type = key.split("|", 1)

        if s1 and not s2:
            change_type = "消失"
            old_strength = s1["signal_strength"]
            new_strength = None
        elif not s1 and s2:
            change_type = "新增"
            old_strength = None
            new_strength = s2["signal_strength"]
        else:
            if s1["signal_strength"] != s2["signal_strength"]:
                strength_order = {"无信号": 0, "弱信号": 1, "中等信号": 2, "强信号": 3}
                if strength_order.get(s2["signal_strength"], 0) > strength_order.get(s1["signal_strength"], 0):
                    change_type = "升级"
                else:
                    change_type = "降级"
                old_strength = s1["signal_strength"]
                new_strength = s2["signal_strength"]
            else:
                continue

        changes.append({
            "device_name": device_name,
            "event_type": event_type,
            "change_type": change_type,
            "old_strength": old_strength,
            "new_strength": new_strength,
            "old_signal": s1,
            "new_signal": s2,
        })

    return changes


def submit_for_review(report_version_id, reviewer_ids, submitter_name=None):
    if not reviewer_ids:
        raise ValueError("至少需要指定一位审阅人")

    with get_db() as conn:
        report = conn.execute(
            "SELECT * FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not report:
            raise ValueError("报告不存在")
        if report["status"] != "草稿":
            raise ValueError("只有草稿状态的报告才能提交审阅")

        conn.execute(
            """
            UPDATE report_versions 
            SET status = '审阅中', submitter = ?, submitted_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (submitter_name, report_version_id),
        )

        for reviewer_id in reviewer_ids:
            conn.execute(
                """
                INSERT INTO review_assignments (report_version_id, reviewer_id)
                VALUES (?, ?)
                """,
                (report_version_id, reviewer_id),
            )

        conn.execute(
            """
            INSERT INTO review_history (report_version_id, action, comments)
            VALUES (?, '提交审阅', ?)
            """,
            (report_version_id, f"指定审阅人: {len(reviewer_ids)}人"),
        )


def _calculate_approval_weight(conn, report_version_id):
    assignments = conn.execute(
        """
        SELECT ra.*, r.role 
        FROM review_assignments ra
        JOIN reviewers r ON ra.reviewer_id = r.id
        WHERE ra.report_version_id = ? AND ra.decision = '批准'
        """,
        (report_version_id,),
    ).fetchall()

    total_weight = 0
    has_supervisor = False
    for a in assignments:
        weight = ROLE_WEIGHTS.get(a["role"], 1)
        if weight >= 999:
            has_supervisor = True
        total_weight += weight

    return total_weight, has_supervisor


def _get_required_weight(conn, report_version_id):
    total_assigned = conn.execute(
        "SELECT COUNT(*) as cnt FROM review_assignments WHERE report_version_id = ?",
        (report_version_id,),
    ).fetchone()["cnt"]
    return max(total_assigned, 2)


def make_review_decision(report_version_id, reviewer_id, decision, comments=None):
    if decision not in ["批准", "退回", "请求修改"]:
        raise ValueError(f"无效决策: {decision}")

    with get_db() as conn:
        report = conn.execute(
            "SELECT * FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not report:
            raise ValueError("报告不存在")
        if report["status"] != "审阅中":
            raise ValueError("只有审阅中的报告才能进行审批操作")

        reviewer = conn.execute(
            "SELECT * FROM reviewers WHERE id = ?",
            (reviewer_id,),
        ).fetchone()
        if not reviewer:
            raise ValueError("审阅人不存在")

        is_supervisor = reviewer["role"] == "主管"

        assignment = conn.execute(
            """
            SELECT * FROM review_assignments 
            WHERE report_version_id = ? AND reviewer_id = ?
            """,
            (report_version_id, reviewer_id),
        ).fetchone()

        if not is_supervisor:
            if not assignment:
                raise ValueError("该审阅人未被分配此报告的审阅任务")
            if assignment["decision"]:
                raise ValueError("该审阅人已完成审阅，不可重复操作")

        if is_supervisor and not assignment:
            cursor = conn.execute(
                """
                INSERT INTO review_assignments (report_version_id, reviewer_id, completed_at, decision, comments)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
                """,
                (report_version_id, reviewer_id, decision, comments),
            )
            assignment_id = cursor.lastrowid
        else:
            conn.execute(
                """
                UPDATE review_assignments 
                SET decision = ?, comments = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (decision, comments, assignment["id"]),
            )
            assignment_id = assignment["id"]

        conn.execute(
            """
            INSERT INTO review_history (report_version_id, reviewer_id, action, comments)
            VALUES (?, ?, ?, ?)
            """,
            (report_version_id, reviewer_id, decision, comments),
        )

        if decision == "退回":
            conn.execute(
                "UPDATE report_versions SET status = '已退回', reject_reason = ? WHERE id = ?",
                (comments, report_version_id),
            )
        else:
            total_weight, has_supervisor = _calculate_approval_weight(conn, report_version_id)
            required = _get_required_weight(conn, report_version_id)

            if has_supervisor or total_weight >= required:
                conn.execute(
                    "UPDATE report_versions SET status = '已批准' WHERE id = ?",
                    (report_version_id,),
                )


def get_report_assignments(report_version_id):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ra.*, r.name, r.role, r.email
            FROM review_assignments ra
            JOIN reviewers r ON ra.reviewer_id = r.id
            WHERE ra.report_version_id = ?
            ORDER BY ra.assigned_at
            """,
            (report_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_reviewer_assignments(reviewer_id=None, status=None):
    with get_db() as conn:
        query = """
            SELECT ra.*, rv.version_number, rv.status as report_status, rv.file_path,
                   r.name as reviewer_name, r.role
            FROM review_assignments ra
            JOIN report_versions rv ON ra.report_version_id = rv.id
            JOIN reviewers r ON ra.reviewer_id = r.id
        """
        conditions = []
        params = []
        if reviewer_id:
            conditions.append("ra.reviewer_id = ?")
            params.append(reviewer_id)
        if status:
            conditions.append("ra.decision IS ?")
            params.append(None if status == "pending" else status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ra.assigned_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_review_history(report_version_id):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT rh.*, r.name as reviewer_name
            FROM review_history rh
            LEFT JOIN reviewers r ON rh.reviewer_id = r.id
            WHERE rh.report_version_id = ?
            ORDER BY rh.created_at
            """,
            (report_version_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_annotation(report_version_id, signal_id, content, annotation_type, author_id):
    if annotation_type not in ANNOTATION_TYPES:
        raise ValueError(f"无效批注类型: {annotation_type}")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO annotations
            (report_version_id, signal_id, content, annotation_type, author_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_version_id, signal_id, content, annotation_type, author_id),
        )
        return cursor.lastrowid


def add_annotation_reply(annotation_id, content, author_id):
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO annotation_replies
            (annotation_id, content, author_id)
            VALUES (?, ?, ?)
            """,
            (annotation_id, content, author_id),
        )
        return cursor.lastrowid


def set_annotation_status(annotation_id, status):
    if status not in ANNOTATION_STATUSES:
        raise ValueError(f"无效状态: {status}")
    with get_db() as conn:
        conn.execute(
            "UPDATE annotations SET status = ? WHERE id = ?",
            (status, annotation_id),
        )


def get_annotations(report_version_id, signal_id=None, status=None):
    with get_db() as conn:
        query = """
            SELECT a.*, r.name as author_name, r.role as author_role
            FROM annotations a
            JOIN reviewers r ON a.author_id = r.id
            WHERE a.report_version_id = ?
        """
        params = [report_version_id]
        if signal_id is not None:
            query += " AND a.signal_id = ?"
            params.append(signal_id)
        if status:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        annotations = [dict(r) for r in rows]

        for ann in annotations:
            replies = conn.execute(
                """
                SELECT ar.*, r.name as author_name, r.role as author_role
                FROM annotation_replies ar
                JOIN reviewers r ON ar.author_id = r.id
                WHERE ar.annotation_id = ?
                ORDER BY ar.created_at
                """,
                (ann["id"],),
            ).fetchall()
            ann["replies"] = [dict(r) for r in replies]

        return annotations


def get_annotation_count_by_signal(report_version_id):
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT signal_id, COUNT(*) as cnt
            FROM annotations
            WHERE report_version_id = ?
            GROUP BY signal_id
            """,
            (report_version_id,),
        ).fetchall()
        return {r["signal_id"]: r["cnt"] for r in rows}


def get_review_statistics():
    with get_db() as conn:
        stats = {}

        approved_reports = conn.execute(
            """
            SELECT julianday(rv.submitted_at) as submit_day, julianday(rh.created_at) as approve_day
            FROM review_history rh
            JOIN report_versions rv ON rh.report_version_id = rv.id
            WHERE rh.action = '批准'
            AND rv.status = '已批准'
            AND rv.submitted_at IS NOT NULL
            """
        ).fetchall()

        durations = []
        for r in approved_reports:
            if r["submit_day"] and r["approve_day"]:
                durations.append(r["approve_day"] - r["submit_day"])
        stats["avg_review_days"] = round(sum(durations) / len(durations), 2) if durations else 0

        reviewer_counts = conn.execute(
            """
            SELECT r.id, r.name, COUNT(*) as review_count
            FROM review_assignments ra
            JOIN reviewers r ON ra.reviewer_id = r.id
            WHERE ra.decision IS NOT NULL
            GROUP BY r.id, r.name
            ORDER BY review_count DESC
            """
        ).fetchall()
        stats["reviewer_ranking"] = [dict(r) for r in reviewer_counts]

        submit_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_history WHERE action = '提交审阅'"
        ).fetchone()["cnt"]
        reject_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM review_history WHERE action = '退回'"
        ).fetchone()["cnt"]
        stats["reject_rate"] = round(reject_count / submit_count * 100, 2) if submit_count > 0 else 0

        top_signals = conn.execute(
            """
            SELECT a.signal_id, rs.device_name, rs.event_type, COUNT(*) as annotation_count
            FROM annotations a
            JOIN report_signals rs ON a.signal_id = rs.id AND a.report_version_id = rs.report_version_id
            GROUP BY a.signal_id, rs.device_name, rs.event_type
            ORDER BY annotation_count DESC
            LIMIT 5
            """
        ).fetchall()
        stats["top_annotated_signals"] = [dict(r) for r in top_signals]

        status_counts = conn.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM report_versions
            GROUP BY status
            """
        ).fetchall()
        stats["status_distribution"] = {r["status"]: r["cnt"] for r in status_counts}

        return stats


def get_kanban_data():
    with get_db() as conn:
        reports = conn.execute(
            "SELECT * FROM report_versions ORDER BY version_number DESC"
        ).fetchall()

        kanban = {"草稿": [], "审阅中": [], "已批准": [], "已退回": []}

        for r in reports:
            report_dict = dict(r)

            signal_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM report_signals WHERE report_version_id = ?",
                (r["id"],),
            ).fetchone()["cnt"]
            report_dict["signal_count"] = signal_count

            annot_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM annotations WHERE report_version_id = ?",
                (r["id"],),
            ).fetchone()["cnt"]
            report_dict["annotation_count"] = annot_count

            assignments = conn.execute(
                """
                SELECT r.name, r.role, ra.decision
                FROM review_assignments ra
                JOIN reviewers r ON ra.reviewer_id = r.id
                WHERE ra.report_version_id = ?
                """,
                (r["id"],),
            ).fetchall()
            report_dict["reviewers"] = [dict(a) for a in assignments]

            if report_dict["status"] in kanban:
                kanban[report_dict["status"]].append(report_dict)

        return kanban
