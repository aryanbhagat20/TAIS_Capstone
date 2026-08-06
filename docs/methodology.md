# Methodology — TAIS (Telemetry Assessment and Integrity System)

*Week 2 — Review-1 document. Read alongside the architecture diagram (project overview
artifact) and `src/schema.py` (Week 1, locked data contract).*

## 1. Overall Approach

TAIS is built and evaluated **simulation-first**: no physical hardware, no real-world driving
data collection. This is a deliberate scope decision (not a shortcut) — it removes field-data
logistics risk entirely while preserving the full engineering problem, since the Trust-Scoring
Engine operates purely on telemetry *fields*, regardless of whether those fields originate
from a real device or a faithful simulator. A real AIS-140 device feed is explicitly named as
future work, and the architecture is designed so it can later replace the simulator without
changing anything downstream.

## 2. Pipeline (Five Stages)

```
Telemetry Simulator → Anomaly Injector → Trust-Scoring Engine → Explanation Layer → Dashboard
```

### Stage 1 — Telemetry Simulator (Week 4)
Generates labelled, scenario-driven telemetry sequences conforming exactly to the
`TelemetryRecord` schema locked in Week 1. Scenarios planned: **highway** (sustained high
speed, low HDOP/good signal), **city** (frequent speed/heading changes, moderate signal
quality), **degraded-signal** (elevated HDOP, occasional satellite-count drops — simulating
tunnels/urban canyons). Each generated record is labelled genuine at the point of creation,
giving exact ground truth for later evaluation.

### Stage 2 — Anomaly Injector (Week 5)
Takes genuine simulated sequences and produces deliberately anomalous variants entirely in
software (no RF transmission of any kind — this is a stated, non-negotiable scope boundary,
both for legal reasons and because it is unnecessary to demonstrate the detection concept).
Six anomaly types, matching the project's architecture documentation:

| Anomaly Type | What It Simulates |
|---|---|
| Position Jump | Impossible teleport between consecutive readings |
| Drift | Slow, unrealistic positional drift while stationary |
| Speed Injection | Unrealistic acceleration or reported speed |
| Heading Change | Impossible turning angle for the reported speed |
| Replay | Old telemetry re-sent as current |
| GPS Freeze | Vehicle moves but reported location stays fixed |

### Stage 3 — Trust-Scoring Engine (Weeks 6–7)
Rule-based checks first (interpretable, not a black box); an ML comparison layer is an
explicit **stretch goal**, not a dependency for project completion. Four sub-scores, computed
per telemetry window and combined into a weighted Trust Score (0–100):

- **Motion Consistency** — is reported speed/acceleration physically achievable given the
  previous state?
- **Trajectory Consistency** — does the position sequence describe a plausible path (no
  teleports, no impossible turning radii)?
- **Signal Quality** — HDOP/PDOP and satellite count relative to expected thresholds.
- **Temporal Consistency** — timestamps arrive in order, at expected intervals, without
  stale/replayed data.

`Trust Score = w₁(Motion) + w₂(Trajectory) + w₃(Signal Quality) + w₄(Temporal)`

Initial weights are reasonable defaults from domain reasoning, refined empirically once real
evaluation data (Week 9) is available — this refinement step is itself part of the
methodology, not an afterthought.

### Stage 4 — Explanation Layer (Week 7)
Every Trust Score ships with a **Confidence level** (High/Medium/Low) and a list of specific
triggered reasons (e.g., "HDOP abnormal", "impossible speed"). This directly addresses a risk
identified during proposal review: a single ambiguous signal (e.g., poor HDOP, which could
mean a tunnel rather than an attack) should not be reported with the same certainty as
multiple independent rule violations firing together. This is what makes the system's output
auditable rather than an unexplained number.

### Stage 5 — Dashboard (Week 8)
A demonstration interface (Flask/Streamlit) visualising scores over time, per-flag
explanations, and the tiered response — Normal / Flagged for review / Escalate. This is the
capstone's demo layer; per the project's own scoping discussion, "we built a dashboard" is
not itself a research contribution — the Trust-Scoring Engine and its evaluation are.

## 3. Why Server-Side, Not On-Device

The vehicle owner/operator is the party most likely to benefit from manipulated telemetry
under a distance-based tolling model, so a check running on their own device cannot be
trusted as an enforcement mechanism. The Trust-Scoring Engine is therefore designed to run
where a transport authority or toll operator would actually receive the data — matching how
AIS-140 telemetry already flows today, and requiring no changes to the vehicle-side hardware.

## 4. Threat Model (Explicit Scope Boundary)

**Assumed trusted:** the backend server/storage; the communication channel's authenticity at
the point the server receives data. **Attacker (vehicle owner/operator) can:** control or
fabricate what telemetry values are reported before transmission; replay previously genuine
telemetry as current. **Explicitly out of scope:** compromising the backend itself, breaking
channel-level cryptography, or physical device tampering (already handled by AIS-140's
existing detection). This keeps the project's claims precise — TAIS assesses whether
*reported* telemetry is internally consistent, not whether the channel or backend has
separately been compromised.

## 5. Evaluation Methodology (Weeks 9–10)

- **Ground truth** comes directly from the generation process itself: genuine simulated
  sequences vs. deliberately injected anomalies. This is stated as an honest, standard scoping
  limitation — no external real-world spoofing-confirmed dataset exists for this domain to
  validate against instead.
- **Metrics:** precision, recall, F1-score (flagged vs. genuine), detection latency, and
  false-positive rate specifically on genuine-but-unusual conditions (simulated
  tunnel/urban-canyon signal drops), to confirm the engine does not over-flag normal degraded
  conditions as attacks.

## 6. Deliverable Traceability

| Methodology Stage | Repo Location | Timeline Week |
|---|---|---|
| Data contract | `src/schema.py` | Week 1 ✅ |
| Telemetry Simulator | `src/simulator/` | Week 4 |
| Anomaly Injector | `src/simulator/` | Week 5 |
| Trust-Scoring Engine | `src/engine/` | Weeks 6–7 |
| Dashboard | `src/dashboard/` | Week 8 |
| Evaluation scripts | `tests/` / `src/engine/` | Weeks 9–10 |
