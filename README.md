# Rotax 915 iS Engine Physics Simulator

A hybrid physics/data-driven digital-twin and telemetry-generation
backend for the Rotax 915 iS engine.

The project generates structured engine telemetry for downstream fault
diagnosis, remaining useful life (RUL), health-index, trend-analysis,
and maintenance-recommendation ML systems.

> **Current status:** Phase 1 --- simulator backend and production
> dataset-generation pipeline --- is complete. The repository is
> intended to evolve as the ML and application layers are added.

## 1. Project Overview

The simulator uses a hybrid architecture rather than pretending that
every engine quantity is produced by a first-principles solver.

``` text
Rotax 915 iS calibrated performance data
                |
                v
      Reference / interpolation model
                |
                +---------------> Tier-1 engine outputs
                |                  power
                |                  torque
                |                  fuel flow
                |                  plenum pressure
                |                  plenum temperature
                |
                v
       Stage 4 health/telemetry layer
                |
                +-- thermal
                +-- lubrication
                +-- electrical
                +-- vibration
                +-- engine-state signals
                |
                v
          Stage 5 mission simulation
                |
                v
        Stage 6 healthy telemetry
                |
                v
        Stage 7 fault injection
                |
                v
        Master dataset builder
                |
                v
          ML-ready master data
```

The key principle is **provenance**: values are treated as
calibrated/reference data, physics-derived features, or documented
engineering proxies.

## 2. Engine Being Modelled

### Rotax 915 iS

The target is the Rotax 915 iS / 915 i A family.

The engineering reference used by the project establishes a
four-cylinder, horizontally opposed, four-stroke architecture.

  Parameter                                Value
  ----------------------- ----------------------
  Cylinders                                    4
  Arrangement               Horizontally opposed
  Cycle                                 4-stroke
  Bore                                     84 mm
  Stroke                                   61 mm
  Total displacement                   \~1.352 L
  Displacement/cylinder                 \~338 cc
  Compression ratio                        8.2:1

The detailed Cantera work began with a single-cylinder representation.
That physics layer is retained as supporting physics; production
engine-performance outputs are governed by calibrated Rotax performance
data.

## 3. Hybrid Model Architecture

### Tier 1 --- Calibrated production data

The Rotax performance-map CSV is the production authority for:

-   power
-   fuel flow
-   plenum/manifold pressure
-   plenum/manifold temperature

Torque is calculated consistently from power and rotational speed.

The performance deck is a scattered/incomplete grid, so the reference
model uses scattered-data interpolation and explicitly tracks
interpolation/extrapolation status.

### Tier 2 --- Physics-derived and engineering-proxy data

Cantera and engineering relationships provide supporting
quantities/features such as:

-   cylinder pressure/temperature behaviour
-   combustion-related features
-   thermal response
-   oil behaviour
-   electrical behaviour
-   vibration proxies
-   engine-state signals

Where authoritative dynamic equations are unavailable, the
implementation treats the relationship as a Tier-2 engineering proxy
rather than an OEM dynamic model.

## 4. Reference Performance Model

Main files:

``` text
rotax_reference_model_v2.py
rotax_915is_performance_map.csv
```

Primary lookup inputs:

``` text
RPM
Throttle %
Altitude
Ambient temperature / ISA temperature offset
```

Primary calibrated outputs:

``` text
power_kW
fuelflow_kgh
p_plenum_bar
t_plenum_K
```

The reference model handles ISA temperature and the source deck's
temperature-offset bands:

``` text
0 °C
+15 °C
+30 °C
+45 °C
```

Unsupported operating points are explicitly handled rather than silently
treated as authoritative extrapolation.

## 5. Engine Telemetry

### Operating and environment

-   altitude
-   throttle
-   RPM
-   mission phase
-   mission type
-   time
-   ambient temperature
-   ambient pressure

### Engine performance

-   power
-   torque
-   fuel flow
-   plenum pressure
-   plenum temperature

### Thermal

-   coolant temperature
-   EGT1--EGT4
-   EGT mean
-   EGT maximum
-   EGT minimum
-   EGT spread

### Lubrication

-   oil pressure
-   oil temperature

### Electrical

-   battery voltage
-   battery state of charge
-   generator A current
-   generator B current
-   generator voltage
-   generator power
-   generator switching state
-   generator threshold/hold-time information

The electrical layer follows the documented Type-A 12 V architecture and
includes the documented generator switching behaviour around 2400 RPM
with an 8-second hold and the 420 W airframe-side limit.

