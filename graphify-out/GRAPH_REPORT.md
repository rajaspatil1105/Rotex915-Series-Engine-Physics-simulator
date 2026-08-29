# Graph Report - rotex data  (2026-08-28)

## Corpus Check
- 41 files · ~56,218 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 437 nodes · 935 edges · 23 communities (20 shown, 3 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 68 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- stage1_3_fuel_metered_combustion.py
- crank_angle
- RotaxReferenceModel
- stage4_health_validation.py
- Stage13HybridEngineOutput
- stage1_2_func1_diagnostic.py
- stage2_engine_state_smoke_validation.py
- stage1_2_closed_reactor_compression_test.py
- stage1_2_intake_trapping_diagnostic.py
- stage1_2_motoring_sealed_test.py
- stage1_2_na_baseline.py
- NormalMissionGenerator
- stage1_2_closed_reactor_wall_test.py
- stage1_2_corrected_timing_diagnostic.py
- stage1_2_wall_only_verification.py
- wall_closed_compression_verified.py
- stage1_1_rotax_geometry.py
- stage5_telemetry_validation.py
- stage1_2_motoring_diagnostic.py
- rotax_915is_engine_parameters.md
- rotax_915is_missing_parameters.md
- copilot-instructions.md

## God Nodes (most connected - your core abstractions)
1. `Stage13HybridEngineOutput` - 57 edges
2. `NormalMissionGenerator` - 31 edges
3. `RotaxReferenceModel` - 28 edges
4. `get_health_state()` - 18 edges
5. `MissionConfig` - 18 edges
6. `get_engine_state()` - 15 edges
7. `generator_switch_state()` - 15 edges
8. `_advance_case()` - 14 edges
9. `main()` - 14 edges
10. `update_generator_switch_timer()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `run_for_outlet_p()` --calls--> `crank_angle()`  [INFERRED]
  engine_model/outlet_pressure_sweep.py → cantera_examples/ic_engine.py
- `test_complete_telemetry_schema_and_alignment()` --uses--> `Stage13HybridEngineOutput`  [INFERRED]
  test_stage5_telemetry.py → engine_model/stage1_3_hybrid_engine_output.py
- `test_complete_telemetry_schema_and_alignment()` --uses--> `NormalMissionGenerator`  [INFERRED]
  test_stage5_telemetry.py → engine_model/stage5_mission_generator.py
- `run_gas_exchange()` --calls--> `crank_angle()`  [INFERRED]
  engine_model/stage1_2_gas_exchange_ab_control.py → cantera_examples/ic_engine.py
- `run_gas_exchange()` --calls--> `crank_angle()`  [INFERRED]
  engine_model/stage1_2_gas_exchange_ab_test.py → cantera_examples/ic_engine.py

## Import Cycles
- None detected.

## Communities (23 total, 3 thin omitted)

### Community 0 - "stage1_3_fuel_metered_combustion.py"
Cohesion: 0.14
Nodes (34): main(), print_energy_accounting(), Stage 1.3 deficit-isolation diagnostic. This wrapper reuses the reconstructed…, _advance_case(), _build_case(), build_theta_schedule(), burn_fraction(), _burn_fraction_at_time() (+26 more)

### Community 1 - "crank_angle"
Cohesion: 0.09
Nodes (25): ca_ticks(), crank_angle(), piston_speed(), Diesel-type internal combustion engine simulation with gaseous fuel…, Helper function converts time to rounded crank angle., # TODO: Replace when dropping Numpy 1.x support, Convert time to crank angle, Approximate piston speed with sinusoidal velocity profile (+17 more)

### Community 2 - "RotaxReferenceModel"
Cohesion: 0.06
Nodes (36): fixture, calculate_metrics(), isa_pressure_bar(), isa_temp_c(), MetricResult, _nearest_band(), DataFrame, ndarray (+28 more)

### Community 3 - "stage4_health_validation.py"
Cohesion: 0.11
Nodes (36): EngineState, _clamp(), egt_spread_limit_from_fuel_flow(), _entry(), GeneratorSwitchState, get_health_state(), HealthState, _linear_interp() (+28 more)

### Community 4 - "Stage13HybridEngineOutput"
Cohesion: 0.08
Nodes (24): EngineOutputResult, main(), DataFrame, ndarray, Path, Read-only hybrid output layer for Stage 1.3. Absolute outputs come from the…, Deterministic ambient surrogate for 3-input production queries. The CSV remains…, Return the Stage 2 engine state on top of the calibrated CSV outputs. (+16 more)

### Community 5 - "stage1_2_func1_diagnostic.py"
Cohesion: 0.29
Nodes (8): build_coeff_function(), clearance_volume_from_cr(), cyl_volume_at_theta(), Stage 1.2 diagnostic (Func1 valve-coefficient test) Diagnostic-only copy of…, # NOTE: Previously set ReactorNet.max_time_step to a very small value to, Try to construct a Cantera Function object (Func1 or PiecewiseLinear) that…, run_func1_diagnostic(), swept_volume_per_cylinder()

### Community 6 - "stage2_engine_state_smoke_validation.py"
Cohesion: 0.14
Nodes (32): fuel_mass_mg_per_cylinder_cycle_from_fuelflow(), get_engine_state(), Stage 1.3 hybrid engine-output layer. Production rule: - The Rotax performance-…, Convert power to torque using the standard P = tau * omega relation., Simple downstream fuel-injection proxy derived from authoritative CSV fuel flow., Convenience wrapper for downstream Stage 2 callers., torque_nm_from_power_kw(), _assert_close() (+24 more)

### Community 7 - "stage1_2_closed_reactor_compression_test.py"
Cohesion: 0.46
Nodes (7): clearance_volume_from_cr(), cyl_volume_at_theta(), Closed-reactor compression test (diagnostic-only) Creates a single…, Recreate the reactor each timestep to preserve mass explicitly. This is slower…, run_closed_reactor(), run_closed_reactor_recreate(), swept_volume_per_cylinder()

### Community 8 - "stage1_2_intake_trapping_diagnostic.py"
Cohesion: 0.43
Nodes (7): clearance_volume_from_cr(), cyl_volume_at_theta(), is_valve_open(), main(), Stage 1.2: Intake Trapping Diagnostic (diagnostic-only) Objective: Determine…, run_intake_trapping_simulation(), swept_volume_per_cylinder()

### Community 9 - "stage1_2_motoring_sealed_test.py"
Cohesion: 0.43
Nodes (7): clearance_volume_from_cr(), cyl_volume_at_theta(), dVdtheta(), is_open_abs(), Motoring diagnostic with explicit sealed interval during compression…, run_sealed_test(), swept_volume_per_cylinder()

### Community 10 - "stage1_2_na_baseline.py"
Cohesion: 0.36
Nodes (5): clearance_volume_from_cr(), cyl_volume_at_theta(), Stage 1.2: Naturally-aspirated (NA) baseline single-cylinder model This script…, run_baseline(), swept_volume_per_cylinder()

### Community 11 - "NormalMissionGenerator"
Cohesion: 0.07
Nodes (57): isa_temp_c(), Approximate ISA temperature in degC below the tropopause., build_endurance_mission_config(), build_high_altitude_mission_config(), build_high_power_mission_config(), build_hot_weather_mission_config(), build_mission_config(), build_normal_mission_config() (+49 more)

### Community 12 - "stage1_2_closed_reactor_wall_test.py"
Cohesion: 0.48
Nodes (6): clearance_volume_from_cr(), cyl_volume_at_theta(), dVdtheta(), Piston-driven closed-reactor compression test using a Cantera Wall (diagnostic-…, run_wall_compression(), swept_volume_per_cylinder()

### Community 13 - "stage1_2_corrected_timing_diagnostic.py"
Cohesion: 0.48
Nodes (6): clearance_volume_from_cr(), cyl_volume_at_theta(), is_valve_open(), Stage 1.2: Corrected Valve Timing Motoring Diagnostic (diagnostic-only)…, run_corrected_timing_diagnostic(), swept_volume_per_cylinder()

### Community 14 - "stage1_2_wall_only_verification.py"
Cohesion: 0.43
Nodes (5): clearance_volume_from_cr(), cyl_volume_at_theta(), Stage 1.2: Wall-only Isolated Compression Verification (diagnostic-only)…, run_wall_only_verification(), swept_volume_per_cylinder()

### Community 15 - "wall_closed_compression_verified.py"
Cohesion: 0.48
Nodes (6): clearance_volume_from_cr(), cyl_volume_at_theta(), dVdtheta(), Closed-reactor piston-driven compression test (diagnostic-only) - One…, run_closed_wall_test(), swept_volume_per_cylinder()

### Community 16 - "stage1_1_rotax_geometry.py"
Cohesion: 0.47
Nodes (4): clearance_volume_from_cr(), print_provenance_and_checks(), Stage 1.1: Rotax 915 iS single-cylinder geometry smoke test This script adapts…, swept_volume_per_cylinder()

### Community 17 - "stage5_telemetry_validation.py"
Cohesion: 0.13
Nodes (28): generator_switch_state(), Advance the continuous above-threshold timer with an explicit timestep. The…, Simple switch logic for the documented >2400 RPM / 8 s generator behavior. The…, update_generator_switch_timer(), _validate_generator_switching(), Path, Stage 5 mission-to-telemetry simulation pipeline. This module orchestrates the…, Run the healthy Stage 5 pipeline and return complete telemetry rows. Stage 5… (+20 more)

### Community 18 - "stage1_2_motoring_diagnostic.py"
Cohesion: 0.53
Nodes (5): clearance_volume_from_cr(), cyl_volume_at_theta(), Stage 1.2 motoring / cylinder-sealing diagnostic (diagnostic-only) - Creates a…, run_motoring(), swept_volume_per_cylinder()

## Knowledge Gaps
- **4 isolated node(s):** `MissionTemplate`, `graphify`, `Rotax 915 iS — Engine Parameter Reference (Phase 1 — Step 0.2)`, `Rotax 915 iS — Missing / Additional Parameters (Phase 1 — Step 0.2)`
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Stage13HybridEngineOutput` connect `Stage13HybridEngineOutput` to `NormalMissionGenerator`, `stage5_telemetry_validation.py`, `stage4_health_validation.py`, `stage2_engine_state_smoke_validation.py`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Why does `NormalMissionGenerator` connect `NormalMissionGenerator` to `stage5_telemetry_validation.py`, `Stage13HybridEngineOutput`?**
  _High betweenness centrality (0.040) - this node is a cross-community bridge._
- **Why does `run_stage1_3_baseline()` connect `stage1_3_fuel_metered_combustion.py` to `stage2_engine_state_smoke_validation.py`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `Stage13HybridEngineOutput` (e.g. with `_validate_boost_sanity()` and `_validate_exact_csv_reproduction()`) actually correct?**
  _`Stage13HybridEngineOutput` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `NormalMissionGenerator` (e.g. with `Stage13HybridEngineOutput` and `MissionConfig`) actually correct?**
  _`NormalMissionGenerator` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `MissionConfig` (e.g. with `_build_schedule()` and `generate_normal_mission_rows()`) actually correct?**
  _`MissionConfig` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `MissionTemplate`, `graphify`, `Rotax 915 iS — Engine Parameter Reference (Phase 1 — Step 0.2)` to the rest of the system?**
  _4 weakly-connected nodes found - possible documentation gaps or missing edges._