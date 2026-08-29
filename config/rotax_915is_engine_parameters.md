# Rotax 915 iS — Engine Parameter Reference (Phase 1 — Step 0.2)

Source used for verified values
- ROTAX Operators Manual for ROTAX engine type 915 i A Series (OM-915 i A), Part No. 898851, Revision: Rev. 2, Date: 01 Dec 2020 — Official BRP‑Rotax manufacturer documentation.

Purpose
- Populate a source-traceable reference table of 16 engine parameters required for later Cantera model configuration. Values below were supplied from the official Rotax Operators Manual (OM-915 i A Rev.2) as provided to the project. No values were inferred or fabricated.

Verification summary
- The workspace was updated using the supplied authoritative extractions from OM-915 i A Rev.2.
- All 16 requested parameters now have rows in config/rotax_915is_engine_parameters.csv and populated values where the manual provided them.

Verified parameters (sourced from OM-915 i A Rev.2)
- Number of cylinders: 4 (cylinders)
  - Source: OM 915 i A Rev.2 (OM-915 i A, Part No. 898851), §7.1.1, manual page 7-2
  - Confidence: HIGH
  - Note: "4-stroke-, 4 cylinder flat engine" (citation recorded in CSV)

- Cylinder arrangement: Flat / horizontally opposed
  - Source: OM 915 i A Rev.2, §§1.6 & 7.1.1, manual pages 1-15 and 7-2
  - Confidence: HIGH

- Engine cycle: 4-stroke
  - Source: OM 915 i A Rev.2, §7.1.1, manual page 7-2
  - Confidence: HIGH

- Bore: 84 mm
  - Source: OM 915 i A Rev.2, §7.1.2, manual page 7-2
  - Confidence: HIGH

- Stroke: 61 mm
  - Source: OM 915 i A Rev.2, §7.1.2, manual page 7-2
  - Confidence: HIGH

- Displacement: 1352 cm3
  - Source: OM 915 i A Rev.2, §7.1.2, manual page 7-2
  - Confidence: HIGH

- Compression ratio: 8.2:1
  - Source: OM 915 i A Rev.2, §7.1.2, manual page 7-2
  - Confidence: HIGH

- Maximum takeoff RPM: 5800 rpm (max. 5 minutes)
  - Source: OM 915 i A Rev.2, §2.1, manual page 2-2
  - Confidence: HIGH

- Maximum continuous RPM: 5500 rpm
  - Source: OM 915 i A Rev.2, §2.1, manual page 2-2
  - Confidence: HIGH

- Takeoff power: 104 kW (at 5800 rpm)
  - Source: OM 915 i A Rev.2, §2.1, manual page 2-2
  - Confidence: HIGH

- Continuous power: 99 kW (at 5500 rpm, without governor)
  - Source: OM 915 i A Rev.2, §2.1, manual page 2-2
  - Confidence: HIGH

- Fuel type: MOGAS and AVGAS 100LL (EN 228 Super / EN 228 Super Plus; AVGAS 100LL (ASTM D910); 915 iSc/iS minimum RON 95; ASTM D4814 fuel minimum AKI 91)
  - Source: OM 915 i A Rev.2, §2.3, manual pages 2-6 and 2-7
  - Confidence: HIGH

- Fuel injection type: Electronic fuel injection, ECU controlled
  - Source: OM 915 i A Rev.2, §7.5.3, manual page 7-12
  - Confidence: HIGH

- Turbocharger type: Turbocharged; exact turbocharger model/type not specified in this Operators Manual
  - Source: OM 915 i A Rev.2, §§7.1.1 and 7.6, manual pages 7-2 and 7-13/14
  - Confidence: HIGH (for turbocharged presence); Model unspecified in the manual
  - Note: Do not invent turbocharger model — further documentation (technical datasheet or installation manual) required.

- Intercooler: Yes
  - Source: OM 915 i A Rev.2, §§7.1.3 and 7.6, manual pages 7-3 and 7-13/14
  - Confidence: HIGH

- Cooling system: Liquid-cooled cylinder heads with ram-air-cooled cylinders; closed coolant circuit with expansion tank
  - Source: OM 915 i A Rev.2, §§7.1.1 and 7.2, manual pages 7-2 and 7-5
  - Confidence: HIGH

Parameters not supplied by OM-915 i A Rev.2 (none — the manual provided values for all 16 requested parameters as supplied):
- None remaining; all 16 parameters have been populated from the supplied manual extractions.

Additional engineering parameters inspected (to be recorded in config/rotax_915is_missing_parameters.md)
- manifold pressure limits
- manifold temperature
- boost pressure
- fuel pressure
- oil pressure
- oil temperature
- coolant temperature
- critical altitude
- airflow
- fuel flow
- plenum pressure
- plenum temperature
- fuel injection control details
- turbocharger specifics (model, maps)
- wastegate control details
- EGT (exhaust gas temperature) operating ranges

(Per instructions, these additional parameters are not added to the 16-row CSV; they will be collected and tracked in config/rotax_915is_missing_parameters.md.)

Validation checklist (completed)
- 16 parameter rows exist: Yes
- No verified parameter remains NOT FOUND unless the supplied source explicitly does not provide it: Yes — all 16 populated from provided manual extractions
- Every populated value has an exact source citation (document, section, page): Yes — citations recorded in the CSV
- Every populated value has confidence HIGH: Yes
- No value was silently inferred: Confirmed
- Official performance CSV (rotax_915is_performance_map.csv) unchanged: Confirmed
- Reported any parameter whose wording differs from requested parameter: None — all wording matched or was explicitly noted (e.g., turbocharger model unspecified)

Files created/modified in this step
- Modified: config/rotax_915is_engine_parameters.csv (populated with verified values and citations)
- Modified: config/rotax_915is_engine_parameters.md (updated to record verified parameters and citations)
- Created: config/rotax_915is_missing_parameters.md (placeholder listing additional parameters to research)

Exact document used
- ROTAX Operators Manual for ROTAX engine type 915 i A Series (OM-915 i A), Part No. 898851, Revision: Rev. 2, Date: 01 Dec 2020
  - Sections and pages cited in the CSV for each parameter (examples included in CSV notes)

Ambiguities and unresolved items
- Turbocharger: the Operators Manual confirms the engine is turbocharged but does not specify the exact turbocharger model or compressor/turbine maps — further supplier/installation documentation required.
- No other ambiguities found in the supplied manual extracts for the 16 requested parameters.

Step 0.2 completion status
- Based on the supplied authoritative extractions from OM-915 i A Rev.2 and per the stated rules, Step 0.2 is COMPLETE: all 16 parameters have been sourced with exact citations, confidence levels, and notes. No values were fabricated.

Prepared by: automated update using supplied verified extractions
Date: 2026-08-28
