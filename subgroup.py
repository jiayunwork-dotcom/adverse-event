import numpy as np
import pandas as pd
from algorithms import compute_prr


def compute_subgroup_prr(df, device_name, event_type, subgroup_col):
    subgroups = df[subgroup_col].dropna().unique()
    results = []
    overall_a, overall_b, overall_c, overall_d = 0, 0, 0, 0
    total_df = df.copy()
    n_all = len(total_df)
    n_device_all = len(total_df[total_df["device_name"] == device_name])
    n_event_all = len(total_df[total_df["event_type"] == event_type])

    overall_a_val = len(total_df[(total_df["device_name"] == device_name) & (total_df["event_type"] == event_type)])
    overall_b_val = n_device_all - overall_a_val
    overall_c_val = n_event_all - overall_a_val
    overall_d_val = n_all - overall_a_val - overall_b_val - overall_c_val

    overall_prr, _, _, _, _, _ = compute_prr(overall_a_val, overall_b_val, overall_c_val, overall_d_val)

    for sg in sorted(subgroups):
        sg_df = df[df[subgroup_col] == sg]
        n_total = len(sg_df)
        if n_total == 0:
            continue
        a = len(sg_df[(sg_df["device_name"] == device_name) & (sg_df["event_type"] == event_type)])
        b = len(sg_df[(sg_df["device_name"] == device_name) & (sg_df["event_type"] != event_type)])
        c = len(sg_df[(sg_df["device_name"] != device_name) & (sg_df["event_type"] == event_type)])
        d = len(sg_df[(sg_df["device_name"] != device_name) & (sg_df["event_type"] != event_type)])

        prr, ci_l, ci_u, chi2, p_val, is_sig = compute_prr(a, b, c, d)
        ratio = prr / overall_prr if overall_prr > 0 and not np.isnan(prr) else np.nan
        is_elevated = ratio > 1.5 if not np.isnan(ratio) else False

        results.append({
            "subgroup": sg,
            "subgroup_col": subgroup_col,
            "report_count": a,
            "total_in_subgroup": n_total,
            "prr": prr,
            "prr_ci_lower": ci_l,
            "prr_ci_upper": ci_u,
            "p_value": p_val,
            "is_signal": is_sig,
            "prr_ratio_to_overall": ratio,
            "is_elevated": is_elevated,
        })

    return pd.DataFrame(results), overall_prr


def stratify_by_age(df, device_name, event_type):
    return compute_subgroup_prr(df, device_name, event_type, "patient_age_group")


def stratify_by_gender(df, device_name, event_type):
    return compute_subgroup_prr(df, device_name, event_type, "patient_gender")


def stratify_by_scenario(df, device_name, event_type):
    return compute_subgroup_prr(df, device_name, event_type, "usage_scenario")


def run_all_stratifications(df, device_name, event_type):
    age_result, overall_prr = stratify_by_age(df, device_name, event_type)
    gender_result, _ = stratify_by_gender(df, device_name, event_type)
    scenario_result, _ = stratify_by_scenario(df, device_name, event_type)

    return {
        "age": age_result,
        "gender": gender_result,
        "scenario": scenario_result,
        "overall_prr": overall_prr,
    }
