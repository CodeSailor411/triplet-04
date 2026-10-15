# Integration decisions and assumptions

## Authority and scoring

- `guardian_layer/guardian` remains the source of truth for protocol/replay checks, HMAC verification, physical checks, cross-sensor correlation, reputation, and the Guardian trust score.
- The saved RF pipeline and `guardian_rf_features.py` remain the source of truth for model preprocessing and class probabilities.
- `compute_trust_score` was not changed. RF probability and label are attached to the evaluation record as advisory evidence and have an explicit numeric contribution of zero. No new score weights or cutoffs were introduced.
- Layer A rejects do not enter the buffer or call the RF. The dashboard/API records the failure and City Brain simulation blocks it.
- City Brain simulation blocks hard physical bounds, rate-of-change and stuck-health failures, as well as every non-trusted Guardian verdict. Statistical drift is a penalty in the existing scorer; the City Brain follows the score's final verdict when no hard check failed.
- Containment remains an in-memory simulation. Contained readings are retained for audit but skip further validation, correlation, and model inference, following the original Layer service behavior.

## Feature derivation and units

- The exact RF input order is `domain`, `value`, `z_score`, `rate_of_change`, `out_of_bounds`, `correlation_strength`, `incident_claimed`, `decayed_flags`, `baseline_dev_norm`, `flat_run_len`. The adapter does not pass unrelated fields.
- History-derived features follow `models/generate_dataset_v2.py`: the last six readings for z-score with a 0.5% range floor; absolute value delta per simulation tick; up to thirty previous readings for a median baseline; a flat run counted from prior identical values; configured normal range and max-rate metadata; actual correlation strength; and the existing decayed reputation count.
- Layer B's rate check remains per elapsed second. RF `rate_of_change` remains per tick, matching the training generator. A simulator tick is five seconds in the authored scenarios; no conversion is applied to the model's per-tick feature.
- Water's Guardian physical bounds are expressed in meters; the RF model is configured in centimeters. Explicit water readings in `cm` are converted to meters for the Layer's existing buffer and converted back to centimeters for model features. Meter readings are converted to centimeters only for the RF.
- Guardian's air-quality range is an AQI placeholder, while the RF domain is PM2.5 in `ug/m3`. There is no lossless AQI-to-PM2.5 conversion, so AQI readings remain eligible for deterministic Guardian logic but RF inference returns unavailable with a quantity-mismatch reason. PM2.5 values in the model's configured unit are eligible for RF.
- The one model result is derived only when a prior sensor reading exists for baseline/rate features. The initial reading is not assigned guessed history values; its model state is unavailable.
- `sensor_type` maps directly to the corresponding configured RF domain: `traffic_cam/traffic`, `water_level/water`, `power_load/power`, `air_quality/air_quality`, and `emergency_call/emergency`.

## Health checks and City Brain policy

- The original deterministic scorer has no stuck-sensor check even though the model documentation identifies stuck data as a sensor-health fault. The integration adds a Layer B health observation when the current value matches at least three prior consecutive values. It does not change the Guardian trust score or reputation; City Brain simulation blocks on this hard health gate. The threshold follows the model generator's `flat_run_len >= 3` convention.
- Out-of-bounds/rate and stuck checks are hard action gates. Statistical drift remains the existing scored anomaly check. This lets a genuine, strongly corroborated incident retain the original scorer's `trusted` outcome after its statistical penalty while still blocking impossible sensor values.
- ML availability is not an implicit trust signal. If the model is unavailable, deterministic Guardian scoring still produces its own result. The City Brain simulation reports that policy decision and never treats the absent probability as zero risk.
- A suspicious RF probability alone neither creates a destructive action nor changes the verdict. City Brain consumes the Guardian verdict and hard deterministic gates only.

## Simulation and runtime

- All scenario values are synthetic and marked as such. The simulator invokes the same in-process integration function as `/ingest`; scenario labels do not force a verdict.
- The Model unavailable scenario injects an unavailable inference state for its focus reading. It is a demonstration of safe failure handling and does not fabricate a prediction.
- Evaluation, reputation, and timeline state are in-memory for this local mock. Unique sensor IDs are generated for each simulator run so rerunning replay demonstrations is meaningful.
- FastAPI is the unified local entry point. The original MCP server remains mounted at `/mcp` and the React assets remain served by that process. The service binds only to loopback unless the source is explicitly changed.
- Serial RF inference (`n_jobs=1`) is set on the loaded estimator in memory because Windows worker pipes are blocked in restricted environments. The serialized artifact, estimator parameters other than parallelism, and predicted probabilities are unchanged.

## Existing model limitations retained

- Training data and scenario outputs are synthetic and do not establish real-world security performance.
- Gradual, adaptive, and corroborated spoofing can resemble genuine events and may be trusted by existing deterministic and learned logic.
- Replay attacks are outside the model's learnable feature set and remain a Layer A rejection.
- The model metadata says scikit-learn 1.9.1 for training; the serialized artifact and project requirements use scikit-learn 1.7.2. The artifact currently loads and model parity tests pass with 1.7.2. This provenance discrepancy is retained.
- Reference rules in the original inspector remain a report-derived comparison only. Unified Guardian verdicts use the real `guardian_layer/guardian/scoring.py` function.
