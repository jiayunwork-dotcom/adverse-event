import numpy as np
import pandas as pd


def bonferroni_correction(p_values, alpha=0.05):
    n = len(p_values)
    if n == 0:
        return np.array([], dtype=bool)
    adjusted_alpha = alpha / n
    return p_values <= adjusted_alpha


def benjamini_hochberg_fdr(p_values, alpha=0.05):
    n = len(p_values)
    if n == 0:
        return np.array([], dtype=bool)
    sorted_indices = np.argsort(p_values)
    sorted_p = p_values[sorted_indices]
    thresholds = np.arange(1, n + 1) / n * alpha
    comparisons = sorted_p <= thresholds
    if not np.any(comparisons):
        return np.zeros(n, dtype=bool)
    last_significant = np.max(np.where(comparisons)[0])
    significant_sorted = np.zeros(n, dtype=bool)
    significant_sorted[: last_significant + 1] = True
    result = np.zeros(n, dtype=bool)
    result[sorted_indices] = significant_sorted
    return result


def apply_corrections(signals_df, alpha=0.05):
    if signals_df.empty:
        signals_df["bonferroni_signal"] = 0
        signals_df["fdr_signal"] = 0
        return signals_df

    p_vals = signals_df["p_value"].fillna(1.0).values.astype(float)

    bonf_signals = bonferroni_correction(p_vals, alpha)
    fdr_signals = benjamini_hochberg_fdr(p_vals, alpha)

    signals_df["bonferroni_signal"] = bonf_signals.astype(int)
    signals_df["fdr_signal"] = fdr_signals.astype(int)

    return signals_df


def get_corrected_signal_strength(row, correction_method="fdr"):
    if correction_method == "bonferroni":
        prr_sig = row["prr_signal"] and row["bonferroni_signal"]
        ror_sig = row["ror_signal"] and row["bonferroni_signal"]
        bcpnn_sig = row["bcpnn_signal"] and row["bonferroni_signal"]
        mgps_sig = row["mgps_signal"] and row["bonferroni_signal"]
    elif correction_method == "fdr":
        prr_sig = row["prr_signal"] and row["fdr_signal"]
        ror_sig = row["ror_signal"] and row["fdr_signal"]
        bcpnn_sig = row["bcpnn_signal"] and row["fdr_signal"]
        mgps_sig = row["mgps_signal"] and row["fdr_signal"]
    else:
        prr_sig = row["prr_signal"]
        ror_sig = row["ror_signal"]
        bcpnn_sig = row["bcpnn_signal"]
        mgps_sig = row["mgps_signal"]

    count = int(prr_sig) + int(ror_sig) + int(bcpnn_sig) + int(mgps_sig)
    if count >= 3:
        return "强信号"
    elif count == 2:
        return "中等信号"
    elif count == 1:
        return "弱信号"
    else:
        return "无信号"
