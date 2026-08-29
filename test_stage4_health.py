from __future__ import annotations

import pytest

from engine_model.stage1_3_hybrid_engine_output import Stage13HybridEngineOutput
from engine_model.stage4_health_parameters import (
    GENERATOR_AIRFRAME_MAX_POWER_W,
    GENERATOR_A_CURVE,
    GENERATOR_B_CURVE,
    GENERATOR_VOLTAGE_MAX_V,
    GENERATOR_VOLTAGE_MIN_V,
    GENERATOR_SWITCH_HOLD_TIME_S,
    GENERATOR_SWITCH_THRESHOLD_RPM,
    get_health_state,
    generator_switch_state,
    lookup_digitized_generator_current,
    update_generator_switch_timer,
)


def _linear_expected(rpm: float, curve: dict[float, float]) -> float:
    points = sorted(curve.items())
    if rpm <= points[0][0]:
        return points[0][1]
    if rpm >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        if x0 <= rpm <= x1:
            frac = (rpm - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return points[-1][1]


def test_generator_current_interpolation_matches_digitized_curves() -> None:
    for rpm in [2250.0, 2750.0, 3750.0, 5250.0, 5700.0]:
        assert lookup_digitized_generator_current(rpm, "A") == pytest.approx(_linear_expected(rpm, GENERATOR_A_CURVE))
        assert lookup_digitized_generator_current(rpm, "B") == pytest.approx(_linear_expected(rpm, GENERATOR_B_CURVE))


def test_generator_switching_rules_remain_unchanged() -> None:
    timer = 0.0
    timer = update_generator_switch_timer(timer, 2390.0, 20.0)
    assert timer == pytest.approx(0.0, abs=1e-12)
    assert not generator_switch_state(2390.0, time_above_threshold_s=timer).ready

    timer = 0.0
    timer = update_generator_switch_timer(timer, 2400.0, 8.0)
    state = generator_switch_state(2400.0, time_above_threshold_s=timer)
    assert state.ready
    assert state.latched
    assert state.threshold_rpm == pytest.approx(GENERATOR_SWITCH_THRESHOLD_RPM, abs=1e-12)
    assert state.hold_time_s == pytest.approx(GENERATOR_SWITCH_HOLD_TIME_S, abs=1e-12)

    timer = update_generator_switch_timer(timer, 2300.0, 1.0)
    assert timer == pytest.approx(0.0, abs=1e-12)
    assert not generator_switch_state(2300.0, time_above_threshold_s=timer).ready


def test_generator_power_varies_without_premature_saturation() -> None:
    model = Stage13HybridEngineOutput()
    rpms = [3000.0, 3500.0, 4000.0, 4500.0, 5000.0, 5500.0, 5800.0]
    powers = []
    for rpm in rpms:
        engine_state = model.get_engine_state(rpm, 85.0 if rpm < 5000.0 else 100.0, 0.0, 15.0)
        health = get_health_state(engine_state, time_above_threshold_s=10.0)
        powers.append(health.generator_power_W)
        assert health.generator_power_W <= GENERATOR_AIRFRAME_MAX_POWER_W + 1e-9
        expected_voltage = min(
            max(
                GENERATOR_VOLTAGE_MIN_V
                + (GENERATOR_VOLTAGE_MAX_V - GENERATOR_VOLTAGE_MIN_V) * (rpm - GENERATOR_SWITCH_THRESHOLD_RPM)
                / (5800.0 - GENERATOR_SWITCH_THRESHOLD_RPM),
                GENERATOR_VOLTAGE_MIN_V,
            ),
            GENERATOR_VOLTAGE_MAX_V,
        )
        assert health.generator_power_W == pytest.approx(
            min(expected_voltage * health.generator_B_current_A, GENERATOR_AIRFRAME_MAX_POWER_W),
            rel=0.0,
            abs=1e-9,
        )

    assert any(power < GENERATOR_AIRFRAME_MAX_POWER_W - 1e-6 for power in powers)
    assert sum(abs(power - GENERATOR_AIRFRAME_MAX_POWER_W) < 1e-9 for power in powers) < len(powers)
    assert powers == sorted(powers)


def test_generator_a_current_does_not_drive_airframe_power() -> None:
    model = Stage13HybridEngineOutput()
    base = model.get_engine_state(4000.0, 85.0, 0.0, 15.0)
    health = get_health_state(base, time_above_threshold_s=10.0)
    assert health.generator_power_W == pytest.approx(
        min(health.generator_voltage_V * health.generator_B_current_A, GENERATOR_AIRFRAME_MAX_POWER_W),
        rel=0.0,
        abs=1e-9,
    )
    assert health.generator_A_current_A != pytest.approx(health.generator_B_current_A, rel=0.0, abs=1e-12)


def test_stage3_case_2151_remains_unchanged() -> None:
    model = Stage13HybridEngineOutput()
    state = model.get_engine_state(3000.0, 56.5, 0.0, 15.0)
    assert state.power_kW == pytest.approx(15.36454167, abs=1e-8)
    assert state.torque_Nm == pytest.approx(48.90685510, abs=1e-8)
    assert state.fuelflow_kgh == pytest.approx(6.02, abs=1e-8)
    assert state.p_plenum_bar == pytest.approx(0.6256, abs=1e-8)
    assert state.t_plenum_K == pytest.approx(289.85, abs=1e-8)
