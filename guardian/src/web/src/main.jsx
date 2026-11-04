import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, AlertTriangle, ArrowUpRight, Check, ChevronDown, CircleHelp, Clock3, Cpu, Fingerprint, Gauge, Layers3, Network, Play, RotateCcw, Shield, ShieldAlert, ShieldCheck, Sparkles, Waves, Zap } from 'lucide-react';
import './style.css';

const PROTOCOL_VERSION = '2026-07-28';
const INPUTS = [
  ['z_score', 'Z-score', '0.1'],
  ['rate_of_change', 'Rate of change / tick', '0.1'],
  ['out_of_bounds', 'Out of bounds', 'flag'],
  ['correlation_strength', 'Corroboration', '0.01'],
  ['incident_claimed', 'Incident claimed', 'flag'],
  ['decayed_flags', 'Decayed flags', '0.1'],
  ['baseline_dev_norm', 'Baseline deviation', '0.01'],
  ['flat_run_len', 'Flat run length', '1'],
];
const PROFILE = {
  Normal: { value_fraction: 0.42, z_score: 0.3, rate_fraction: 0.8 / 6, out_of_bounds: 0, correlation_strength: 1, incident_claimed: 0, decayed_flags: 0, baseline_dev_norm: 0.01, flat_run_len: 0 },
  'Fake flood': { value_fraction: 1.6, z_score: 45, rate_fraction: 140 / 6, out_of_bounds: 1, correlation_strength: 0, incident_claimed: 1, decayed_flags: 0, baseline_dev_norm: 1.4, flat_run_len: 0 },
  'Smart spoof': { value_fraction: 0.72, z_score: 8, rate_fraction: 42 / 6, out_of_bounds: 0, correlation_strength: 0, incident_claimed: 1, decayed_flags: 0, baseline_dev_norm: 0.42, flat_run_len: 0 },
  'Stuck sensor': { value_fraction: 0.383, z_score: 0, rate_fraction: 0, out_of_bounds: 0, correlation_strength: 1, incident_claimed: 0, decayed_flags: 0, baseline_dev_norm: 0, flat_run_len: 5 },
  'Adaptive ramp': { value_fraction: 0.58, z_score: 1.4, rate_fraction: 4.5 / 6, out_of_bounds: 0, correlation_strength: 0.85, incident_claimed: 1, decayed_flags: 0, baseline_dev_norm: 0.35, flat_run_len: 0 },
};

function fromProfile(name, domain, domains) {
  const spec = PROFILE[name];
  const range = domains[domain];
  return {
    domain,
    value: range.lo + spec.value_fraction * (range.hi - range.lo),
    z_score: spec.z_score,
    rate_of_change: spec.rate_fraction * range.max_rate,
    out_of_bounds: spec.out_of_bounds,
    correlation_strength: spec.correlation_strength,
    incident_claimed: spec.incident_claimed,
    decayed_flags: spec.decayed_flags,
    baseline_dev_norm: spec.baseline_dev_norm,
    flat_run_len: spec.flat_run_len,
  };
}

function sameReading(a, b) {
  if (!a || !b || a.domain !== b.domain) return false;
  const fields = ['value', 'z_score', 'rate_of_change', 'out_of_bounds', 'correlation_strength', 'incident_claimed', 'decayed_flags', 'baseline_dev_norm', 'flat_run_len'];
  return fields.every((key) => Number.isFinite(Number(a[key])) && Math.abs(Number(a[key]) - Number(b[key])) < 1e-8);
}

function classifyReference(record, capabilities) {
  if (!record || !capabilities) return null;
  const domain = capabilities.domains[record.domain];
  const weights = capabilities.reference_rules;
  const reasons = [];
  let score = 1;
  const penalize = (code, amount) => { score -= amount; reasons.push({ code, amount }); };
  if (record.out_of_bounds) penalize('out_of_bounds', weights.out_of_bounds);
  if (record.rate_of_change > domain.max_rate) penalize('rate_of_change_exceeded', weights.rate_of_change_exceeded);
  if (Math.abs(record.z_score) > 3) penalize('statistical_drift_outlier', weights.statistical_drift_outlier);
  if (record.incident_claimed) {
    if (record.correlation_strength < weights.weak_correlation_min) penalize('no_correlated_evidence', weights.no_correlated_evidence);
    else if (record.correlation_strength <= weights.correlation_satisfied_min) penalize('weak_correlated_evidence', weights.weak_correlated_evidence);
  }
  const priorPenalty = Math.min(record.decayed_flags * weights.prior_flag_per_count, weights.prior_flag_cap);
  if (priorPenalty > 0) penalize('prior_flags_on_record', priorPenalty);
  score = Math.max(0, Math.min(1, score));
  const cutoffs = capabilities.trust_cutoffs;
  const state = score >= cutoffs.trusted_min ? 'Trusted' : score >= cutoffs.degraded_min ? 'Degraded' : 'Untrusted';
  return { score, state, reasons };
}

