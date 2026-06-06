import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db, get_db
from config_manager import (
    init_default_config, get_risk_weights, get_alert_config,
    get_active_config, save_new_config, DEFAULT_WEIGHTS
)
from risk_assessment import (
    calculate_simulated_score, get_simulated_rank,
    save_simulator_scheme, get_simulator_schemes,
    delete_simulator_scheme, get_risk_scores_for_export,
    get_active_risk_alerts, confirm_risk_alert
)

def test_config_manager():
    print("=" * 60)
    print("Testing Config Manager")
    print("=" * 60)

    weights = get_risk_weights()
    print(f"Current weights: {weights}")
    assert abs(weights["signal_strength"] + weights["report_frequency"] +
               weights["severity"] + weights["trend"] - 1.0) < 0.01, \
        "Weights should sum to 1.0"
    print("✓ Weights sum to 1.0")

    alert_config = get_alert_config()
    print(f"Alert config: {alert_config}")
    assert "continuous_rise_n" in alert_config
    assert "jump_m" in alert_config
    print("✓ Alert config loaded correctly")

    new_config = get_active_config()
    new_config["weight_signal_strength"] = 0.50
    new_config["weight_report_frequency"] = 0.20
    new_config["weight_severity"] = 0.20
    new_config["weight_trend"] = 0.10
    save_new_config(new_config, created_by="test")

    updated_weights = get_risk_weights()
    print(f"Updated weights: {updated_weights}")
    assert abs(updated_weights["signal_strength"] - 0.50) < 0.01
    print("✓ Weights updated correctly")

    save_new_config({
        "prr_threshold": 2.0, "min_report_count": 3, "p_value_threshold": 0.05,
        "ror_lower_threshold": 1.0, "ic025_threshold": 0.0, "eb05_threshold": 2.0,
        "strong_signal_min_methods": 3,
        "weight_signal_strength": 0.40, "weight_report_frequency": 0.25,
        "weight_severity": 0.20, "weight_trend": 0.15,
        "alert_continuous_rise_n": 3, "alert_jump_m": 15.0
    }, created_by="test")
    print("✓ Config reset to defaults")

def test_simulator():
    print("\n" + "=" * 60)
    print("Testing Risk Simulator")
    print("=" * 60)

    factor_values = {
        "signal_strength": 80,
        "report_frequency": 60,
        "severity": 40,
        "trend": 50
    }

    result = calculate_simulated_score(factor_values)
    print(f"Simulated score: {result['total_score']:.2f}")
    print(f"Risk level: {result['risk_level']}")
    print(f"Risk color: {result['risk_color']}")
    assert 0 <= result["total_score"] <= 100
    assert result["risk_level"] is not None
    assert result["risk_color"].startswith("#")
    print("✓ Simulation result valid")

    print(f"Bayesian distribution: {result['bayesian_distribution']}")
    assert "low" in result["bayesian_distribution"]
    assert "medium" in result["bayesian_distribution"]
    assert "high" in result["bayesian_distribution"]
    print("✓ Bayesian distribution valid")

    rank = get_simulated_rank(result["total_score"])
    print(f"Simulated rank: {rank}")
    print("✓ Rank calculation works")

    test_scheme_name = f"test_scheme_{os.getpid()}"
    save_simulator_scheme(test_scheme_name, factor_values, created_by="test")
    print(f"✓ Saved scheme: {test_scheme_name}")

    schemes = get_simulator_schemes()
    print(f"Total schemes: {len(schemes)}")
    test_scheme = next((s for s in schemes if s["scheme_name"] == test_scheme_name), None)
    assert test_scheme is not None
    print("✓ Scheme loaded correctly")

    delete_simulator_scheme(test_scheme["id"])
    schemes_after = get_simulator_schemes()
    assert not any(s["scheme_name"] == test_scheme_name for s in schemes_after)
    print("✓ Scheme deleted correctly")

def test_alerts():
    print("\n" + "=" * 60)
    print("Testing Risk Alerts")
    print("=" * 60)

    alerts = get_active_risk_alerts(limit=10)
    print(f"Active alerts: {len(alerts)}")
    print("✓ Alert retrieval works")

def test_export():
    print("\n" + "=" * 60)
    print("Testing Export Function")
    print("=" * 60)

    export_data = get_risk_scores_for_export()
    print(f"Export records: {len(export_data)}")

    if export_data:
        sample = export_data[0]
        expected_fields = [
            "device_name", "total_score", "risk_level", "risk_color_hex",
            "weight_signal_strength", "weight_report_frequency",
            "weight_severity", "weight_trend",
            "bayesian_prob_low", "bayesian_prob_medium", "bayesian_prob_high",
            "last_score_change", "has_active_alert"
        ]
        for field in expected_fields:
            assert field in sample, f"Missing field: {field}"
            print(f"  ✓ Field exists: {field} = {sample[field]}")
        print("✓ All expected export fields present")

if __name__ == "__main__":
    try:
        init_db()
        init_default_config()

        test_config_manager()
        test_simulator()
        test_alerts()
        test_export()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
