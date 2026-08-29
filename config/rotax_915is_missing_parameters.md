# Rotax 915 iS — Missing / Additional Parameters (Phase 1 — Step 0.2)

These parameters were requested for additional investigation but were not added to the primary 16-row CSV per instructions. They should be researched in detailed technical/installation/service documents (OEM technical datasheets, service manuals, installation manuals, or supplier data sheets).

Parameters to investigate
- manifold pressure limits
- manifold temperature
- boost pressure (control limits, wastegate behavior)
- fuel pressure (supply and rail pressures)
- oil pressure (normal operating range and limits)
- oil temperature (normal operating range and limits)
- coolant temperature (normal operating range and limits)
- critical altitude (manufacturer-declared service ceiling or max operating altitude for rated power)
- airflow (induction mass flow at rated conditions)
- fuel flow (fuel consumption maps, LPH/kW)
- plenum pressure (plenum pressure relations and sensor locations)
- plenum temperature
- fuel injection control (ECU mapping overview, sensor inputs used)
- turbocharger specifics (model, compressor/turbine maps, efficiency curves)
- wastegate control details (actuation type and setpoints)
- EGT ranges / sensor locations

For each parameter above the following information should be recorded when found:
- parameter
- why Cantera needs it
- whether Rotax provides it (document, section, page)
- possible source (installation manual, technical datasheet, supplier data sheet)
- status (TODO / FOUND / NOT FOUND)

Guidance
- Do not add these to config/rotax_915is_engine_parameters.csv until they are confirmed authoritative and if they are required by Cantera.
- Prioritize OEM technical datasheets and installation manuals for turbocharger and ECU details; service manuals for operating limits and pressures.

Prepared by: automated workspace update (supplied extractions used for primary CSV)
Date: 2026-08-28
