import pandas as pd
import hashlib
from db import get_db

REQUIRED_COLUMNS = {
    "器械名称": "device_name",
    "注册证号": "registration_number",
    "事件描述": "event_description",
    "事件类型": "event_type",
    "严重程度": "severity",
    "报告日期": "report_date",
    "患者年龄段": "patient_age_group",
    "患者性别": "patient_gender",
    "使用场景": "usage_scenario",
    "批次号": "batch_number",
}

OPTIONAL_COLUMNS = {
    "器械大类": "device_category",
    "器械分类编码": "device_class_code",
}

COLUMN_DESCRIPTIONS = {
    "器械名称": "必需。医疗器械的通用名称",
    "注册证号": "必需。医疗器械的注册证书编号",
    "事件描述": "必需。不良事件的详细描述（自由文本）",
    "事件类型": "必需。按监管分类：故障/伤害/死亡",
    "严重程度": "必需。严重/非严重",
    "报告日期": "必需。报告提交日期",
    "患者年龄段": "推荐。0-18/19-40/41-60/61-80/80+",
    "患者性别": "推荐。男/女/未知",
    "使用场景": "推荐。医院/家用/急救",
    "批次号": "推荐。器械生产批次号",
    "器械大类": "推荐，用于同类对比。植入类/体外诊断/治疗设备/监护设备等",
    "器械分类编码": "**必需用于同类对比**。国家医疗器械分类编码，取前4位识别同类器械",
}

VALID_EVENT_TYPES = {"故障", "伤害", "死亡"}
VALID_SEVERITIES = {"严重", "非严重"}
VALID_AGE_GROUPS = {"0-18", "19-40", "41-60", "61-80", "80+"}
VALID_GENDERS = {"男", "女", "未知"}
VALID_SCENARIOS = {"医院", "家用", "急救"}


def _make_hash_key(row):
    key_str = f"{row.get('registration_number', '')}|{row.get('report_date', '')}|{row.get('event_description', '')}"
    return hashlib.md5(key_str.encode("utf-8")).hexdigest()


def validate_dataframe(df):
    errors = []
    warnings = []
    missing_required = [cn for cn in REQUIRED_COLUMNS if cn not in df.columns]
    if missing_required:
        errors.append(f"缺少必需列: {', '.join(missing_required)}")
        return errors, warnings, df

    row_count = len(df)
    col_count = len(df.columns)

    null_counts = df[list(REQUIRED_COLUMNS.keys())].isnull().sum()
    for col, cnt in null_counts.items():
        if cnt > 0:
            warnings.append(f"列 '{col}' 有 {cnt}/{row_count} 条空值")

    invalid_event = ~df["事件类型"].isin(VALID_EVENT_TYPES)
    if invalid_event.any():
        bad_vals = df.loc[invalid_event, "事件类型"].unique().tolist()
        errors.append(f"事件类型包含无效值: {bad_vals}, 有效值为: {list(VALID_EVENT_TYPES)}")

    invalid_sev = ~df["严重程度"].isin(VALID_SEVERITIES)
    if invalid_sev.any():
        bad_vals = df.loc[invalid_sev, "严重程度"].unique().tolist()
        errors.append(f"严重程度包含无效值: {bad_vals}, 有效值为: {list(VALID_SEVERITIES)}")

    try:
        df["报告日期"] = pd.to_datetime(df["报告日期"])
    except Exception as e:
        errors.append(f"报告日期格式错误: {e}")

    age_col = "患者年龄段"
    if age_col in df.columns:
        invalid_age = df[age_col].notna() & ~df[age_col].isin(VALID_AGE_GROUPS)
        if invalid_age.any():
            bad_vals = df.loc[invalid_age, age_col].unique().tolist()
            warnings.append(f"患者年龄段包含非标准值: {bad_vals}, 标准值为: {list(VALID_AGE_GROUPS)}")

    gender_col = "患者性别"
    if gender_col in df.columns:
        invalid_gender = df[gender_col].notna() & ~df[gender_col].isin(VALID_GENDERS)
        if invalid_gender.any():
            bad_vals = df.loc[invalid_gender, gender_col].unique().tolist()
            warnings.append(f"患者性别包含非标准值: {bad_vals}, 标准值为: {list(VALID_GENDERS)}")

    scenario_col = "使用场景"
    if scenario_col in df.columns:
        invalid_scenario = df[scenario_col].notna() & ~df[scenario_col].isin(VALID_SCENARIOS)
        if invalid_scenario.any():
            bad_vals = df.loc[invalid_scenario, scenario_col].unique().tolist()
            warnings.append(f"使用场景包含非标准值: {bad_vals}, 标准值为: {list(VALID_SCENARIOS)}")

    return errors, warnings, df


