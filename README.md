# TAIS — Telemetry Assessment and Integrity System

**MCA Capstone Project — PAMCA698J, Dissertation-1**
**Aryan Bhagat, 25MCA0022 — VIT Vellore, Fall 2026-27**
**Guide: Dr. Sathiyamoorthy E**

A server-side system that assesses the integrity of AIS-140 vehicle-tracking telemetry,
computing a Trust Score with an explained confidence level to flag kinematically implausible
data — ahead of India's shift to GNSS-based satellite tolling. Simulation-first: no physical
hardware or field data collection required to complete this capstone.

See the full project proposal for problem statement, architecture, and scope
*(proposal PDF to be added to `docs/`).*

## Status

🟡 **Week 1 of 17** — repo scaffolding, schema locked, literature survey drafted.
*(Project timeline PDF to be added.)*

## Repo Structure

```
TAIS/
├── README.md
├── requirements.txt
├── .gitignore
├── docs/
│   ├── literature_survey.md       ← Week 1
│   └── verified_ais140_fields.md  ← Week 1
├── src/
│   ├── schema.py                  ← Week 1 (LOCKED — do not redefine fields elsewhere)
│   ├── simulator/                 ← Week 4
│   ├── engine/                    ← Weeks 6-7
│   └── dashboard/                 ← Week 8
├── tests/
│   └── test_schema.py             ← Week 1
└── data/                          ← generated telemetry logs land here (gitignored)
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
pytest tests/ -v                  # confirm everything passes before you start Week 4
```

## Design Principle Carried Through Every Module

TAIS assesses telemetry **already transmitted by standard AIS-140 devices** — see
`docs/verified_ais140_fields.md` for exactly what that includes and excludes. Do not add
fields to the simulator or engine that aren't in `src/schema.py`'s locked `TelemetryRecord`
without updating that file first and re-running the test suite.
