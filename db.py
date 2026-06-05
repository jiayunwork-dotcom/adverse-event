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
        """)