### Vibration

The project uses a simplified vibration proxy because an authoritative
Rotax 915 iS vibration-amplitude spectrum was not available.

Signals include:

-   vibration amplitude
-   vibration frequency
-   vibration 1x
-   vibration 2x
-   vibration 3x

Baseline 1x frequency is tied to rotational frequency:

``` text
vibration_frequency_Hz = RPM / 60
```

Higher-order components are engineering proxies.

## 6. Health and Operating Limits

Current health validation includes:

  Parameter               Current validation limit
  --------------------- --------------------------
  Coolant temperature               120 °C maximum
  EGT maximum                       950 °C maximum
  Oil temperature                 -20 °C to 130 °C
  Battery voltage                  9.0 V to 14.5 V
  Generator power               420 W system limit

EGT cylinder-to-cylinder spread is also tracked as a diagnostic feature.

These limits should not be confused with a claim that every parameter
has an OEM dynamic simulation equation.

## 7. Stage 5 --- Mission Simulation

Stage 5 is the mission-level simulation layer. It feeds time-varying
operating conditions into the engine model.

Current mission types:

``` text
1. NORMAL
2. HIGH_ALTITUDE
3. ENDURANCE
4. HOT_WEATHER
5. HIGH_POWER
6. RAPID_THROTTLE
```

Telemetry is generated on a 1-second timestep.

A mission can produce:

``` text
time
altitude
ambient conditions
throttle
RPM
power
torque
fuel flow
thermal state
oil state
electrical state
vibration state
validation/provenance fields
```

Mission rows are checked for identity and timestep consistency before
being written.

## 8. Stage 6 --- Healthy Dataset Generation

Generator:

``` text
generate_stage6_normal_dataset.py
```

The generator:

1.  Builds a Stage 5 mission.
2.  Runs the mission.
3.  Performs lightweight integrity checks.
4.  Writes the mission directly to CSV.
5.  Releases mission data from memory.
6.  Continues with the next mission.

This design avoids accumulating the entire telemetry dataset in RAM.

Engine and mission seeds are deterministic.

### Completed Phase-1 healthy dataset

``` text
250 healthy engines
x 6 mission types
= 1,500 mission runs
```

Completed source dataset:

``` text
1,924,149 rows
55 original telemetry/provenance columns
```

The master builder later expands healthy rows to the unified 68-column
schema.

## 9. Stage 7 --- Abnormal / Fault Dataset Generation

Generator:

``` text
generate_stage7_abnormal_dataset.py
```

Stage 5 remains unchanged for fault injection.

The flow is:

``` text
Stage 5 healthy mission
        |
        v
Stage 7 fault model
        |
        v
Faulted telemetry
        |
        v
Fault metadata
        |
        v
CSV
```

Active fault types:

``` text
1. misfire
2. cooling_degradation
3. lubrication_degradation
4. sensor_drift
5. fuel_pressure_deviation
```

Severity levels:

``` text
mild
moderate
severe
```

Therefore the active fault scenario space is:

``` text
5 fault types x 3 severity levels
```

The completed abnormal source dataset used in Phase 1 contains:

``` text
10 abnormal virtual engines
6 mission types
5 fault types
3 severity levels
1,197,069 rows
68 columns
```

## 10. Fault Model Behaviour

Main files:

``` text
engine_model/stage7_fault_config.py
engine_model/stage7_fault_models.py
```

### Misfire

Introduces a coherent combustion-related abnormal signature rather than
an arbitrary random sensor spike.

### Cooling degradation

Reduces cooling effectiveness according to severity and increases
thermal proxies as available thermal headroom is consumed.

### Lubrication degradation

Modifies oil-related behaviour according to fault severity and
progression.

### Sensor drift

Separates underlying truth from the measured signal:

``` text
true_sensor_value
measured_sensor_value
```

For a drift event:

``` text
true_sensor_value != measured_sensor_value
```

### Fuel-pressure deviation

Uses a dedicated fuel-pressure state. Healthy operation is maintained
around the validated normal pressure region; the fault model moves
pressure outside that region according to fault progression and
severity.

## 11. Fault Timing

Faults are active over mission windows rather than necessarily being
present for the complete mission.

The master data records:

``` text
fault_start_time_s
fault_end_time_s
fault_envelope
```

This provides ground truth for fault classification and later RUL
construction.