const STATE_COPY = {
  Trusted: { title: 'Below alert threshold', detail: "The model's trusted class · advisory label only", icon: ShieldCheck, tone: 'low' },
  Uncertain: { title: 'Near threshold — ignored by scoring', detail: 'The advisory signal is within the model uncertainty band.', icon: CircleHelp, tone: 'uncertain' },
  Suspicious: { title: 'Suspicious pattern', detail: 'The advisory signal is above the model uncertainty band.', icon: ShieldAlert, tone: 'high' },
  Unavailable: { title: 'Model unavailable — Guardian rules decide', detail: 'No probability was produced for this reading.', icon: AlertTriangle, tone: 'unavailable' },
};

function App() {
  const [capabilities, setCapabilities] = useState(null);
  const [connection, setConnection] = useState('connecting');
  const [form, setForm] = useState(null);
  const [result, setResult] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [message, setMessage] = useState('');
  const [demo, setDemo] = useState({ catalog: null, overview: null, events: [], loading: true });
  const [scenarioId, setScenarioId] = useState('genuine_fire');
  const [sensorType, setSensorType] = useState('water_level');
  const [customValue, setCustomValue] = useState('62');
  const [runResult, setRunResult] = useState(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [runningScenario, setRunningScenario] = useState(false);
  const [demoError, setDemoError] = useState('');

  const refreshDemo = async () => {
    const [overviewResponse, catalogResponse, timelineResponse] = await Promise.all([
      fetch('/api/overview'), fetch('/api/scenarios'), fetch('/api/timeline?limit=80'),
    ]);
    if (!overviewResponse.ok || !catalogResponse.ok || !timelineResponse.ok) throw new Error('Unified dashboard API is unavailable.');
    const [overviewData, catalogData, timelineData] = await Promise.all([
      overviewResponse.json(), catalogResponse.json(), timelineResponse.json(),
    ]);
    setDemo({ catalog: catalogData, overview: overviewData, events: timelineData.events || [], loading: false });
    if (catalogData.sensors?.length && !catalogData.sensors.some((item) => item.sensor_type === sensorType)) {
      setSensorType(catalogData.sensors[0].sensor_type);
    }
  };

  useEffect(() => {
    let cancelled = false;
    async function loadDashboard() {
      try {
        const [overviewResponse, catalogResponse, timelineResponse] = await Promise.all([
          fetch('/api/overview'), fetch('/api/scenarios'), fetch('/api/timeline?limit=80'),
        ]);
        if (!overviewResponse.ok || !catalogResponse.ok || !timelineResponse.ok) throw new Error('Unified dashboard API is unavailable.');
        const [overviewData, catalogData, timelineData] = await Promise.all([
          overviewResponse.json(), catalogResponse.json(), timelineResponse.json(),
        ]);
        if (!cancelled) setDemo({ catalog: catalogData, overview: overviewData, events: timelineData.events || [], loading: false });
      } catch (error) {
        if (!cancelled) setDemo((current) => ({ ...current, loading: false, error: error.message }));
      }
    }
    loadDashboard();
    return () => { cancelled = true; };
  }, []);

  const runDemoScenario = async () => {
    setRunningScenario(true);
    setDemoError('');
    try {
      const body = scenarioId === 'custom'
        ? { sensor_type: sensorType, value: customValue === '' ? null : Number(customValue) }
        : {};
      const response = await fetch(`/api/simulations/${scenarioId}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Scenario could not be run.');
      setRunResult(data);
      const focus = data.evaluations.findIndex((item) => item.reading_id === data.focus_reading_id);
      setStepIndex(Math.max(0, focus));
      await refreshDemo();
    } catch (error) {
      setDemoError(error.message);
    } finally {
      setRunningScenario(false);
    }
  };

  const resetDemo = async () => {
    setDemoError('');
    try {
      const response = await fetch('/api/reset', { method: 'POST' });
      if (!response.ok) throw new Error('Dashboard reset failed.');
      setRunResult(null);
      await refreshDemo();
    } catch (error) {
      setDemoError(error.message);
    }
  };

  useEffect(() => {
    let cancelled = false;
    async function connect() {
      try {
        const response = await fetch('/api/capabilities');
        if (!response.ok) throw new Error('Guardian capability endpoint is unavailable.');
        const caps = await response.json();
        if (cancelled) return;
        setCapabilities(caps);
        if (caps.model_available) {
          setConnection('ready');
          setForm(fromProfile('Normal', 'water', caps.domains));
        } else {
          setConnection('unavailable');
          setMessage('Model unavailable — Guardian rules decide.');
        }
      } catch (error) {
        if (!cancelled) {
          setConnection('unavailable');
          setResult(null);
          setMessage(error.message || 'Model unavailable — Guardian rules decide.');
        }
      }
    }
    connect();
    return () => { cancelled = true; };
  }, []);

  const domain = form && capabilities?.domains[form.domain];
  const activePreset = useMemo(() => {
    if (!form || !capabilities) return 'Custom';
    return Object.keys(PROFILE).find((name) => sameReading(form, fromProfile(name, form.domain, capabilities.domains))) || 'Custom';
  }, [form, capabilities]);
  const reference = useMemo(() => classifyReference(form, capabilities), [form, capabilities]);
  const requiredFieldsValid = form && Object.entries(form).every(([key, value]) => key === 'value' || key === 'domain' || (typeof value === 'number' && Number.isFinite(value)));

  const changeField = (key, raw) => {
    setForm((current) => ({ ...current, [key]: key === 'domain' ? raw : raw === '' ? null : Number(raw) }));
    setResult(null);
    setMessage('');
  };

  const changeDomain = (nextDomain) => {
    if (activePreset !== 'Custom') setForm(fromProfile(activePreset, nextDomain, capabilities.domains));
    else setForm((current) => ({ ...current, domain: nextDomain }));
    setResult(null);
  };

  const evaluate = async () => {
    if (!form || !requiredFieldsValid) return;
    setEvaluating(true);
    setMessage('');
    try {
      const response = await fetch('/api/advisory', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form),
      });
      const evaluated = await response.json();
      if (!response.ok) throw new Error(evaluated.detail || 'Model evaluation failed.');
      setResult({ ...evaluated, evaluatedAt: new Date() });
      if (evaluated.ml_label === 'Unavailable') setMessage('Model unavailable — Guardian rules decide.');
    } catch (error) {
      setResult(null);
      setConnection('unavailable');
      setMessage('Model unavailable — Guardian rules decide.');
    } finally {
      setEvaluating(false);
    }
  };

  const reset = () => {
    if (capabilities?.domains.water) setForm(fromProfile('Normal', 'water', capabilities.domains));
    setResult(null);
    setMessage('');
  };
  const stateInfo = result ? STATE_COPY[result.ml_label] : null;
  const StateIcon = stateInfo?.icon;
  const sliderMax = domain ? Math.max(domain.hi, domain.hi * 1.6) : 0;
  const sliderPosition = domain && form?.value != null ? Math.max(0, Math.min(100, (form.value / sliderMax) * 100)) : 0;

  return (
    <div className="app-shell">
      <aside className="rail" aria-label="Guardian playground">
        <div className="brand-mark" aria-hidden="true"><Shield size={21} /></div>
        <div className="rail-line" />
        <div className="rail-button active" aria-label="Reading inspector"><Activity size={18} /></div>
        <div className="rail-spacer" />
        <div className="avatar" title="Guardian team">9</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="crumb"><span>Guardian</span><span className="crumb-slash">/</span><b>Model lab</b></div>
          <div className="top-right">
            <div className="live-status" role="status"><span className={`status-dot ${connection === 'ready' ? '' : 'off'}`} />
              {connection === 'connecting' ? 'Connecting to Guardian API' : connection === 'ready' ? 'Local model ready' : 'Model unavailable'}
            </div>
            <div className="top-divider" />
            <span className="protocol-chip">MCP {capabilities?.protocol_version || PROTOCOL_VERSION}</span>
          </div>
        </header>

        <div className="content">
          <section className="hero">
            <div className="hero-copy">
              <div className="eyebrow"><span className="eyebrow-dot" /> GUARDIAN INTELLIGENCE <span className="version">{capabilities?.model_version || '—'}</span></div>
              <h1>Trust, before action.</h1>
              <p>Explore how the Guardian's advisory model evaluates a sensor reading. Adjust the signal, inspect the inputs and compare the advisory against a reference rule set.</p>
              <div className="hero-tags"><span><Fingerprint size={14} /> Advisory only</span><span><Cpu size={14} /> Random Forest</span><span><Layers3 size={14} /> Synthetic model</span></div>
            </div>
            <div className="hero-art" aria-hidden="true">
              <div className="orbit orbit-one" /><div className="orbit orbit-two" />
              <div className="hero-core"><ShieldCheck size={32} /></div>
              <div className="orbit-node n1" /><div className="orbit-node n2" /><div className="orbit-node n3" />
              <div className="signal s1"><span>MCP</span><small>local tool</small></div>
              <div className="signal s2"><span>MODEL</span><small>shadow signal</small></div>
            </div>
          </section>

          <section className="demo-dashboard" aria-labelledby="demo-title">
            <div className="demo-header">
              <div><span className="section-kicker">LIVE PIPELINE</span><h2 id="demo-title">End-to-end demonstration</h2><p>Simulator readings pass through Guardian security, validation, correlation, the saved model, scoring, and a simulated City Brain gate.</p></div>
              <div className="demo-health" role="status"><span className={`status-dot ${(demo.overview?.guardian_status === 'ready' || connection === 'ready') ? '' : 'off'}`} />Guardian {demo.overview?.guardian_status || (connection === 'connecting' || demo.loading ? 'loading' : connection === 'ready' ? 'ready' : 'unavailable')}<span className="demo-health-sep">·</span>RF {capabilities ? (capabilities.model_available ? 'available' : 'unavailable') : (connection === 'connecting' || demo.loading ? 'loading' : 'unavailable')}</div>
            </div>

            <div className="demo-metrics" aria-label="System overview">
              {[
                ['Processed readings', demo.overview?.processed_readings],
                ['Trusted', demo.overview?.trusted_readings],
                ['Suspicious', demo.overview?.suspicious_readings],
                ['Rejected', demo.overview?.rejected_readings],
                ['Active incidents', demo.overview?.active_simulated_incidents?.length],
              ].map(([label, count]) => <div className="demo-metric" key={label}><span>{label}</span><b>{count ?? (demo.loading ? '…' : '—')}</b></div>)}
            </div>

            <div className="demo-controls-grid">
              <div className="demo-controls">
                <div className="demo-control-heading"><div><span className="section-kicker">SENSOR / TWIN SIMULATOR</span><h3>Choose a scenario</h3></div><button type="button" className="reset-button" onClick={resetDemo} disabled={runningScenario}><RotateCcw size={13} /> Reset</button></div>
                <div className="scenario-buttons" aria-label="End-to-end scenarios">
                  {(demo.catalog?.scenarios || []).map((item) => <button key={item.id} type="button" aria-pressed={scenarioId === item.id} className={scenarioId === item.id ? 'selected' : ''} onClick={() => setScenarioId(item.id)}>{item.name}</button>)}
                </div>
                <div className="simulator-inputs">
                  <label>Sensor / domain<select aria-label="Sensor for simulator" value={sensorType} onChange={(event) => {
                    const nextType = event.target.value;
                    setSensorType(nextType);
                    const spec = demo.catalog?.sensors?.find((item) => item.sensor_type === nextType);
                    if (spec) setCustomValue(String(spec.default_value));
                  }}>{(demo.catalog?.sensors || []).map((item) => <option key={item.sensor_type} value={item.sensor_type}>{item.domain.replaceAll('_', ' ')} · {item.sensor_type}</option>)}</select></label>
                  {scenarioId === 'custom' && <label>Observed value<input aria-label="Custom simulator value" type="number" step="any" value={customValue} onChange={(event) => setCustomValue(event.target.value)} /></label>}
                  <button className="run-button" type="button" onClick={runDemoScenario} disabled={runningScenario || demo.loading} aria-label="Run simulation"><span>{runningScenario ? 'Running…' : 'Run scenario'}</span>{runningScenario ? <span className="spinner" /> : <Play size={15} fill="currentColor" />}</button>
                </div>
                {scenarioId === 'custom' && <p className="simulator-note">Custom values are synthetic. Units follow the selected sensor's configured domain.</p>}
                {demoError && <div className="error-message" role="alert"><AlertTriangle size={15} />{demoError}</div>}
              </div>

              <div className="demo-outcome" aria-live="polite">
                <div className="demo-control-heading"><div><span className="section-kicker">CURRENT EVALUATION</span><h3>{runResult ? runResult.description : 'Pipeline result'}</h3></div>{runResult && <span className="synthetic-chip">SYNTHETIC</span>}</div>
                {runResult ? (() => {
                  const item = runResult.evaluations[stepIndex] || runResult.focus_evaluation;
                  const guardian = item.guardian;
                  const ml = item.ml;
                  const layerState = (state) => state === 'passed' ? 'passed' : state === 'failed' ? 'failed' : state === 'uncertain' ? 'uncertain' : state === 'not_applicable' || state === 'skipped' ? 'skipped' : 'unavailable';
                  return <>
                    <div className="pipeline-stages">
                      {[
                        ['Layer A', item.layer_a.status], ['Layer B', item.layer_b.status], ['Layer C', item.layer_c.status],
                        ['Random Forest', ml.status === 'available' ? ml.label : ml.status.replaceAll('_', ' ')],
                        ['Guardian', guardian ? guardian.verdict : 'rejected'], ['City Brain', item.city_brain.status],
                      ].map(([label, state], index) => <div className={`pipeline-stage ${index === 3 ? `stage-${ml.status === 'available' ? ml.label.toLowerCase() : 'unavailable'}` : `stage-${layerState(state)}`}`} key={label}><span>{label}</span><b>{state}</b></div>)}
                    </div>
                    <div className="demo-result-grid">
                      <div><span>Suspicious probability</span><b>{ml.probability == null ? 'Unavailable' : `${(ml.probability * 100).toFixed(1)}%`}</b><small>{ml.label}{ml.threshold == null ? '' : ` · threshold ${(ml.threshold * 100).toFixed(1)}% · band ±${((ml.uncertainty_band || 0) * 100).toFixed(0)}%`}</small></div>
                      <div><span>Guardian trust score</span><b>{guardian ? `${(guardian.trust_score * 100).toFixed(1)}%` : 'Not scored'}</b><small>{guardian?.verdict || item.rejection_reason || 'No verdict'}</small></div>
                      <div><span>City Brain</span><b className={item.city_brain.allowed ? 'decision-allowed' : 'decision-blocked'}>{item.city_brain.action.replaceAll('_', ' ')}</b><small>{item.city_brain.reason.replaceAll('_', ' ')}</small></div>
                    </div>
                    {ml.error && <p className="simulator-note">Model state: {ml.error}</p>}
                    <div className="demo-evidence"><span>ML signals</span><div>{ml.signals?.length ? ml.signals.map((signal, index) => <code key={`${signal}-${index}`}>{signal}</code>) : <em>No model signals</em>}</div></div>
                    <div className="demo-evidence"><span>Model features</span><div className="demo-feature-list">{ml.features ? Object.entries(ml.features).map(([key, feature]) => <code key={key}>{key}={typeof feature === 'number' ? Number(feature.toFixed(4)) : feature}</code>) : <em>Feature vector unavailable</em>}</div></div>
                    <div className="demo-evidence"><span>Reason codes</span><div>{[...(item.layer_a.reason_codes || []), ...(item.layer_b.reason_codes || []), ...(guardian?.reasons || [])].length
                      ? [...new Set([...(item.layer_a.reason_codes || []), ...(item.layer_b.reason_codes || []), ...(guardian?.reasons || [])])].map((code) => <code key={code}>{code}</code>)
                      : <em>No deterministic penalty or rejection reason</em>}</div></div>
                    <div className="demo-evidence"><span>Score breakdown</span><div>{guardian ? <><code>start {guardian.scoring_breakdown.starting_score.toFixed(2)}</code>{guardian.scoring_breakdown.penalties.map((penalty) => <code key={penalty.reason_code}>{penalty.reason_code} −{penalty.penalty.toFixed(2)}</code>)}<code>ML weight {guardian.scoring_breakdown.ml_numeric_contribution.toFixed(2)}</code></> : <em>Scoring skipped</em>}</div></div>
                    <div className="demo-evidence"><span>Reputation change</span><div>{item.reputation_change ? <><code>flags {item.reputation_change.raw_flags_before} → {item.reputation_change.raw_flags_after}</code><code>decayed {item.reputation_change.decayed_flags_before.toFixed(2)} → {item.reputation_change.decayed_flags_after.toFixed(2)}</code></> : <em>No reputation update</em>}</div></div>
                    <div className="stepper"><span>Reading {stepIndex + 1} of {runResult.evaluations.length}</span><div><button type="button" onClick={() => setStepIndex((index) => Math.max(0, index - 1))} disabled={stepIndex === 0}>Previous</button><button type="button" onClick={() => setStepIndex((index) => Math.min(runResult.evaluations.length - 1, index + 1))} disabled={stepIndex >= runResult.evaluations.length - 1}>Next</button></div></div>
                  </>;
                })() : <div className="demo-empty">Choose a scenario and run it to see backend evaluations. Model probability and Guardian score are separate values.</div>}
              </div>
            </div>

            <div className="demo-lower-grid">
              <div className="demo-reputation"><div className="demo-control-heading"><div><span className="section-kicker">LAYER E</span><h3>Sensor reputation</h3></div></div>{demo.overview?.sensor_reputation?.length ? <div className="reputation-list">{demo.overview.sensor_reputation.slice(-5).map((rep) => <div key={rep.sensor_id}><b>{rep.sensor_id}</b><span>{rep.decayed_flag_score.toFixed(2)} decayed · {rep.raw_flag_count} flags{rep.quarantined || rep.isolated ? ' · contained' : ''}</span></div>)}</div> : <p className="demo-empty compact">No sensor history yet.</p>}</div>
              <div className="demo-timeline"><div className="demo-control-heading"><div><span className="section-kicker">AUDIT TRACE</span><h3>Event timeline</h3></div></div>{demo.events.length ? <ol>{demo.events.slice(-9).map((event) => <li key={event.event_id}><time>{new Date(event.occurred_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time><span>{event.event_type.replaceAll('_', ' ')}</span><small>{event.data?.sensor_id || event.reading_id || 'Guardian'}</small></li>)}</ol> : <p className="demo-empty compact">Events from the backend appear here in order.</p>}</div>
            </div>
          </section>

          <div className="section-head">
            <div><span className="section-kicker">PLAYGROUND</span><h2>Reading inspector</h2></div>
            <div className="presets" aria-label="Reading presets">
              <span>Load a scenario</span>
              {Object.keys(PROFILE).map((name) => (
                <button key={name} type="button" aria-pressed={activePreset === name} className={`${activePreset === name ? 'selected' : ''} ${name === 'Fake flood' ? 'preset-alert' : ''}`} onClick={() => { setForm(fromProfile(name, form?.domain || 'water', capabilities.domains)); setResult(null); setMessage(''); }} disabled={!capabilities}>
                  {name === 'Fake flood' ? 'Fake flood · T5' : name}
                </button>
              ))}
              <span className={`custom-state ${activePreset === 'Custom' ? 'current' : ''}`} aria-live="polite">{activePreset === 'Custom' ? 'Custom' : ''}</span>
            </div>
          </div>

          <div className="workspace-grid">
            <section className="panel input-panel" aria-labelledby="sensor-title">
              <div className="panel-heading">
                <div className="heading-icon green">{domain?.quantity === 'water_level' ? <Waves size={17} /> : domain?.quantity === 'power_load' ? <Zap size={17} /> : <Activity size={17} />}</div>
                <div><h3 id="sensor-title">Sensor observation</h3><p>Configure the reading and model features</p></div>
                <span className="panel-index">INPUT</span>
              </div>
              {form && domain ? <div className="input-body">
                <label className="field-label" htmlFor="domain">Domain</label>
                <div className="select-wrap"><select id="domain" value={form.domain} onChange={(event) => changeDomain(event.target.value)}>
                  {Object.entries(capabilities.domains).map(([key, item]) => <option key={key} value={key}>{item.quantity.replaceAll('_', ' ')}</option>)}
                </select><ChevronDown size={16} aria-hidden="true" /></div>

                <div className="value-label"><label className="field-label" htmlFor="sensor-value">Observed value</label><span className="range-note">Typical {domain.lo}–{domain.hi} {domain.unit}</span></div>
                <div className="value-input-wrap"><input id="sensor-value" aria-label={`Observed value in ${domain.unit}`} type="number" step="any" value={form.value ?? ''} onChange={(event) => changeField('value', event.target.value)} /><span>{form.value == null ? 'JSON null' : domain.unit}</span></div>
                {form.value == null ? <p className="null-hint">Missing sensor value is sent as JSON null; the model abstains.</p> : <div className="slider-wrap">
                  <input aria-label="Adjust observed value" type="range" min="0" max={sliderMax} step="any" value={form.value} onChange={(event) => changeField('value', event.target.value)} style={{ '--pct': `${sliderPosition}%` }} />
                  <div><span>0</span><span>{sliderMax} {domain.unit}</span></div>
                </div>}

                <div className="subsection-title"><span>MODEL INPUTS</span><span className="muted">All fields are included in the snapshot</span></div>
                <div className="feature-grid">
                  {INPUTS.map(([key, label, step]) => <label className="feature-field" key={key} htmlFor={`field-${key}`}>
                    <span>{label}</span>
                    {step === 'flag' ? <select id={`field-${key}`} value={form[key]} onChange={(event) => changeField(key, event.target.value)}><option value="0">No</option><option value="1">Yes</option></select> : <input id={`field-${key}`} type="number" step={step} value={form[key] ?? ''} onChange={(event) => changeField(key, event.target.value)} />}
                  </label>)}
                </div>
                {activePreset === 'Stuck sensor' && <p className="scenario-note health-note">Not an attack signal — flat-run/health checks belong to the deterministic layers.</p>}
                {activePreset === 'Adaptive ramp' && <p className="scenario-note blind-spot-note">Known blind spot: a forged gradual, corroborated incident looks like a genuine one (a genuine ramp scores ≈ 0.51).</p>}
                <div className="run-row">
                  <div className="hint"><Sparkles size={15} /><span>ML output is advisory only</span></div>
                  <button className="run-button" type="button" onClick={evaluate} disabled={connection !== 'ready' || evaluating || !requiredFieldsValid}>
                    <span>{evaluating ? 'Evaluating…' : 'Evaluate reading'}</span>{evaluating ? <span className="spinner" /> : <Play size={15} fill="currentColor" />}
                  </button>
                </div>
                {message && <div className="error-message" role="alert"><AlertTriangle size={15} />{message}</div>}
              </div> : <div className="loading-panel" role="status"><span className="spinner" />Connecting to the local Guardian MCP server…</div>}
            </section>

            <section className="panel result-panel" aria-labelledby="assessment-title">
              <div className="panel-heading"><div className="heading-icon blue"><Activity size={17} /></div><div><h3 id="assessment-title">Model assessment</h3><p>Suspicious-class probability</p></div><span className="advisory-chip"><span /> ADVISORY</span></div>
              {result ? <>
                <div className={`result-state ${STATE_COPY[result.ml_label].tone}`} role="status">
                  <div className="result-icon"><StateIcon size={23} /></div>
                  <div className="result-copy"><span>MODEL SIGNAL</span><h3>{STATE_COPY[result.ml_label].title}</h3><p>{STATE_COPY[result.ml_label].detail}</p></div>
                  {result.ml_probabilities && <div className="probability">{(result.ml_probabilities.suspicious * 100).toFixed(1)}<small>%</small></div>}
                </div>
                {result.ml_probabilities ? <div className="probability-block">
                  <div className="bar-head"><span>Suspicious probability</span><b>{(result.ml_probabilities.suspicious * 100).toFixed(1)}%</b></div>
                  <div className="threshold-copy">Model threshold {(result.decision_threshold * 100).toFixed(1)}% · uncertainty band ±{(capabilities.uncertainty_band * 100).toFixed(0)}%</div>
                  <div className="probability-track"><div className={`probability-fill ${STATE_COPY[result.ml_label].tone}`} style={{ width: `${result.ml_probabilities.suspicious * 100}%` }} /><div className="threshold-marker" style={{ left: `${result.decision_threshold * 100}%` }} aria-hidden="true" /></div>
                  <div className="bar-foot"><span>0%</span><span>100%</span></div>
                </div> : <div className="unavailable-callout"><AlertTriangle size={15} /><span>Model unavailable — Guardian rules decide</span></div>}
                <div className="assessment-details"><div><span>MODEL THRESHOLD</span><b>{(result.decision_threshold * 100).toFixed(1)}%</b></div><div><span>TRUST SCORE</span><b className="not-issued">Not issued</b></div><div><span>ACTION TOKEN</span><b className="not-issued">Never from ML</b></div></div>
                <div className="result-time"><Clock3 size={13} /> {result.evaluatedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}<span>·</span><Check size={13} /> Model call complete</div>
              </> : <div className="empty-result"><div className="empty-visual"><div className="empty-ring r1" /><div className="empty-ring r2" /><div className="empty-shield"><Shield size={27} /></div><span className="empty-pulse p1" /><span className="empty-pulse p2" /></div><h3>{connection === 'ready' ? 'Ready when you are' : 'Model unavailable — Guardian rules decide'}</h3><p>{connection === 'ready' ? 'Choose a scenario or configure a sensor reading. The live model result will appear here.' : 'The MCP server did not return model capabilities. No probability is shown.'}</p></div>}
            </section>
          </div>

          <div className="analysis-grid">
            <section className="panel analysis-panel" aria-labelledby="why-title">
              <div className="analysis-heading"><div><span className="section-kicker">EXPLANATION</span><h3 id="why-title">Why these inputs stand out</h3></div><span className="quiet-chip">INPUT RULES</span></div>
              <p className="analysis-caption">Rule-of-thumb signals in the inputs, not a per-prediction attribution.</p>
              <ul className="signal-list" aria-live="polite">
                {(result?.signals || ['Evaluate a reading to see rule-of-thumb input signals.']).map((signal, index) => <li key={`${signal}-${index}`}><span className="signal-bullet"><ArrowUpRight size={12} /></span><span>{signal}</span></li>)}
              </ul>
            </section>
            <section className="panel analysis-panel reference-panel" aria-labelledby="reference-title">
              <div className="analysis-heading"><div><span className="section-kicker">COMPARISON</span><h3 id="reference-title">Reference rules</h3></div><Gauge size={17} /></div>
              <p className="analysis-caption">Re-implementation of the Guardian report's penalty table — not the real scoring.py.</p>
              {reference ? <>
                <div className="reference-score"><div><span>REFERENCE SCORE</span><small>Working defaults</small></div><strong>{reference.score.toFixed(2)}</strong><span className={`reference-state ${reference.state.toLowerCase()}`}>{reference.state}</span></div>
                <div className="reason-codes"><span>REASON CODES</span>{reference.reasons.length ? reference.reasons.map(({ code }) => <code key={code}>{code}</code>) : <em>No penalty reasons</em>}</div>
                <div className="cutoff-note">Cut-offs from local config: Trusted ≥ {capabilities?.trust_cutoffs.trusted_min.toFixed(2)} · Degraded ≥ {capabilities?.trust_cutoffs.degraded_min.toFixed(2)} · Untrusted below</div>
              </> : <div className="reference-score"><div><span>REFERENCE SCORE</span><small>Configure a reading</small></div><strong>—</strong></div>}
              <p className="verdict-footer">Final verdict: Guardian's deterministic layers. ML is advisory.</p>
            </section>
          </div>

          <section className="panel snapshot-panel" aria-labelledby="snapshot-title">
            <div className="snapshot-heading"><div><span className="section-kicker">READING DETAILS</span><h3 id="snapshot-title">Input snapshot</h3></div><button type="button" onClick={reset} className="reset-button"><RotateCcw size={13} /> Reset to Normal</button></div>
            <div className="snapshot-grid">
              <div><span>Domain</span><b>{form?.domain || '—'}</b></div>
              <div><span>Observed value</span><b>{form?.value == null ? 'null' : `${form.value} ${domain?.unit || ''}`}</b></div>
              {INPUTS.map(([key, label]) => <div key={key}><span>{label}</span><b>{form?.[key] ?? 'null'}</b></div>)}
            </div>
          </section>

          <section className="notice"><div className="notice-icon"><AlertTriangle size={17} /></div><div><b>Experimental model · synthetic training data</b><p>This model was trained on synthetic scenarios. Its reported test metrics do not predict real-world performance. Adaptive, gradual and corroborated attacks may go undetected. Replay detection belongs to deterministic protocol checks.</p></div></section>
          <footer><span><span className="footer-mark"><Shield size={13} /></span> Guardian <span className="footer-sep">/</span> 9antra</span><span>LOCAL PLAYGROUND <i /> No data leaves this machine</span><span className="footer-lock">MCP tool calls stay on this laptop</span></footer>
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
