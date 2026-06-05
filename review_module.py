import json
import pandas as pd
from datetime import datetime, timedelta
from db import get_db
from config_manager import get_active_config

REVIEWER_ROLES = ["初审员", "高级审阅员", "主管"]
ROLE_WEIGHTS = {"初审员": 1, "高级审阅员": 2, "主管": 999}
REPORT_STATUSES = ["草稿", "审阅中", "已批准", "已退回", "已超时"]
ANNOTATION_TYPES = ["疑问", "建议", "反对", "确认"]
ANNOTATION_PRIORITIES = ["紧急", "普通", "低"]
ANNOTATION_STATUSES = ["开放", "已解决"]
REVIEW_ACTIONS = ["提交审阅", "批准", "退回", "请求修改", "延期", "强制关闭"]


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
            status TEXT NOT NULL DEFAULT '草稿' CHECK(status IN ('草稿','审阅中','已批准','已退回','已超时')),
            submitter TEXT,
            submitted_at TIMESTAMP,
            deadline TIMESTAMP,
            reject_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_report_status ON report_versions(status);
        CREATE INDEX IF NOT EXISTS idx_report_version ON report_versions(version_number);
        CREATE INDEX IF NOT EXISTS idx_report_deadline ON report_versions(deadline);

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
            action TEXT NOT NULL CHECK(action IN ('提交审阅','批准','退回','请求修改','延期','强制关闭')),
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
            priority TEXT NOT NULL DEFAULT '普通' CHECK(priority IN ('紧急','普通','低')),
            author_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT '开放' CHECK(status IN ('开放','已解决')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_version_id) REFERENCES report_versions(id),
            FOREIGN KEY (author_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_ann_report ON annotations(report_version_id);
        CREATE INDEX IF NOT EXISTS idx_ann_signal ON annotations(signal_id);
        CREATE INDEX IF NOT EXISTS idx_ann_status ON annotations(status);
        CREATE INDEX IF NOT EXISTS idx_ann_priority ON annotations(priority);

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

        CREATE TABLE IF NOT EXISTS annotation_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            annotation_type TEXT NOT NULL CHECK(annotation_type IN ('疑问','建议','反对','确认')),
            priority TEXT NOT NULL DEFAULT '普通' CHECK(priority IN ('紧急','普通','低')),
            is_public INTEGER NOT NULL DEFAULT 0,
            creator_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (creator_id) REFERENCES reviewers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_at_creator ON annotation_templates(creator_id);
        CREATE INDEX IF NOT EXISTS idx_at_public ON annotation_templates(is_public);
        """)
        
        try:
            conn.execute("ALTER TABLE report_versions ADD COLUMN deadline TIMESTAMP")
        except:
            pass
        try:
            conn.execute("ALTER TABLE annotations ADD COLUMN priority TEXT NOT NULL DEFAULT '普通' CHECK(priority IN ('紧急','普通','低'))")
        except:
            pass


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


def submit_for_review(report_version_id, reviewer_ids, deadline, submitter_name=None):
    if not reviewer_ids:
        raise ValueError("至少需要指定一位审阅人")
    if not deadline:
        raise ValueError("必须设置审阅截止时间")

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
            SET status = '审阅中', submitter = ?, submitted_at = CURRENT_TIMESTAMP, deadline = ?
            WHERE id = ?
            """,
            (submitter_name, deadline, report_version_id),
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
            (report_version_id, f"指定审阅人: {len(reviewer_ids)}人, 截止时间: {deadline}"),
        )