## 12. Master Dataset

Builder:

``` text
build_master_dataset.py
```

The production flow is:

``` text
Healthy dataset
      +
Abnormal dataset
      |
      v
Unified 68-column schema
      |
      v
Master dataset
```

### Engine ID strategy

Healthy source engines:

``` text
ENG_0001 -> ENG_0250
```

Abnormal source engines:

``` text
ENG_0001 -> ENG_0010
```

Before merging, abnormal engines are remapped to:

``` text
ENG_0251 -> ENG_0260
```

The merge is a row-wise append. It is not a relational join.

No telemetry rows are matched against one another and no deduplication
is performed.

## 13. Completed Master Dataset

Validated Phase-1 master dataset:

``` text
Rows:       3,121,218
Columns:    68
Engines:    260
File size:  ~2.70 GB
```

Composition:

``` text
Healthy:
ENG_0001 -> ENG_0250
1,924,149 rows

Abnormal:
ENG_0251 -> ENG_0260
1,197,069 rows
```

Fault classes:

``` text
healthy
cooling_degradation
fuel_pressure_deviation
lubrication_degradation
misfire
sensor_drift
```

Severity labels:

``` text
none
mild
moderate
severe
```

## 14. Master Dataset Schema

The final unified dataset contains exactly 68 columns.

### Fault metadata

``` text
engine_id
fault_present
fault_type
fault_category
fault_severity
fault_start_time_s
fault_end_time_s
fault_envelope
fuel_pressure_bar
limit_exceeded
limit_parameter
limit_value
true_sensor_value
measured_sensor_value
```

### Time / mission metadata

``` text
time_s
mission_id
mission_type
phase
random_seed
model_version
```

### Environment

``` text
altitude_ft
altitude_m
ambient_temperature_C
ambient_pressure_hPa
```

### Engine operating state

``` text
throttle_pct
rpm
power_kW
torque_Nm
fuelflow_kgh
p_plenum_bar
t_plenum_K
```

### Thermal

``` text
coolant_temp_C
EGT1_C
EGT2_C
EGT3_C
EGT4_C
EGT_mean_C
EGT_max_C
EGT_min_C
EGT_spread_C
```

### Lubrication

``` text
oil_pressure_bar
oil_temperature_C
```

### Electrical

``` text
battery_voltage_V
battery_soc_pct
generator_A_current_A
generator_B_current_A
generator_voltage_V
generator_power_W
generator_switch_ready
generator_switch_latched
generator_switch_threshold_rpm
generator_switch_hold_time_s
generator_time_above_threshold_s
```

### Vibration

``` text
vibration_amplitude
vibration_frequency_Hz
vibration_1x
vibration_2x
vibration_3x
```

### Validation / provenance

``` text
engine_state_valid
outside_calibrated_envelope
extrapolation_used
health_state_valid
mission_generated_values
stage3_values
stage3_validation_status
stage3_ambient_source
stage4_production_source
ambient_source
```

## 15. Important Label Semantics

### fault_present

``` text
False = healthy
True  = faulted
```

### fault_type

Healthy rows:

``` text
healthy
```

Faulted rows:

``` text
cooling_degradation
fuel_pressure_deviation
lubrication_degradation
misfire
sensor_drift
```

### fault_severity

Healthy rows:

``` text
none
```

Faulted rows:

``` text
mild
moderate
severe
```

### true_sensor_value / measured_sensor_value

These are primarily meaningful for sensor-drift scenarios.

## 16. ML Roadmap

The master dataset is the raw ML source dataset, not the final feature
matrix.

### Model 1 --- Fault Classifier

Target:

``` text
fault_type
```

Classes:

``` text
healthy
cooling_degradation
fuel_pressure_deviation
lubrication_degradation
misfire
sensor_drift
```

Recommended approach:

``` text
Gradient-boosted trees
```

Examples:

``` text
XGBoost
LightGBM
sklearn GradientBoostingClassifier
```

Input features will include instantaneous telemetry plus short
rolling-window statistics, typically using 5--10 second windows.

Direct fault metadata must not be used as input features because it
would leak the answer.

### Model 2 --- RUL Regressor

Target:

``` text
time remaining until the relevant failure/limit condition
```

Training should focus on progressive fault trajectories.

Healthy rows may use a defined RUL ceiling if that design is retained.

### Health Index

A health index can be calculated from normalized telemetry and weighted
parameter contributions.

### Trend Analysis

