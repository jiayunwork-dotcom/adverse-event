import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import gammaln, digamma, polygamma
from db import get_db
from config_manager import get_active_config


def build_contingency_table(df, device_name, event_type):
    a = len(df[(df["device_name"] == device_name) & (df["event_type"] == event_type)])
    b = len(df[(df["device_name"] == device_name) & (df["event_type"] != event_type)])
    c = len(df[(df["device_name"] != device_name) & (df["event_type"] == event_type)])
    d = len(df[(df["device_name"] != device_name) & (df["event_type"] != event_type)])
    return a, b, c, d


def compute_prr(a, b, c, d, config=None):
    if config is None:
        config = get_active_config()

    prr_threshold = config.get("prr_threshold", 2.0)
    min_report_count = config.get("min_report_count", 3)
    p_value_threshold = config.get("p_value_threshold", 0.05)

    n1 = a + b
    n2 = c + d
    if a == 0 or c == 0 or n1 == 0 or n2 == 0:
        return np.nan, np.nan, np.nan, np.nan, 1.0, False
    prr = (a / n1) / (c / n2)
    se_ln_prr = np.sqrt(1.0 / a + 1.0 / c - 1.0 / n1 - 1.0 / n2) if a > 0 and c > 0 else np.nan
    ci_lower = np.exp(np.log(prr) - 1.96 * se_ln_prr) if not np.isnan(se_ln_prr) else np.nan
    ci_upper = np.exp(np.log(prr) + 1.96 * se_ln_prr) if not np.isnan(se_ln_prr) else np.nan

    chi2_val = None
    p_val = 1.0
    if a > 0 and b >= 0 and c > 0 and d >= 0:
        table = np.array([[a, b], [c, d]])
        try:
            chi2_val, p_val, _, _ = stats.chi2_contingency(table, correction=False)
        except ValueError:
            chi2_val, p_val = np.nan, 1.0

    is_signal = (prr >= prr_threshold) and (a >= min_report_count) and (p_val < p_value_threshold) if not np.isnan(prr) else False
    return prr, ci_lower, ci_upper, chi2_val, p_val, is_signal


def compute_ror(a, b, c, d, config=None):
    if config is None:
        config = get_active_config()

    ror_lower_threshold = config.get("ror_lower_threshold", 1.0)

    if a == 0 or b == 0 or c == 0 or d == 0:
        ror = np.nan
        ci_lower = np.nan
        ci_upper = np.nan
    else:
        ror = (a * d) / (b * c)
        se_ln_ror = np.sqrt(1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d)
        ci_lower = np.exp(np.log(ror) - 1.96 * se_ln_ror)
        ci_upper = np.exp(np.log(ror) + 1.96 * se_ln_ror)
    is_signal = ci_lower > ror_lower_threshold if not np.isnan(ci_lower) else False
    return ror, ci_lower, ci_upper, is_signal


def compute_bcpnn(a, b, c, d, config=None):
    if config is None:
        config = get_active_config()

    ic025_threshold = config.get("ic025_threshold", 0.0)

    N = a + b + c + d
    if N == 0:
        return np.nan, np.nan, False
    n_device = a + b
    n_event = a + c
    E = (n_device * n_event) / N
    if E == 0:
        return np.nan, np.nan, False
    IC = np.log2(a / E)

    alpha1 = 0.5
    beta1 = 0.5
    alpha2 = 0.5
    beta2 = 0.5
    alpha_post = alpha1 + a
    beta_post = N - a + beta1
    gamma_post = alpha2 + n_device
    delta_post = N - n_device + beta2

    var_ic = (
        (digamma(alpha_post) - digamma(alpha_post + beta_post))
        + (digamma(N - a + beta1) - digamma(alpha_post + beta_post))
        + (digamma(gamma_post) - digamma(gamma_post + delta_post))
        + (digamma(N - n_device + beta2) - digamma(gamma_post + delta_post))
    )

    def trigamma(x):
        return polygamma(1, x)

    var_ic_approx = (
        trigamma(alpha_post) - trigamma(alpha_post + beta_post)
        + trigamma(N - a + beta1) - trigamma(alpha_post + beta_post)
        + trigamma(gamma_post) - trigamma(gamma_post + delta_post)
        + trigamma(N - n_device + beta2) - trigamma(gamma_post + delta_post)
    )
    var_ic_approx = max(var_ic_approx, 1e-10)
    sd_ic = np.sqrt(var_ic_approx)
    IC025 = IC - 1.645 * sd_ic
    is_signal = IC025 > ic025_threshold
    return IC, IC025, is_signal


def _log_gamma(x):
    return gammaln(x)


