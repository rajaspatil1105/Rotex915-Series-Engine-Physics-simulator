"""Stage 4 realism layer.

Re-anchors the Tier-2 thermal proxies to documented Rotax limits and reported
field bands, and supplies first-order thermal lag plus per-instrument sensor
noise so that generated telemetry is dynamically and statistically plausible.

Reference bands
---------------
coolant     thermostat-regulated normal band 85-95 C, max 120 C
            (Rotax OM 915 i A limits; operator field reports)
oil temp    cruise 95-115 C, keep below 120 C, max 130 C, min 50 C for takeoff
            (Rotax OM 915 i A; EASA TCDS E.121 Issue 17)
EGT mean    cruise 730-790 C, max 950 C; RICH at full power so takeoff EGT is
            not higher than cruise (Rotax family field data)
EGT spread  about 110 C cruise, about 150 C climb (915 iS operator reports)
oil press   2.0-5.0 bar above 3500 rpm, min 0.8 bar below (EASA TCDS E.121)

Classification
--------------
TIER-2 PROXY, re-anchored to documented limits and reported field bands.
These are NOT OEM dynamic equations. Time constants are ASSUMED engineering
values typical of liquid-cooled piston engines. Sensor noise sigmas are
ASSUMED instrument-grade values and must be replaced if real instrument
specifications become available.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import exp

RATED_POWER_KW = 105.0

THERMOSTAT_SETPOINT_C = 88.0
COOLANT_MAX_C = 120.0
OIL_TEMP_MAX_C = 130.0
OIL_TEMP_MIN_C = -20.0
EGT_MAX_C = 950.0

# First-order thermal/mechanical lag time constants (seconds). ASSUMED.
TAU_S = {
    "coolant_temp_C": 60.0,
    "oil_temperature_C": 120.0,
    "oil_pressure_bar": 2.0,
    "EGT_mean_C": 3.0,
    "EGT_spread_C": 3.0,
    "p_plenum_bar": 0.5,
    "t_plenum_K": 8.0,
}

# Per-sample instrument noise, one standard deviation. ASSUMED.
SENSOR_SIGMA = {
    "rpm": 2.0,
    "EGT1_C": 0.75,
    "EGT2_C": 0.75,
    "EGT3_C": 0.75,
    "EGT4_C": 0.75,
    "EGT_mean_C": 0.5,
    "coolant_temp_C": 0.30,
    "oil_temperature_C": 0.25,
    "oil_pressure_bar": 0.02,
    "fuelflow_kgh": 0.158,
    "p_plenum_bar": 0.004,
    "t_plenum_K": 0.30,
    "battery_voltage_V": 0.02,
    "generator_voltage_V": 0.02,
    "vibration_amplitude": 0.004,
}

# Fixed per-engine installation bias, one standard deviation. ASSUMED.
SENSOR_BIAS_SIGMA = {
    "EGT1_C": 6.0,
    "EGT2_C": 6.0,
    "EGT3_C": 6.0,
    "EGT4_C": 6.0,
    "coolant_temp_C": 1.2,
    "oil_temperature_C": 1.0,
    "oil_pressure_bar": 0.05,
    "fuelflow_kgh": 0.25,
    "p_plenum_bar": 0.008,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def load_ratio(power_kW: float) -> float:
    return _clamp(float(power_kW) / RATED_POWER_KW, 0.0, 1.2)


def density_ratio(altitude_ft: float) -> float:
    """ISA density ratio, used as a cooling-airflow capacity scale."""
    h = max(0.0, float(altitude_ft))
    return max(0.20, (1.0 - 6.87535e-6 * h) ** 4.2561)


def coolant_equilibrium_C(power_kW: float, altitude_ft: float, ambient_C: float) -> float:
    """Thermostat-regulated coolant equilibrium.

    Below cooling saturation the thermostat holds the setpoint with only a
    small load-proportional rise. Once the heat load exceeds what the ram-air
    cooler can reject at that density and ambient temperature, coolant rises
    above the setpoint toward the 120 C limit.
    """
    q = load_ratio(power_kW)
    rise = 62.0 * q / max(0.45, density_ratio(altitude_ft) ** 0.5)
    regulated = THERMOSTAT_SETPOINT_C + 4.0 * q
    saturated = float(ambient_C) + rise
    return _clamp(max(regulated, saturated), OIL_TEMP_MIN_C, COOLANT_MAX_C)


def oil_temperature_equilibrium_C(coolant_C: float, power_kW: float) -> float:
    """Oil runs above coolant, with the offset growing under load."""
    q = load_ratio(power_kW)
    return _clamp(float(coolant_C) + 5.0 + 8.0 * q, OIL_TEMP_MIN_C, OIL_TEMP_MAX_C)


def egt_mean_equilibrium_C(power_kW: float, mat_C: float) -> float:
    """EGT rises with load, then falls back as the ECU enriches at high power."""
    q = load_ratio(power_kW)
    enrich = _clamp((q - 0.80) / 0.20, 0.0, 1.0)
    return _clamp(450.0 + 400.0 * q + 0.35 * float(mat_C) - 110.0 * enrich, 200.0, EGT_MAX_C)


def egt_spread_equilibrium_C(power_kW: float, spread_limit_C: float) -> float:
    """Anchored on reported field values: about 110 C cruise, 150 C climb."""
    q = load_ratio(power_kW)
    return _clamp(85.0 + 65.0 * q, 20.0, float(spread_limit_C))


@dataclass
class Lag:
    """Single-channel first-order lag. Initialises at the first target."""

    tau_s: float
    value: float | None = None

    def step(self, target: float, dt_s: float) -> float:
        target = float(target)
        if self.value is None or self.tau_s <= 0.0 or dt_s <= 0.0:
            self.value = target
            return self.value
        alpha = 1.0 - exp(-float(dt_s) / float(self.tau_s))
        self.value += alpha * (target - self.value)
        return self.value


@dataclass
class ThermalLagBank:
    """Applies TAU_S lag to every channel that has a time constant."""

    lags: dict[str, Lag] = field(default_factory=dict)

    def apply(self, values: dict[str, float], dt_s: float) -> dict[str, float]:
        out = dict(values)
        for name, tau in TAU_S.items():
            if name not in out:
                continue
            if name not in self.lags:
                self.lags[name] = Lag(tau)
            out[name] = self.lags[name].step(out[name], dt_s)
        return out

    def reset(self) -> None:
        self.lags.clear()


class SensorNoise:
    """Deterministic per-engine bias plus per-sample Gaussian noise.

    Seeded from the engine identifier so a given virtual engine keeps the same
    installation bias for its whole life, which is what a real airframe does.
    """

    def __init__(self, engine_seed: int) -> None:
        self._rng = random.Random(int(engine_seed) * 7919 + 13)
        bias_rng = random.Random(int(engine_seed) * 104729 + 7)
        self.bias = {k: bias_rng.gauss(0.0, s) for k, s in SENSOR_BIAS_SIGMA.items()}

    def measure(self, values: dict[str, float]) -> dict[str, float]:
        """Return measured values; callers should keep the true values too."""
        out = dict(values)
        for name, sigma in SENSOR_SIGMA.items():
            if name not in out:
                continue
            v = float(out[name]) + self.bias.get(name, 0.0)
            out[name] = v + self._rng.gauss(0.0, sigma)
        return out


def _selftest() -> int:
    cases = (
        ("cruise 80pct 6000ft ISA+10", 67.8, 6000.0, 10.0, 40.0),
        ("climb 95pct 6000ft ISA+10", 85.4, 6000.0, 10.0, 55.0),
        ("takeoff 100pct sea level", 104.4, 0.0, 15.0, 60.0),
        ("hot day takeoff ISA+30", 104.4, 0.0, 45.0, 85.0),
        ("descent 40pct 4000ft", 40.0, 4000.0, 12.0, 25.0),
    )
    print("%-30s %8s %8s %8s" % ("case", "coolant", "oil", "EGT"))
    for name, kw, alt, amb, mat in cases:
        c = coolant_equilibrium_C(kw, alt, amb)
        o = oil_temperature_equilibrium_C(c, kw)
        e = egt_mean_equilibrium_C(kw, mat)
        print("%-30s %8.1f %8.1f %8.1f" % (name, c, o, e))
    lag = Lag(TAU_S["coolant_temp_C"])
    lag.step(88.0, 1.0)
    t = 0.0
    while lag.value < 88.0 + 0.63 * (100.0 - 88.0):
        lag.step(100.0, 1.0)
        t += 1.0
    print("\ncoolant 63pct step response reached at %.0f s (tau = %.0f s)" % (t, TAU_S["coolant_temp_C"]))
    n = SensorNoise(engine_seed=42)
    m = n.measure({"coolant_temp_C": 88.0, "oil_pressure_bar": 3.2, "rpm": 5000.0})
    print("noisy sample:", {k: round(v, 3) for k, v in m.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