def check_and_update_timeout():
    with get_db() as conn:
        now = datetime.now()
        rows = conn.execute(
            """
            SELECT * FROM report_versions 
            WHERE status = '审阅中' AND deadline IS NOT NULL AND deadline < ?
            """,
            (now.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()
        
        timeout_count = 0
        for r in rows:
            conn.execute(
                "UPDATE report_versions SET status = '已超时' WHERE id = ?",
                (r["id"],),
            )
            conn.execute(
                """
                INSERT INTO review_history (report_version_id, action, comments)
                VALUES (?, '提交审阅', ?)
                """,
                (r["id"], "系统自动标记为已超时"),
            )
            timeout_count += 1
        return timeout_count


def get_remaining_time(report_version_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT deadline, status FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not row or not row["deadline"]:
            return None, None
        
        deadline = datetime.strptime(row["deadline"], "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        remaining = deadline - now
        
        if remaining.total_seconds() <= 0:
            return "已超时", 0
        
        days = remaining.days
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        
        if days > 0:
            display = f"剩余 {days}天 {hours}小时"
        elif hours > 0:
            display = f"剩余 {hours}小时 {minutes}分钟"
        else:
            display = f"剩余 {minutes}分钟"
        
        is_urgent = remaining.total_seconds() < 24 * 3600
        
        return display, remaining.total_seconds()


def extend_deadline(report_version_id, new_deadline, operator_id=None):
    with get_db() as conn:
        report = conn.execute(
            "SELECT * FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not report:
            raise ValueError("报告不存在")
        if report["status"] != "已超时":
            raise ValueError("只有已超时的报告才能延期")
        
        conn.execute(
            """
            UPDATE report_versions 
            SET status = '审阅中', deadline = ?
            WHERE id = ?
            """,
            (new_deadline, report_version_id),
        )
        
        conn.execute(
            """
            INSERT INTO review_history (report_version_id, reviewer_id, action, comments)
            VALUES (?, ?, '延期', ?)
            """,
            (report_version_id, operator_id, f"延期至: {new_deadline}"),
        )
        
        conn.execute(
            "UPDATE review_assignments SET decision = NULL, completed_at = NULL WHERE report_version_id = ?",
            (report_version_id,),
        )


def force_close(report_version_id, operator_id=None):
    with get_db() as conn:
        report = conn.execute(
            "SELECT * FROM report_versions WHERE id = ?",
            (report_version_id,),
        ).fetchone()
        if not report:
            raise ValueError("报告不存在")
        if report["status"] != "已超时":
            raise ValueError("只有已超时的报告才能强制关闭")
        
        conn.execute(
            """
            UPDATE report_versions 
            SET status = '已退回', reject_reason = '超时未完成审阅，已强制关闭'
            WHERE id = ?
            """,
            (report_version_id,),
        )
        
        conn.execute(
            """
            INSERT INTO review_history (report_version_id, reviewer_id, action, comments)
            VALUES (?, ?, '强制关闭', '超时未完成审阅，已强制关闭')
            """,
            (report_version_id, operator_id),
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
        if report["status"] == "已超时":
            raise ValueError("报告已超时，无法进行审批操作")
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


def add_annotation(report_version_id, signal_id, content, annotation_type, author_id, priority="普通"):
    if annotation_type not in ANNOTATION_TYPES:
        raise ValueError(f"无效批注类型: {annotation_type}")
    if priority not in ANNOTATION_PRIORITIES:
        raise ValueError(f"无效优先级: {priority}")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO annotations
            (report_version_id, signal_id, content, annotation_type, priority, author_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (report_version_id, signal_id, content, annotation_type, priority, author_id),
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


def get_annotations(report_version_id, signal_id=None, status=None, priority=None):
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
        if priority:
            query += " AND a.priority = ?"
            params.append(priority)
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


def create_annotation_template(name, content, annotation_type, priority, is_public, creator_id):
    if annotation_type not in ANNOTATION_TYPES:
        raise ValueError(f"无效批注类型: {annotation_type}")
    if priority not in ANNOTATION_PRIORITIES:
        raise ValueError(f"无效优先级: {priority}")
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO annotation_templates
            (name, content, annotation_type, priority, is_public, creator_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, content, annotation_type, priority, 1 if is_public else 0, creator_id),
        )
        return cursor.lastrowid


def update_annotation_template(template_id, name=None, content=None, annotation_type=None, priority=None, is_public=None):
    fields = []
    values = []
    if name:
        fields.append("name = ?")
        values.append(name)
    if content:
        fields.append("content = ?")
        values.append(content)
    if annotation_type:
        if annotation_type not in ANNOTATION_TYPES:
            raise ValueError(f"无效批注类型: {annotation_type}")
        fields.append("annotation_type = ?")
        values.append(annotation_type)
    if priority:
        if priority not in ANNOTATION_PRIORITIES:
            raise ValueError(f"无效优先级: {priority}")
        fields.append("priority = ?")
        values.append(priority)
    if is_public is not None:
        fields.append("is_public = ?")
        values.append(1 if is_public else 0)
    values.append(template_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE annotation_templates SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )


def delete_annotation_template(template_id):
    with get_db() as conn:
        conn.execute("DELETE FROM annotation_templates WHERE id = ?", (template_id,))


def get_annotation_templates(user_id=None):
    with get_db() as conn:
        query = """
            SELECT at.*, r.name as creator_name
            FROM annotation_templates at
            JOIN reviewers r ON at.creator_id = r.id
            WHERE at.is_public = 1
        """
        params = []
        if user_id:
            query += " OR at.creator_id = ?"
            params.append(user_id)
        query += " ORDER BY at.is_public DESC, at.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_my_todo_list(reviewer_id):
    with get_db() as conn:
        priority_order = {"紧急": 0, "普通": 1, "低": 2}
        
        pending_reviews = conn.execute(
            """
            SELECT ra.*, rv.version_number, rv.status as report_status,
                   rs.device_name, rs.event_type
            FROM review_assignments ra
            JOIN report_versions rv ON ra.report_version_id = rv.id
            LEFT JOIN report_signals rs ON rs.report_version_id = rv.id
            WHERE ra.reviewer_id = ? AND ra.decision IS NULL
            AND rv.status IN ('审阅中', '已超时')
            ORDER BY rv.deadline ASC
            """,
            (reviewer_id,),
        ).fetchall()
        
        urgent_annotations = conn.execute(
            """
            SELECT a.*, rv.version_number, 
                   rs.device_name, rs.event_type,
                   r.name as author_name
            FROM annotations a
            JOIN report_versions rv ON a.report_version_id = rv.id
            JOIN report_signals rs ON a.signal_id = rs.id AND a.report_version_id = rs.report_version_id
            JOIN reviewers r ON a.author_id = r.id
            WHERE a.priority = '紧急' AND a.status = '开放'
            AND rv.status IN ('审阅中', '已超时')
            ORDER BY a.created_at DESC
            """,
            (),
        ).fetchall()
        
        todo_list = []
        for r in pending_reviews:
            remaining, seconds = get_remaining_time(r["report_version_id"])
            todo_list.append({
                "type": "review",
                "id": r["id"],
                "report_version_id": r["report_version_id"],
                "version_number": r["version_number"],
                "device_name": r["device_name"],
                "event_type": r["event_type"],
                "priority": "紧急" if seconds and seconds < 24 * 3600 else "普通",
                "remaining_time": remaining,
                "report_status": r["report_status"],
                "signal_id": None,
                "annotation_id": None,
            })
        
        for a in urgent_annotations:
            todo_list.append({
                "type": "annotation",
                "id": a["id"],
                "report_version_id": a["report_version_id"],
                "version_number": a["version_number"],
                "device_name": a["device_name"],
                "event_type": a["event_type"],
                "priority": a["priority"],
                "content": a["content"],
                "author_name": a["author_name"],
                "annotation_type": a["annotation_type"],
                "signal_id": a["signal_id"],
                "annotation_id": a["id"],
            })
        
        todo_list.sort(key=lambda x: priority_order.get(x["priority"], 3))
        return todo_list


def compare_report_versions_enhanced(version1_id, version2_id):
    base_changes = compare_report_versions(version1_id, version2_id)
    
    all_report_versions = get_all_report_versions()
    version_numbers = sorted([v["version_number"] for v in all_report_versions])
    
    v1 = get_report_version(version1_id)
    v2 = get_report_version(version2_id)
    
    for change in base_changes:
        key = f"{change['device_name']}|{change['event_type']}"
        
        old_signal = change.get("old_signal")
        new_signal = change.get("new_signal")
        
        prr_change = None
        ror_change = None
        ic_change = None
        ebgm_change = None
        
        if old_signal and new_signal:
            if old_signal.get("prr_value") and new_signal.get("prr_value"):
                diff = new_signal["prr_value"] - old_signal["prr_value"]
                prr_change = {
                    "old": round(old_signal["prr_value"], 3),
                    "new": round(new_signal["prr_value"], 3),
                    "diff": round(diff, 3),
                    "direction": "up" if diff > 0 else "down" if diff < 0 else "same"
                }
            if old_signal.get("ror_value") and new_signal.get("ror_value"):
                diff = new_signal["ror_value"] - old_signal["ror_value"]
                ror_change = {
                    "old": round(old_signal["ror_value"], 3),
                    "new": round(new_signal["ror_value"], 3),
                    "diff": round(diff, 3),
                    "direction": "up" if diff > 0 else "down" if diff < 0 else "same"
                }
            if old_signal.get("ic_value") and new_signal.get("ic_value"):
                diff = new_signal["ic_value"] - old_signal["ic_value"]
                ic_change = {
                    "old": round(old_signal["ic_value"], 3),
                    "new": round(new_signal["ic_value"], 3),
                    "diff": round(diff, 3),
                    "direction": "up" if diff > 0 else "down" if diff < 0 else "same"
                }
            if old_signal.get("ebgm_value") and new_signal.get("ebgm_value"):
                diff = new_signal["ebgm_value"] - old_signal["ebgm_value"]
                ebgm_change = {
                    "old": round(old_signal["ebgm_value"], 3),
                    "new": round(new_signal["ebgm_value"], 3),
                    "diff": round(diff, 3),
                    "direction": "up" if diff > 0 else "down" if diff < 0 else "same"
                }
        
        change["prr_change"] = prr_change
        change["ror_change"] = ror_change
        change["ic_change"] = ic_change
        change["ebgm_change"] = ebgm_change
        
        trend_data = []
        for v in all_report_versions:
            signals = get_report_signals(v["id"])
            for s in signals:
                if s["device_name"] == change["device_name"] and s["event_type"] == change["event_type"]:
                    strength_order = {"无信号": 0, "弱信号": 1, "中等信号": 2, "强信号": 3}
                    trend_data.append({
                        "version_number": v["version_number"],
                        "signal_strength": s["signal_strength"],
                        "strength_value": strength_order.get(s["signal_strength"], 0),
                        "prr_value": s.get("prr_value"),
                    })
                    break
        
        trend_data.sort(key=lambda x: x["version_number"])
        if len(trend_data) > 5:
            trend_data = trend_data[-5:]
        change["trend_data"] = trend_data
    
    return base_changes


def export_review_comments(report_version_id):
    report = get_report_version(report_version_id)
    if not report:
        raise ValueError("报告不存在")
    
    annotations = get_annotations(report_version_id)
    history = get_review_history(report_version_id)
    
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["=== 批注信息 ==="])
    writer.writerow(["信号名称", "批注内容", "批注类型", "优先级", "批注人", "批注时间", "状态", "回复数量"])
    
    signals = {s["id"]: f"{s['device_name']} - {s['event_type']}" for s in report.get("signals", [])}
    
    for ann in annotations:
        signal_name = signals.get(ann["signal_id"], f"信号{ann['signal_id']}")
        writer.writerow([
            signal_name,
            ann["content"],
            ann["annotation_type"],
            ann.get("priority", "普通"),
            ann["author_name"],
            ann["created_at"],
            ann["status"],
            len(ann.get("replies", [])),
        ])
    
    writer.writerow([])
    writer.writerow(["=== 审阅历史 ==="])
    writer.writerow(["操作时间", "操作人", "操作类型", "意见内容"])
    
    for h in history:
        writer.writerow([
            h["created_at"],
            h.get("reviewer_name", "系统"),
            h["action"],
            h.get("comments", ""),
        ])
    
    return output.getvalue()


def get_review_statistics():
    with get_db() as conn:
        stats = {}
        
        check_and_update_timeout()

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
        
        timeout_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM report_versions WHERE status = '已超时'"
        ).fetchone()["cnt"]
        stats["timeout_count"] = timeout_count
        stats["timeout_rate"] = round(timeout_count / submit_count * 100, 2) if submit_count > 0 else 0

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
        check_and_update_timeout()
        
        reports = conn.execute(
            "SELECT * FROM report_versions ORDER BY version_number DESC"
        ).fetchall()

        kanban = {"草稿": [], "审阅中": [], "已批准": [], "已退回": [], "已超时": []}

        for r in reports:
            report_dict = dict(r)
            
            remaining, seconds = get_remaining_time(r["id"])
            report_dict["remaining_time"] = remaining
            report_dict["remaining_seconds"] = seconds
            report_dict["is_urgent"] = seconds and seconds < 24 * 3600 and seconds > 0

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
