import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adverse_event.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    from review_module import init_review_tables, create_default_reviewers
    init_review_tables()
    create_default_reviewers()
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            registration_number TEXT,
            event_description TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('故障','伤害','死亡')),
            severity TEXT NOT NULL CHECK(severity IN ('严重','非严重')),
            report_date DATE NOT NULL,
            patient_age_group TEXT,
            patient_gender TEXT,
            usage_scenario TEXT,
            batch_number TEXT,
            device_category TEXT,
            device_class_code TEXT,
            hash_key TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_reports_device ON reports(device_name);
        CREATE INDEX IF NOT EXISTS idx_reports_event_type ON reports(event_type);
        CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date);
        CREATE INDEX IF NOT EXISTS idx_reports_hash ON reports(hash_key);
        CREATE INDEX IF NOT EXISTS idx_reports_reg ON reports(registration_number);

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            report_count INTEGER,
            prr_value REAL,
            prr_ci_lower REAL,
            prr_ci_upper REAL,
            prr_signal INTEGER DEFAULT 0,
            ror_value REAL,
            ror_ci_lower REAL,
            ror_ci_upper REAL,
            ror_signal INTEGER DEFAULT 0,
            ic_value REAL,
            ic025 REAL,
            bcpnn_signal INTEGER DEFAULT 0,
            ebgm_value REAL,
            eb05 REAL,
            mgps_signal INTEGER DEFAULT 0,
            signal_count INTEGER DEFAULT 0,
            signal_strength TEXT DEFAULT '无信号',
            p_value REAL,
            chi_square REAL,
            bonferroni_signal INTEGER DEFAULT 0,
            fdr_signal INTEGER DEFAULT 0,
            detection_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_signals_device ON signals(device_name);
        CREATE INDEX IF NOT EXISTS idx_signals_event ON signals(event_type);
        CREATE INDEX IF NOT EXISTS idx_signals_strength ON signals(signal_strength);

        CREATE TABLE IF NOT EXISTS signal_workflow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT '待评估' CHECK(status IN ('待评估','评估中','确认信号','排除')),
            action_measure TEXT,
            operator TEXT DEFAULT '系统',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );

        CREATE INDEX IF NOT EXISTS idx_workflow_signal ON signal_workflow(signal_id);
        CREATE INDEX IF NOT EXISTS idx_workflow_status ON signal_workflow(status);

        CREATE TABLE IF NOT EXISTS cusum_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            alert_month DATE NOT NULL,
            baseline_mean REAL,
            baseline_std REAL,
            cusum_value REAL,
            threshold REAL,
            is_alert INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_cusum_device ON cusum_alerts(device_name);

        CREATE TABLE IF NOT EXISTS signal_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            signal_strength TEXT NOT NULL CHECK(signal_strength IN ('强信号', '中等信号')),
            prr_value REAL,
            report_count INTEGER,
            detection_run_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_device ON signal_alerts(device_name);
        CREATE INDEX IF NOT EXISTS idx_alerts_strength ON signal_alerts(signal_strength);
        CREATE INDEX IF NOT EXISTS idx_alerts_created ON signal_alerts(created_at);

        CREATE TABLE IF NOT EXISTS detection_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prr_threshold REAL DEFAULT 2.0,
            min_report_count INTEGER DEFAULT 3,
            p_value_threshold REAL DEFAULT 0.05,
            ror_lower_threshold REAL DEFAULT 1.0,
            ic025_threshold REAL DEFAULT 0.0,
            eb05_threshold REAL DEFAULT 2.0,
            strong_signal_min_methods INTEGER DEFAULT 3,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '系统'
        );

        CREATE INDEX IF NOT EXISTS idx_config_active ON detection_config(is_active);

        CREATE TABLE IF NOT EXISTS detection_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_reports INTEGER,
            total_signals INTEGER,
            strong_signals INTEGER,
            medium_signals INTEGER,
            weak_signals INTEGER,
            config_id INTEGER,
            FOREIGN KEY (config_id) REFERENCES detection_config(id)
        );

        CREATE INDEX IF NOT EXISTS idx_runs_time ON detection_runs(run_time);

        CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detection_run_id INTEGER NOT NULL,
            device_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            report_count INTEGER,
            prr_value REAL,
            ror_value REAL,
            ic_value REAL,
            ebgm_value REAL,
            signal_count INTEGER,
            signal_strength TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_history_run ON signal_history(detection_run_id);
        CREATE INDEX IF NOT EXISTS idx_history_pair ON signal_history(device_name, event_type);

        CREATE TABLE IF NOT EXISTS signal_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detection_run_id INTEGER NOT NULL,
            device_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            previous_strength TEXT,
            current_strength TEXT,
            change_type TEXT NOT NULL CHECK(change_type IN ('升级', '降级', '新增', '消失')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_changes_run ON signal_changes(detection_run_id);
        CREATE INDEX IF NOT EXISTS idx_changes_type ON signal_changes(change_type);

        CREATE TABLE IF NOT EXISTS risk_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL UNIQUE,
            total_score REAL NOT NULL DEFAULT 0,
            risk_level TEXT NOT NULL DEFAULT '极低风险',
            signal_strength_factor REAL NOT NULL DEFAULT 0,
            signal_strength_score REAL NOT NULL DEFAULT 0,
            report_frequency_factor REAL NOT NULL DEFAULT 0,
            report_frequency_score REAL NOT NULL DEFAULT 0,
            severity_factor REAL NOT NULL DEFAULT 0,
            severity_score REAL NOT NULL DEFAULT 0,
            trend_factor REAL NOT NULL DEFAULT 0,
            trend_score REAL NOT NULL DEFAULT 0,
            bayesian_risk REAL NOT NULL DEFAULT 0,
            prediction_trend TEXT DEFAULT '稳',
            prediction_values TEXT,
            is_upgrade_alert INTEGER DEFAULT 0,
            detection_run_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_risk_device ON risk_scores(device_name);
        CREATE INDEX IF NOT EXISTS idx_risk_level ON risk_scores(risk_level);
        CREATE INDEX IF NOT EXISTS idx_risk_score ON risk_scores(total_score);

        CREATE TABLE IF NOT EXISTS risk_score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            total_score REAL NOT NULL,
            risk_level TEXT NOT NULL,
            signal_strength_score REAL NOT NULL DEFAULT 0,
            report_frequency_score REAL NOT NULL DEFAULT 0,
            severity_score REAL NOT NULL DEFAULT 0,
            trend_score REAL NOT NULL DEFAULT 0,
            bayesian_risk REAL NOT NULL DEFAULT 0,
            detection_run_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
        );

        CREATE INDEX IF NOT EXISTS idx_risk_history_device ON risk_score_history(device_name);
        CREATE INDEX IF NOT EXISTS idx_risk_history_time ON risk_score_history(created_at);

        CREATE TABLE IF NOT EXISTS risk_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_name TEXT NOT NULL,
            prediction_date DATE NOT NULL,
            predicted_score REAL NOT NULL,
            predicted_level TEXT NOT NULL,
            prediction_months_ahead INTEGER NOT NULL,
            model_type TEXT NOT NULL DEFAULT 'linear',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_prediction_device ON risk_predictions(device_name);
        CREATE INDEX IF NOT EXISTS idx_prediction_date ON risk_predictions(prediction_date);
        """)