def rename_columns(df):
    rename_map = {}
    for cn, en in REQUIRED_COLUMNS.items():
        if cn in df.columns:
            rename_map[cn] = en
    for cn, en in OPTIONAL_COLUMNS.items():
        if cn in df.columns:
            rename_map[cn] = en
    return df.rename(columns=rename_map)


def check_duplicates(df):
    df["hash_key"] = df.apply(_make_hash_key, axis=1)
    dup_mask = df["hash_key"].duplicated(keep="first")
    dup_count = dup_mask.sum()
    existing_hashes = set()
    with get_db() as conn:
        rows = conn.execute("SELECT hash_key FROM reports").fetchall()
        existing_hashes = {r["hash_key"] for r in rows}
    db_dup_mask = df["hash_key"].isin(existing_hashes)
    db_dup_count = db_dup_mask.sum()
    return dup_count, db_dup_count, df, db_dup_mask


def import_data(df, skip_db_duplicates=True):
    df = rename_columns(df)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.strftime("%Y-%m-%d")
    df["hash_key"] = df.apply(_make_hash_key, axis=1)

    existing_hashes = set()
    with get_db() as conn:
        rows = conn.execute("SELECT hash_key FROM reports").fetchall()
        existing_hashes = {r["hash_key"] for r in rows}

    if skip_db_duplicates:
        df = df[~df["hash_key"].isin(existing_hashes)]

    if df.empty:
        return 0, 0

    internal_dups = df["hash_key"].duplicated(keep="first")
    dup_count = internal_dups.sum()
    df = df[~internal_dups]

    cols = [
        "device_name", "registration_number", "event_description", "event_type",
        "severity", "report_date", "patient_age_group", "patient_gender",
        "usage_scenario", "batch_number", "device_category", "device_class_code", "hash_key"
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = None

    records = df[cols].values.tolist()
    with get_db() as conn:
        conn.executemany(
            f"INSERT OR IGNORE INTO reports ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            records,
        )

    return len(records) - len(df), len(df)


def load_reports(filters=None):
    with get_db() as conn:
        query = "SELECT * FROM reports WHERE 1=1"
        params = []
        if filters:
            if filters.get("date_start"):
                query += " AND report_date >= ?"
                params.append(filters["date_start"])
            if filters.get("date_end"):
                query += " AND report_date <= ?"
                params.append(filters["date_end"])
            if filters.get("device_name"):
                query += " AND device_name LIKE ?"
                params.append(f"%{filters['device_name']}%")
            if filters.get("event_type"):
                query += " AND event_type = ?"
                params.append(filters["event_type"])
            if filters.get("severity"):
                query += " AND severity = ?"
                params.append(filters["severity"])
            if filters.get("usage_scenario"):
                query += " AND usage_scenario = ?"
                params.append(filters["usage_scenario"])
        query += " ORDER BY report_date DESC"
        rows = conn.execute(query, params).fetchall()
        return pd.DataFrame([dict(r) for r in rows])


def get_report_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM reports").fetchone()["cnt"]
        devices = conn.execute("SELECT COUNT(DISTINCT device_name) as cnt FROM reports").fetchone()["cnt"]
        event_types = conn.execute("SELECT COUNT(DISTINCT event_type) as cnt FROM reports").fetchone()["cnt"]
        date_range = conn.execute(
            "SELECT MIN(report_date) as min_d, MAX(report_date) as max_d FROM reports"
        ).fetchone()
        return {
            "total_reports": total,
            "total_devices": devices,
            "total_event_types": event_types,
            "date_min": date_range["min_d"],
            "date_max": date_range["max_d"],
        }


def get_distinct_values(column):
    with get_db() as conn:
        rows = conn.execute(f"SELECT DISTINCT {column} FROM reports WHERE {column} IS NOT NULL").fetchall()
        return [r[0] for r in rows]