Rolling health-index slopes can be used to detect persistent
degradation.

### Maintenance Recommendations

Initial recommendations can be rule-based using health index, RUL, and
persistent limit exceedance.

## 17. Data Leakage Prevention

Because each engine generates many time-series rows, row-level random
train/test splitting is inappropriate.

The ML pipeline should split by:

``` text
engine_id
```

so that engines in training, validation, and test sets are distinct.

This prevents telemetry from the same virtual engine from appearing in
multiple splits.

## 18. Repository Structure

Important production files include:

``` text
Rotex915-Series-Engine-Physics-simulator/
|
+-- engine_model/
|   +-- stage1_*
|   +-- stage2_*
|   +-- stage3_*
|   +-- stage4_*
|   +-- stage5_*
|   +-- stage7_fault_config.py
|   +-- stage7_fault_models.py
|
+-- generate_stage6_normal_dataset.py
+-- generate_stage7_abnormal_dataset.py
+-- build_master_dataset.py
|
+-- rotax_reference_model_v2.py
+-- rotax_915is_performance_map.csv
|
+-- graphify-out/
|
+-- README.md
```

Generated multi-gigabyte CSV datasets should not normally be committed
to the GitHub source repository.

## 19. Running the Pipeline

### Generate healthy data

``` powershell
python .\generate_stage6_normal_dataset.py
```

### Generate abnormal data

``` powershell
python .\generate_stage7_abnormal_dataset.py
```

### Build the master dataset

``` powershell
python .uild_master_dataset.py
```

The generators are designed for large datasets and limited RAM by
writing completed missions/chunks to disk instead of holding the
complete dataset in memory.

## 20. Validation Philosophy

Validation covers:

-   reference-map lookup
-   interpolation behaviour
-   operating-envelope handling
-   timestep consistency
-   mission identity
-   finite telemetry values
-   documented operating limits
-   fault-label consistency
-   source-schema consistency
-   master row counts
-   engine-ID uniqueness
-   master column alignment

The completed Phase-1 merge validated:

``` text
3,121,218 expected rows
3,121,218 written rows
68 columns
260 unique engines
```

No source data was modified and no deduplication was performed.

## 21. Known Limitations

This is an engineering digital twin and synthetic telemetry generator,
not an OEM-certified engine simulator.

1.  Not every telemetry channel has an authoritative dynamic OEM model.
    Vibration amplitude, detailed EGT dynamics, detailed oil-pressure
    dynamics, and several thermal transients are simplified engineering
    proxies.
2.  Cantera is not the production authority for absolute engine power.
    Calibrated Rotax performance data provides production
    power/torque/fuel/boost outputs.
3.  Proprietary ECU and injector maps are not claimed.
4.  Fault models are synthetic and should not be represented as measured
    real-engine fault-test data.
5.  Millions of telemetry rows are not millions of independent engines.
    Engine-level validation is therefore essential.
6.  The completed Phase-1 master dataset reflects the current
    250-healthy / 10-abnormal configuration; generator counts are
    configurable and should be checked before reproducing or expanding
    the dataset.

## 22. Phase 1 Completion

Phase 1 established:

``` text
Validated Rotax reference model
        +
Hybrid engine/physics layer
        +
Mission simulation
        +
Healthy dataset generator
        +
Fault dataset generator
        +
Master dataset builder
        +
Validated ML source dataset
```

Current completed dataset:

``` text
3,121,218 rows
68 columns
260 virtual engines
6 mission types
5 fault types
3 fault severity levels
```

## 23. Next Phase

The next phase starts with ML data engineering, not immediate model
training:

``` text
master_dataset.csv
        |
        v
Schema audit
        |
        v
Feature / label separation
        |
        v
Remove leakage-prone metadata
        |
        v
Sensor feature selection
        |
        v
5–10 second rolling features
        |
        v
Engine-level train/validation/test split
        |
        v
Fault classifier
        |
        v
RUL regressor
        |
        v
Health index
        |
        v
Trend analysis
        |
        v
Maintenance recommendation layer
```

## 24. Engineering Principle

> **Calibrate where authoritative data exists.\
> Model physics where physics is useful.\
> Use engineering proxies where authoritative dynamics do not exist.\
> Label synthetic data honestly.\
> Never confuse synthetic telemetry with measured engine data.**

This README is a Phase-1 snapshot and should be updated as the ML,
inference, visualization, and application layers are developed.
