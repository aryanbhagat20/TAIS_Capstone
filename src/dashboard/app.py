"""
TAIS Dashboard — Streamlit Visualization Interface
====================================================

Interactive dashboard for the Telemetry Assessment and Integrity System.

Features:
    - Real-time pipeline execution with scenario/anomaly selection
    - Trust score trend line chart with color-coded action zones
    - Sub-score radar/breakdown per record
    - Alerts table with severity levels
    - Per-record explanation panel
    - Sequence summary statistics

Usage:
    streamlit run src/dashboard/app.py
"""

import sys
import os

# Ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone, timedelta

from src.schema import TelemetryRecord, TrustAssessment, Action, Confidence
from src.injector.anomaly_injector import AnomalyInjector, AnomalyType
from src.engine.trust_scoring_engine import TrustScoringEngine, ScoringConfig


# -- Page config --
st.set_page_config(
    page_title="TAIS Dashboard",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -- Custom CSS --
st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a1f2e 0%, #2d3748 100%);
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #4a5568;
        text-align: center;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: 700;
        color: #e2e8f0;
    }
    .metric-label {
        font-size: 0.9em;
        color: #a0aec0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .status-normal { color: #48bb78; }
    .status-flagged { color: #ed8936; }
    .status-escalate { color: #fc8181; }
    .reason-box {
        background: #1a202c;
        border-left: 4px solid #ed8936;
        padding: 10px 15px;
        margin: 5px 0;
        border-radius: 0 8px 8px 0;
        font-family: monospace;
        font-size: 0.85em;
    }
</style>
""", unsafe_allow_html=True)


# ================================================================
# Data generation (cached)
# ================================================================

@st.cache_data
def generate_data(scenario, duration, seed):
    """Generate synthetic telemetry route."""
    from run_pipeline import generate_synthetic_route
    return generate_synthetic_route(
        scenario=scenario,
        duration_minutes=duration,
        seed=seed,
    )


@st.cache_data
def run_engine(records_dicts, anomaly_type_val, seed):
    """Run injector + engine on telemetry data."""
    # Reconstruct records from dicts
    from src.schema import PositionValidity, DeviceStatus
    records = []
    for d in records_dicts:
        d = dict(d)
        d['timestamp'] = datetime.fromisoformat(d['timestamp'])
        d['position_validity'] = PositionValidity(d['position_validity'])
        d['device_status'] = DeviceStatus(d['device_status'])
        records.append(TelemetryRecord(**d))

    engine = TrustScoringEngine()

    if anomaly_type_val != "none":
        injector = AnomalyInjector(seed=seed)
        atype = AnomalyType(anomaly_type_val)
        modified, labels = injector.inject(records, atype)
        assessments = engine.assess_sequence(modified)
        label_indices = {l.record_index for l in labels}
        return assessments, label_indices, modified
    else:
        assessments = engine.assess_sequence(records)
        return assessments, set(), records


def assessments_to_df(assessments):
    """Convert assessments to a pandas DataFrame."""
    rows = []
    for i, a in enumerate(assessments):
        rows.append({
            "Index": i,
            "Timestamp": a.timestamp,
            "Trust Score": a.trust_score,
            "Action": a.action.value,
            "Confidence": a.confidence.value,
            "Motion": a.sub_scores.get("motion", 100),
            "Trajectory": a.sub_scores.get("trajectory", 100),
            "Signal": a.sub_scores.get("signal", 100),
            "Temporal": a.sub_scores.get("temporal", 100),
            "Reasons": "; ".join(a.reasons) if a.reasons else "None",
            "Flag Count": len(a.reasons),
        })
    return pd.DataFrame(rows)


# ================================================================
# Sidebar
# ================================================================

st.sidebar.markdown("# TAIS Dashboard")
st.sidebar.markdown("**Telemetry Assessment & Integrity System**")
st.sidebar.markdown("---")

scenario = st.sidebar.selectbox(
    "Driving Scenario",
    ["highway", "city", "degraded"],
    index=0,
    help="Highway: 60-100km/h, City: 0-40km/h, Degraded: high HDOP"
)

duration = st.sidebar.slider(
    "Duration (minutes)", 5, 30, 15, step=5,
)

anomaly_options = ["none"] + [a.value for a in AnomalyType]
anomaly_type = st.sidebar.selectbox(
    "Inject Anomaly",
    anomaly_options,
    index=0,
    help="Select 'none' for clean data, or inject a specific anomaly type"
)

seed = st.sidebar.number_input("Random Seed", value=42, step=1)

st.sidebar.markdown("---")
run_button = st.sidebar.button("Run Pipeline", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.markdown("""
**TAIS v1.0**
25MCA0022 - Aryan Bhagat
VIT Vellore, Fall 2026-27
Guide: Dr. Sathiyamoorthy E
""")


# ================================================================
# Main content
# ================================================================

# Generate and cache data
clean_records = generate_data(scenario, duration, seed)
records_dicts = [r.to_dict() for r in clean_records]
assessments, label_indices, scored_records = run_engine(
    [tuple(sorted(d.items())) for d in records_dicts],
    anomaly_type, seed,
)
df = assessments_to_df(assessments)

# -- Header --
st.markdown("# TAIS - Telemetry Assessment & Integrity System")
st.markdown(f"**Scenario:** `{scenario}` | **Anomaly:** `{anomaly_type}` | "
            f"**Records:** `{len(assessments)}` | **Duration:** `{duration} min`")

# -- Metric cards --
col1, col2, col3, col4, col5 = st.columns(5)

mean_score = df["Trust Score"].mean()
min_score = df["Trust Score"].min()
normal_count = len(df[df["Action"] == "Normal"])
flagged_count = len(df[df["Action"] == "Flagged for review"])
escalate_count = len(df[df["Action"] == "Escalate"])

with col1:
    color = "#48bb78" if mean_score > 80 else "#ed8936" if mean_score > 50 else "#fc8181"
    st.metric("Mean Trust Score", f"{mean_score:.1f}", delta=None)

with col2:
    st.metric("Min Score", f"{min_score:.1f}")

with col3:
    st.metric("Normal", f"{normal_count}", delta=None)

with col4:
    st.metric("Flagged", f"{flagged_count}",
              delta=f"{flagged_count}" if flagged_count > 0 else None,
              delta_color="inverse")

with col5:
    st.metric("Escalate", f"{escalate_count}",
              delta=f"{escalate_count}" if escalate_count > 0 else None,
              delta_color="inverse")


# -- Trust Score Trend Chart --
st.markdown("---")
st.markdown("## Trust Score Timeline")

fig = go.Figure()

# Action zone bands
fig.add_hrect(y0=70, y1=100, fillcolor="rgba(72,187,120,0.1)",
              line_width=0, annotation_text="Normal Zone",
              annotation_position="top right")
fig.add_hrect(y0=40, y1=70, fillcolor="rgba(237,137,54,0.15)",
              line_width=0, annotation_text="Flagged Zone",
              annotation_position="top right")
fig.add_hrect(y0=0, y1=40, fillcolor="rgba(252,129,129,0.15)",
              line_width=0, annotation_text="Escalate Zone",
              annotation_position="top right")

# Color-coded scatter
colors = []
for _, row in df.iterrows():
    if row["Action"] == "Escalate":
        colors.append("#fc8181")
    elif row["Action"] == "Flagged for review":
        colors.append("#ed8936")
    else:
        colors.append("#48bb78")

fig.add_trace(go.Scatter(
    x=df["Timestamp"],
    y=df["Trust Score"],
    mode="lines+markers",
    marker=dict(color=colors, size=6),
    line=dict(color="#63b3ed", width=2),
    hovertemplate=(
        "Time: %{x}<br>"
        "Trust Score: %{y:.1f}<br>"
        "<extra></extra>"
    ),
    name="Trust Score",
))

# Highlight anomaly injection window
if label_indices:
    anom_df = df[df["Index"].isin(label_indices)]
    fig.add_trace(go.Scatter(
        x=anom_df["Timestamp"],
        y=anom_df["Trust Score"],
        mode="markers",
        marker=dict(color="red", size=12, symbol="x",
                    line=dict(width=2, color="white")),
        name="Injected Anomaly",
        hovertemplate=(
            "ANOMALY INJECTED<br>"
            "Time: %{x}<br>"
            "Trust Score: %{y:.1f}<br>"
            "<extra></extra>"
        ),
    ))

fig.update_layout(
    template="plotly_dark",
    height=400,
    margin=dict(l=40, r=40, t=30, b=40),
    xaxis_title="Time",
    yaxis_title="Trust Score (0-100)",
    yaxis=dict(range=[-5, 105]),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)

st.plotly_chart(fig, use_container_width=True)


# -- Sub-scores chart --
col_left, col_right = st.columns([3, 2])

with col_left:
    st.markdown("## Sub-Score Breakdown")

    fig_sub = go.Figure()
    for dim, color in [("Motion", "#63b3ed"), ("Trajectory", "#68d391"),
                        ("Signal", "#fbd38d"), ("Temporal", "#fc8181")]:
        fig_sub.add_trace(go.Scatter(
            x=df["Timestamp"], y=df[dim],
            mode="lines", name=dim,
            line=dict(color=color, width=1.5),
        ))

    fig_sub.update_layout(
        template="plotly_dark",
        height=300,
        margin=dict(l=40, r=40, t=30, b=40),
        yaxis=dict(range=[-5, 105], title="Sub-Score"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_sub, use_container_width=True)

with col_right:
    st.markdown("## Action Distribution")
    action_counts = df["Action"].value_counts()
    fig_pie = go.Figure(data=[go.Pie(
        labels=action_counts.index,
        values=action_counts.values,
        marker=dict(colors=["#48bb78", "#ed8936", "#fc8181"]),
        hole=0.5,
        textinfo="label+percent",
    )])
    fig_pie.update_layout(
        template="plotly_dark",
        height=300,
        margin=dict(l=20, r=20, t=30, b=20),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    st.plotly_chart(fig_pie, use_container_width=True)


# -- Alerts table --
st.markdown("---")
st.markdown("## Flagged Records & Alerts")

flagged_df = df[df["Flag Count"] > 0].copy()
if len(flagged_df) > 0:
    flagged_df = flagged_df[["Index", "Timestamp", "Trust Score", "Action",
                              "Confidence", "Reasons"]].reset_index(drop=True)
    st.dataframe(
        flagged_df.style.apply(
            lambda row: [
                'background-color: #742a2a' if row["Action"] == "Escalate"
                else 'background-color: #744210' if row["Action"] == "Flagged for review"
                else '' for _ in row
            ], axis=1
        ),
        use_container_width=True,
        height=min(400, len(flagged_df) * 35 + 38),
    )
else:
    st.success("No flags triggered -- all records within normal parameters.")

# -- Record detail explorer --
st.markdown("---")
st.markdown("## Record Detail Explorer")

selected_idx = st.slider(
    "Select Record Index",
    min_value=0, max_value=len(assessments) - 1, value=0,
)

a = assessments[selected_idx]
r = scored_records[selected_idx]

detail_col1, detail_col2, detail_col3 = st.columns(3)

with detail_col1:
    st.markdown("### Telemetry Data")
    st.json({
        "device_id": r.device_id,
        "timestamp": r.timestamp.isoformat(),
        "latitude": r.latitude,
        "longitude": r.longitude,
        "speed_kmh": r.speed,
        "heading_deg": r.heading,
        "hdop": r.hdop,
        "satellite_count": r.satellite_count,
        "mileage_km": r.mileage,
    })

with detail_col2:
    st.markdown("### Trust Assessment")
    score_color = "green" if a.trust_score > 70 else "orange" if a.trust_score > 40 else "red"
    st.markdown(f"**Trust Score:** :{score_color}[**{a.trust_score}**]")
    st.markdown(f"**Action:** {a.action.value}")
    st.markdown(f"**Confidence:** {a.confidence.value}")

    st.markdown("**Sub-Scores:**")
    for dim, score in a.sub_scores.items():
        bar_color = "green" if score > 80 else "orange" if score > 50 else "red"
        st.progress(score / 100, text=f"{dim.title()}: {score}")

with detail_col3:
    st.markdown("### Explanations")
    if a.reasons:
        for reason in a.reasons:
            rule_id = reason.split(":")[0].strip()
            st.markdown(f"""
<div class="reason-box">
    <strong>{rule_id}</strong>: {reason.split(':', 1)[1].strip() if ':' in reason else reason}
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("*No anomalies detected for this record.*")

    is_anomaly = selected_idx in label_indices
    if is_anomaly:
        st.error(f"This record has an INJECTED ANOMALY ({anomaly_type})")


# -- Summary stats --
st.markdown("---")
st.markdown("## Sequence Summary")

engine = TrustScoringEngine()
summary = engine.sequence_summary(assessments)

sum_col1, sum_col2 = st.columns(2)
with sum_col1:
    st.json({
        "total_records": summary["count"],
        "mean_score": summary["mean_score"],
        "min_score": summary["min_score"],
        "max_score": summary["max_score"],
        "normal": summary["normal_count"],
        "flagged": summary["flagged_count"],
        "escalate": summary["escalate_count"],
    })

with sum_col2:
    if summary.get("rule_breakdown"):
        st.markdown("### Rule Trigger Breakdown")
        rule_df = pd.DataFrame([
            {"Rule": k, "Triggers": v}
            for k, v in sorted(summary["rule_breakdown"].items())
        ])
        st.bar_chart(rule_df.set_index("Rule"))
    else:
        st.info("No rules were triggered in this sequence.")