def compute_mgps(a, b, c, d, config=None):
    if config is None:
        config = get_active_config()

    eb05_threshold = config.get("eb05_threshold", 2.0)

    N = a + b + c + d
    if N == 0 or a == 0:
        return np.nan, np.nan, False
    n_device = a + b
    n_event = a + c
    E = (n_device * n_event) / N
    if E == 0:
        return np.nan, np.nan, False

    O = a
    RR = O / E

    alpha1 = 0.2
    beta1 = 0.1
    alpha2 = 0.2
    beta2 = 0.1

    n_mix = 10
    p1_range = np.linspace(0.01, 0.99, n_mix)

    best_Q = -np.inf
    best_p1 = 0.5
    best_alpha1 = 2.0
    best_beta1 = 2.0

    for p1 in p1_range:
        p2 = 1 - p1
        for a1_try in [1.0, 2.0, 3.0]:
            for b1_try in [0.5, 1.0, 2.0]:
                log_Q = (
                    np.log(p1)
                    + a1_try * np.log(b1_try)
                    - _log_gamma(a1_try)
                    + _log_gamma(a1_try + O)
                    - (a1_try + O) * np.log(b1_try + E)
                    + _log_gamma(a1_try + b1_try + N)
                    - _log_gamma(a1_try + b1_try)
                    - _log_gamma(b1_try + N - O + 1e-10)
                    + _log_gamma(b1_try + N)
                    + np.log(p2)
                    + alpha2 * np.log(beta2)
                    - _log_gamma(alpha2)
                    + _log_gamma(alpha2 + O)
                    - (alpha2 + O) * np.log(beta2 + E)
                )
                if log_Q > best_Q:
                    best_Q = log_Q
                    best_p1 = p1
                    best_alpha1 = a1_try
                    best_beta1 = b1_try

    p1 = best_p1
    p2 = 1 - p1
    a1 = best_alpha1
    b1 = best_beta1
    a2 = alpha2
    b2 = beta2

    post_alpha1 = a1 + O
    post_beta1 = b1 + E
    post_alpha2 = a2 + O
    post_beta2 = b2 + E

    ebgm1 = post_alpha1 / post_beta1
    ebgm2 = post_alpha2 / post_beta2
    EBGM = p1 * ebgm1 + p2 * ebgm2

    n_sim = 10000
    seed = int((a + b + c + d) * 1000) % (2**31 - 1)
    rng = np.random.default_rng(seed)
    comp1 = rng.gamma(post_alpha1, 1.0 / post_beta1, n_sim)
    comp2 = rng.gamma(post_alpha2, 1.0 / post_beta2, n_sim)
    mask = rng.random(n_sim) < p1
    samples = np.where(mask, comp1, comp2)
    EB05 = np.percentile(samples, 10)

    is_signal = EB05 >= eb05_threshold
    return EBGM, EB05, is_signal


def compute_signal_strength(prr_signal, ror_signal, bcpnn_signal, mgps_signal, config=None):
    if config is None:
        config = get_active_config()

    strong_min_methods = config.get("strong_signal_min_methods", 3)
    count = int(prr_signal) + int(ror_signal) + int(bcpnn_signal) + int(mgps_signal)
    if count >= strong_min_methods:
        return count, "强信号"
    elif count == 2:
        return count, "中等信号"
    elif count == 1:
        return count, "弱信号"
    else:
        return count, "无信号"


def run_signal_detection(df=None, config=None):
    if config is None:
        config = get_active_config()

    if df is None:
        from data_import import load_reports
        df = load_reports()

    if df.empty:
        return pd.DataFrame()

    device_event_pairs = df.groupby(["device_name", "event_type"]).size().reset_index(name="count")
    results = []

    for _, row in device_event_pairs.iterrows():
        device = row["device_name"]
        event = row["event_type"]
        a, b, c, d = build_contingency_table(df, device, event)

        prr_val, prr_ci_l, prr_ci_u, chi2, p_val, prr_sig = compute_prr(a, b, c, d, config)
        ror_val, ror_ci_l, ror_ci_u, ror_sig = compute_ror(a, b, c, d, config)
        ic_val, ic025, bcpnn_sig = compute_bcpnn(a, b, c, d, config)
        ebgm_val, eb05, mgps_sig = compute_mgps(a, b, c, d, config)

        sig_count, strength = compute_signal_strength(prr_sig, ror_sig, bcpnn_sig, mgps_sig, config)

        results.append({
            "device_name": device,
            "event_type": event,
            "report_count": a,
            "prr_value": prr_val,
            "prr_ci_lower": prr_ci_l,
            "prr_ci_upper": prr_ci_u,
            "prr_signal": int(prr_sig),
            "ror_value": ror_val,
            "ror_ci_lower": ror_ci_l,
            "ror_ci_upper": ror_ci_u,
            "ror_signal": int(ror_sig),
            "ic_value": ic_val,
            "ic025": ic025,
            "bcpnn_signal": int(bcpnn_sig),
            "ebgm_value": ebgm_val,
            "eb05": eb05,
            "mgps_signal": int(mgps_sig),
            "signal_count": sig_count,
            "signal_strength": strength,
            "p_value": p_val,
            "chi_square": chi2,
        })

    result_df = pd.DataFrame(results)
    return result_df


def save_signals(result_df):
    if result_df.empty:
        return
    with get_db() as conn:
        conn.execute("DELETE FROM signals")
        cols = [
            "device_name", "event_type", "report_count",
            "prr_value", "prr_ci_lower", "prr_ci_upper", "prr_signal",
            "ror_value", "ror_ci_lower", "ror_ci_upper", "ror_signal",
            "ic_value", "ic025", "bcpnn_signal",
            "ebgm_value", "eb05", "mgps_signal",
            "signal_count", "signal_strength", "p_value", "chi_square",
            "bonferroni_signal", "fdr_signal",
        ]
        for c in cols:
            if c not in result_df.columns:
                result_df[c] = 0
        records = result_df[cols].values.tolist()
        conn.executemany(
            f"INSERT INTO signals ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            records,
        )


def load_signals():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM signals").fetchall()
        return pd.DataFrame([dict(r) for r in rows])


def get_signal_detail(device_name, event_type):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM signals WHERE device_name = ? AND event_type = ?",
            (device_name, event_type),
        ).fetchone()
        return dict(row) if row else None
