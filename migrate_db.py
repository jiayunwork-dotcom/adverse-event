import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adverse_event.db")


def migrate_database():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(detection_config)")
        columns = [col[1] for col in cursor.fetchall()]

        new_columns = [
            ("weight_signal_strength", "REAL DEFAULT 0.40"),
            ("weight_report_frequency", "REAL DEFAULT 0.25"),
            ("weight_severity", "REAL DEFAULT 0.20"),
            ("weight_trend", "REAL DEFAULT 0.15"),
            ("alert_continuous_rise_n", "INTEGER DEFAULT 3"),
            ("alert_jump_m", "REAL DEFAULT 15.0"),
        ]

        for col_name, col_def in new_columns:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE detection_config ADD COLUMN {col_name} {col_def}")
                print(f"Added column: {col_name}")
            else:
                print(f"Column already exists: {col_name}")

        cursor.execute("PRAGMA table_info(risk_scores)")
        columns = [col[1] for col in cursor.fetchall()]

        new_rs_columns = [
            ("weight_signal_strength", "REAL DEFAULT 0.40"),
            ("weight_report_frequency", "REAL DEFAULT 0.25"),
            ("weight_severity", "REAL DEFAULT 0.20"),
            ("weight_trend", "REAL DEFAULT 0.15"),
        ]

        for col_name, col_def in new_rs_columns:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE risk_scores ADD COLUMN {col_name} {col_def}")
                print(f"Added column: {col_name}")
            else:
                print(f"Column already exists: {col_name}")

        table_definitions = [
            """
            CREATE TABLE IF NOT EXISTS risk_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT NOT NULL,
                alert_type TEXT NOT NULL CHECK(alert_type IN ('continuous_rise', 'jump')),
                current_score REAL NOT NULL,
                previous_score REAL,
                change_amount REAL,
                trigger_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_confirmed INTEGER DEFAULT 0,
                confirmed_by TEXT,
                confirmed_at TIMESTAMP,
                detection_run_id INTEGER,
                FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS risk_simulator_schemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scheme_name TEXT NOT NULL,
                signal_strength REAL NOT NULL,
                report_frequency REAL NOT NULL,
                severity REAL NOT NULL,
                trend REAL NOT NULL,
                created_by TEXT DEFAULT '用户',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ]

        for table_sql in table_definitions:
            cursor.execute(table_sql)
            print("Ensured table exists")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_alerts_device ON risk_alerts(device_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_alerts_type ON risk_alerts(alert_type)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_alerts_confirmed ON risk_alerts(is_confirmed)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_alerts_time ON risk_alerts(trigger_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sim_schemes_name ON risk_simulator_schemes(scheme_name)
        """)

        cursor.execute("SELECT COUNT(*) as cnt FROM detection_config")
        if cursor.fetchone()["cnt"] > 0:
            cursor.execute("""
                UPDATE detection_config SET
                    weight_signal_strength = COALESCE(weight_signal_strength, 0.40),
                    weight_report_frequency = COALESCE(weight_report_frequency, 0.25),
                    weight_severity = COALESCE(weight_severity, 0.20),
                    weight_trend = COALESCE(weight_trend, 0.15),
                    alert_continuous_rise_n = COALESCE(alert_continuous_rise_n, 3),
                    alert_jump_m = COALESCE(alert_jump_m, 15.0)
                WHERE is_active = 1
            """)
            print("Updated active config with default values for new columns")

        conn.commit()
        print("\n✅ Database migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        migrate_database()
    else:
        print("Database does not exist yet, no migration needed.")
        print("It will be created with the new schema on first run.")
