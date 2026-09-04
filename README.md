# TAIS — Telemetry Assessment and Integrity System

**MCA Capstone Project — PMCA698J, Dissertation-1**
**Aryan Bhagat, 25MCA0022 — VIT Vellore, Fall 2026-27**
**Guide: Dr. Sathiyamoorthy E**

A server-side system that assesses the integrity of AIS-140 vehicle-tracking telemetry,
computing a Trust Score with an explained confidence level to flag kinematically implausible
data — ahead of India's shift to GNSS-based satellite tolling. Simulation-first: no physical
hardware or field data collection required to complete this capstone.

See the full project proposal for problem statement, architecture, and scope:
`docs/TAIS_Capstone_Proposal.pdf`.

## Status

🟠 **Week 6 of 17** — Review-1 submitted (Aug 14). Simulator + Anomaly Injector implementation in progress.
See `TAIS_Project_Timeline.pdf` for the full week-by-week plan.

### Milestones
| Milestone | Target Week | Status |
|---|---|---|
| Schema locked, tests passing | Week 1 | ✅ Done |
| Problem statement, methodology, simulator skeleton | Week 2 | ✅ Done |
| Literature survey (16 papers, APA) | Week 3 | ✅ Done |
| **Review-1 submitted** | Aug 14 | ✅ Done |
| Telemetry Simulator (full implementation) | Week 4–5 | 🔄 In Progress |
| Anomaly Injector (6 types) | Week 5 | 🔄 In Progress |
| Trust-Scoring Engine | Weeks 6–7 | ⏳ Upcoming |
| Explanation Layer | Week 7 | ⏳ Upcoming |
| Dashboard | Week 8 | ⏳ Upcoming |
| Evaluation & metrics | Weeks 9–10 | ⏳ Upcoming |

## Repo Structure

```
TAIS/
├── README.md
├── requirements.txt
├── .gitignore
├── TAIS_Project_Timeline.pdf
│
├── docs/                                ← Project documentation
│   ├── TAIS_Capstone_Proposal.pdf       ← Original proposal
│   ├── literature_survey.md             ← 16 papers, APA format (Week 1–3)
│   ├── verified_ais140_fields.md        ← Locked field reference (Week 1)
│   ├── problem_statement.md             ← Week 2
│   └── methodology.md                   ← Week 2
│
├── src/                                 ← Source code
│   ├── schema.py                        ← LOCKED data contract (TelemetryRecord + TrustAssessment)
│   ├── simulator/
│   │   └── telemetry_simulator.py       ← Week 4–5
│   ├── engine/                          ← Trust-Scoring Engine (Weeks 6–7)
│   └── dashboard/                       ← Streamlit dashboard (Week 8)
│
├── tests/                               ← Pytest test suite
│   ├── test_schema.py                   ← Week 1
│   └── test_simulator_skeleton.py       ← Week 2
│
├── data/                                ← Generated telemetry CSVs/JSONs (gitignored)
│
└── reviews/                             ← Submitted review deliverables (read-only archive)
    └── review-1/
        ├── MCA_Review_1_TAIS_FINAL.docx         ← Submitted report
        ├── MCA_Review_1_format_template.docx     ← Faculty template
        ├── TAIS_Review1_Presentation.pptx        ← Submitted presentation
        └── diagrams/
            ├── system_architecture.png
            ├── use_case_diagram.png
            ├── class_diagram.png
            └── architecture_overview.png
```

## Setup

```bash
python -m venv venv
venv\Scripts\activate             # Windows
pip install -r requirements.txt
pytest tests/ -v                  # all tests should pass before any new work
```

## Design Principle Carried Through Every Module

TAIS assesses telemetry **already transmitted by standard AIS-140 devices** — see
`docs/verified_ais140_fields.md` for exactly what that includes and excludes. Do not add
fields to the simulator or engine that aren't in `src/schema.py`'s locked `TelemetryRecord`
without updating that file first and re-running the test suite.

## Architecture

Five-stage pipeline — all stages communicate through the locked `TelemetryRecord` schema:

```
Telemetry Simulator → Anomaly Injector → Trust-Scoring Engine → Explanation Layer → Dashboard
```

See `reviews/review-1/diagrams/system_architecture.png` for the full diagram.
