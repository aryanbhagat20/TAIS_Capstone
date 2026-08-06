# Problem Statement — TAIS (Telemetry Assessment and Integrity System)

*Week 2 — Review-1 document*

## 1. Context

India's AIS-140 standard mandates GPS/NavIC-based Vehicle Location Tracking Devices (VLTDs)
on all commercial vehicles (buses, taxis, trucks, school vans), enforced since 2018 and
tightened via Amendment 2 in 2023. This same hardware category is now the foundation for
India's rollout of GNSS-based satellite tolling, publicly announced by the Ministry of Road
Transport and Highways, where a vehicle's continuously reported GPS location — not a fixed
toll-booth transaction — determines the amount charged to the vehicle owner.

## 2. The Problem

Every AIS-140 device ships with mandatory tamper detection. Verified across multiple
independent sources (see `docs/literature_survey.md` and `docs/verified_ais140_fields.md`),
this tamper detection is **exclusively physical**: it flags enclosure breach, power
disconnection, or SIM removal. **Nothing in the current system checks whether the telemetry
data itself — the position, speed, and heading actually being reported — is internally
consistent or physically plausible.**

This gap was tolerable when AIS-140 data was used mainly for compliance monitoring and
after-the-fact investigation. It becomes a direct financial integrity problem once that same
data stream determines a real-time bank charge under GNSS tolling. A vehicle reporting an
inconsistent, corrupted, or manipulated trajectory could be undercharged, overcharged, or
have its trip data disputed — with no existing mechanism to flag the telemetry as suspicious
before it reaches a billing decision.

## 3. Why Existing Solutions Don't Cover This

| Existing System | What It Does | Why It Doesn't Solve This |
|---|---|---|
| AIS-140 tamper detection | Detects physical interference with the device | Says nothing about whether the *data* is trustworthy |
| Aviation-grade RAIM (integrity monitoring) | Cross-checks satellite-level data inside a receiver | Needs receiver-internal data (raw pseudoranges) that standard AIS-140 backends never receive (confirmed — see `docs/verified_ais140_fields.md`) |
| Commercial fleet-tracking dashboards | Score driver behaviour (harsh braking, speeding patterns) | Built for driving-behaviour analytics, not for assessing whether the underlying location data itself is internally consistent |

No publicly documented system evaluates AIS-140 telemetry integrity specifically, using only
the fields the standard already transmits to a backend server.

## 4. Research Question

> **Can a server-side system, using only the telemetry fields already mandated and
> transmitted under AIS-140, reliably distinguish physically plausible vehicle telemetry from
> kinematically implausible telemetry (whether caused by spoofing, signal degradation, or
> data corruption) — and communicate that distinction with enough explanation to support a
> real billing/compliance decision?**

## 5. Objectives (Restated for Review-1)

1. Precisely characterize what data is actually available at the AIS-140 backend (done —
   Week 1, `docs/verified_ais140_fields.md`).
2. Build a scenario-driven telemetry simulator standing in for real device output, since no
   public real-world AIS-140 dataset with confirmed spoofing incidents exists.
3. Design and implement a rule-based Trust-Scoring Engine that flags kinematically
   inconsistent telemetry, with a human-readable explanation and confidence level per
   decision — not a black-box score.
4. Demonstrate the system end-to-end via a dashboard showing scored telemetry and a tiered
   response (Normal / Flagged / Escalate).
5. Evaluate the system quantitatively (precision, recall, F1, detection latency, false-positive
   rate) against labelled simulator ground truth.

## 6. Explicit Scope Boundary

**In scope:** telemetry-level consistency assessment, using only currently-mandated AIS-140
fields, evaluated on simulated data generated for this project.

**Out of scope (deliberately, and stated upfront to avoid scope creep):** transmitting real
GNSS radio signals of any kind (illegal, unnecessary); integrating with live government/NHAI
systems; building a production billing platform; claiming to detect the *cause* of an anomaly
(spoofing vs. tunnel vs. firmware bug) — TAIS flags *implausibility*, and reports confidence
accordingly, without overclaiming certainty about intent.

## 7. Why This Matters (Real-World Relevance)

AIS-140 is a real, enforced mandate, not a hypothetical system, and GNSS-based tolling is an
active, publicly announced rollout on this exact hardware. TAIS addresses a concrete,
currently-unaddressed gap between what these devices already report and what is actually
verified about that report — a gap that matters far more once the data decides a bank charge
than it did when it only fed a compliance dashboard.
