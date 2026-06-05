import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import init_db, get_db
from data_import import import_data, rename_columns
from algorithms import run_signal_detection, save_signals
from correction import apply_corrections
from workflow import init_workflow_for_signals

init_db()

np.random.seed(42)

device_names = [
    "心脏起搏器X100", "胰岛素泵A200", "人工关节Z300", "血液透析机B400",
    "呼吸机C500", "心脏支架D600", "血糖仪E700", "除颤器F800",
    "超声诊断仪G900", "心电图机H1000", "体外膜肺氧合I1100", "输液泵J1200",
]

registration_numbers = [f"REG-{i:04d}" for i in range(len(device_names))]
class_codes = ["C3401", "C3401", "C3501", "C3601", "C3701", "C3402", "C3801", "C3403", "C3901", "C3902", "C3702", "C3602"]
categories = ["植入类", "体外诊断", "植入类", "治疗设备", "监护设备", "植入类", "体外诊断", "治疗设备", "监护设备", "监护设备", "治疗设备", "治疗设备"]
event_types = ["故障", "伤害", "死亡"]
severities = ["严重", "非严重"]
age_groups = ["0-18", "19-40", "41-60", "61-80", "80+"]
genders = ["男", "女"]
scenarios = ["医院", "家用", "急救"]

n_records = 2000
records = []

for i in range(n_records):
    dev_idx = np.random.choice(len(device_names), p=[0.15, 0.12, 0.13, 0.08, 0.10, 0.10, 0.08, 0.06, 0.05, 0.04, 0.05, 0.04])
    if dev_idx == 0:
        evt = np.random.choice(event_types, p=[0.3, 0.55, 0.15])
    elif dev_idx == 1:
        evt = np.random.choice(event_types, p=[0.4, 0.5, 0.1])
    elif dev_idx == 2:
        evt = np.random.choice(event_types, p=[0.35, 0.55, 0.1])
    else:
        evt = np.random.choice(event_types, p=[0.5, 0.4, 0.1])

    sev = np.random.choice(severities, p=[0.35, 0.65]) if evt != "死亡" else "严重"
    age = np.random.choice(age_groups, p=[0.05, 0.15, 0.3, 0.35, 0.15])
    if dev_idx in [0, 2, 5] and age in ["61-80", "80+"]:
        if np.random.random() < 0.3:
            evt = "伤害"
            sev = "严重"

    gender = np.random.choice(genders)
    scenario = np.random.choice(scenarios, p=[0.6, 0.25, 0.15])

    month = np.random.randint(1, 13)
    year = np.random.choice([2022, 2023, 2024, 2025], p=[0.15, 0.25, 0.30, 0.30])
    day = np.random.randint(1, 28)
    report_date = f"{year}-{month:02d}-{day:02d}"

    batch = f"BATCH-{dev_idx:02d}-{np.random.randint(100, 999)}"

    desc_templates = {
        "故障": ["设备运行中断", "功能异常", "显示错误", "传感器失灵", "电池故障"],
        "伤害": ["患者疼痛", "皮肤灼伤", "过敏反应", "感染", "组织损伤"],
        "死亡": ["患者死亡", "致死性事件", "心肺功能停止", "多器官衰竭", "严重并发症"],
    }
    desc = np.random.choice(desc_templates[evt])

    records.append({
        "器械名称": device_names[dev_idx],
        "注册证号": registration_numbers[dev_idx],
        "事件描述": desc,
        "事件类型": evt,
        "严重程度": sev,
        "报告日期": report_date,
        "患者年龄段": age,
        "患者性别": gender,
        "使用场景": scenario,
        "批次号": batch,
        "器械大类": categories[dev_idx],
        "器械分类编码": class_codes[dev_idx],
    })

df = pd.DataFrame(records)
print(f"Generated {len(df)} sample records")
print(f"Devices: {df['器械名称'].nunique()}")
print(f"Event types: {df['事件类型'].value_counts().to_dict()}")

dup_count, new_count = import_data(df, skip_db_duplicates=False)
print(f"Imported: {new_count} new records, {dup_count} duplicates skipped")

result_df = run_signal_detection()
if not result_df.empty:
    result_df = apply_corrections(result_df)
    save_signals(result_df)
    init_workflow_for_signals()
    print(f"Signal detection complete: {len(result_df)} signals found")
    print(result_df[["device_name", "event_type", "signal_strength"]].to_string())
else:
    print("No signals detected")

print("\nDemo data loaded successfully!")
