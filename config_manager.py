from db import get_db

DEFAULT_CONFIG = {
    "prr_threshold": 2.0,
    "min_report_count": 3,
    "p_value_threshold": 0.05,
    "ror_lower_threshold": 1.0,
    "ic025_threshold": 0.0,
    "eb05_threshold": 2.0,
    "strong_signal_min_methods": 3,
    "weight_signal_strength": 0.40,
    "weight_report_frequency": 0.25,
    "weight_severity": 0.20,
    "weight_trend": 0.15,
    "alert_continuous_rise_n": 3,
    "alert_jump_m": 15.0,
}

DEFAULT_WEIGHTS = {
    "signal_strength": 0.40,
    "report_frequency": 0.25,
    "severity": 0.20,
    "trend": 0.15,
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
                 strong_signal_min_methods, 
                 weight_signal_strength, weight_report_frequency, 
                 weight_severity, weight_trend,
                 alert_continuous_rise_n, alert_jump_m,
                 is_active, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, '系统')
                """,
                (
                    DEFAULT_CONFIG["prr_threshold"],
                    DEFAULT_CONFIG["min_report_count"],
                    DEFAULT_CONFIG["p_value_threshold"],
                    DEFAULT_CONFIG["ror_lower_threshold"],
                    DEFAULT_CONFIG["ic025_threshold"],
                    DEFAULT_CONFIG["eb05_threshold"],
                    DEFAULT_CONFIG["strong_signal_min_methods"],
                    DEFAULT_CONFIG["weight_signal_strength"],
                    DEFAULT_CONFIG["weight_report_frequency"],
                    DEFAULT_CONFIG["weight_severity"],
                    DEFAULT_CONFIG["weight_trend"],
                    DEFAULT_CONFIG["alert_continuous_rise_n"],
                    DEFAULT_CONFIG["alert_jump_m"],
                ),
            )


def get_risk_weights():
    config = get_active_config()
    return {
        "signal_strength": float(config.get("weight_signal_strength", DEFAULT_WEIGHTS["signal_strength"])),
        "report_frequency": float(config.get("weight_report_frequency", DEFAULT_WEIGHTS["report_frequency"])),
        "severity": float(config.get("weight_severity", DEFAULT_WEIGHTS["severity"])),
        "trend": float(config.get("weight_trend", DEFAULT_WEIGHTS["trend"])),
    }


def get_alert_config():
    config = get_active_config()
    return {
        "continuous_rise_n": int(config.get("alert_continuous_rise_n", 3)),
        "jump_m": float(config.get("alert_jump_m", 15.0)),
    }


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
             strong_signal_min_methods, 
             weight_signal_strength, weight_report_frequency, 
             weight_severity, weight_trend,
             alert_continuous_rise_n, alert_jump_m,
             is_active, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                float(config["prr_threshold"]),
                int(config["min_report_count"]),
                float(config["p_value_threshold"]),
                float(config["ror_lower_threshold"]),
                float(config["ic025_threshold"]),
                float(config["eb05_threshold"]),
                int(config["strong_signal_min_methods"]),
                float(config["weight_signal_strength"]),
                float(config["weight_report_frequency"]),
                float(config["weight_severity"]),
                float(config["weight_trend"]),
                int(config["alert_continuous_rise_n"]),
                float(config["alert_jump_m"]),
                created_by,
            ),
        )


def reset_to_default():
    save_new_config(DEFAULT_CONFIG, "系统")
