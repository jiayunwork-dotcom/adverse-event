from db import get_db

DEFAULT_CONFIG = {
    "prr_threshold": 2.0,
    "min_report_count": 3,
    "p_value_threshold": 0.05,
    "ror_lower_threshold": 1.0,
    "ic025_threshold": 0.0,
    "eb05_threshold": 2.0,
    "strong_signal_min_methods": 3,
}


def init_default_config():
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) as cnt FROM detection_config").fetchone()
        if row["cnt"] == 0:
            conn.execute(
                """
                INSERT INTO detection_config 
                (prr_threshold, min_report_count, p_value_threshold, 
                 ror_lower_threshold, ic025_threshold, eb05_threshold, 
                 strong_signal_min_methods, is_active, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, '系统')
                """,
                (
                    DEFAULT_CONFIG["prr_threshold"],
                    DEFAULT_CONFIG["min_report_count"],
                    DEFAULT_CONFIG["p_value_threshold"],
                    DEFAULT_CONFIG["ror_lower_threshold"],
                    DEFAULT_CONFIG["ic025_threshold"],
                    DEFAULT_CONFIG["eb05_threshold"],
                    DEFAULT_CONFIG["strong_signal_min_methods"],
                ),
            )


def get_active_config():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM detection_config WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            init_default_config()
            return DEFAULT_CONFIG.copy()
        return dict(row)


def get_all_configs():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM detection_config ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def save_new_config(config, created_by="用户"):
    for key in DEFAULT_CONFIG:
        if key not in config:
            config[key] = DEFAULT_CONFIG[key]

    with get_db() as conn:
        conn.execute("UPDATE detection_config SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            """
            INSERT INTO detection_config 
            (prr_threshold, min_report_count, p_value_threshold, 
             ror_lower_threshold, ic025_threshold, eb05_threshold, 
             strong_signal_min_methods, is_active, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                float(config["prr_threshold"]),
                int(config["min_report_count"]),
                float(config["p_value_threshold"]),
                float(config["ror_lower_threshold"]),
                float(config["ic025_threshold"]),
                float(config["eb05_threshold"]),
                int(config["strong_signal_min_methods"]),
                created_by,
            ),
        )


def reset_to_default():
    save_new_config(DEFAULT_CONFIG, "系统")
