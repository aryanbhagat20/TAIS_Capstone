"""
TAIS Dashboard v2.0 -- Real Data Visualization
=================================================

Human-friendly dashboard for the Telemetry Assessment & Integrity System.
Uses self-collected GPS data from VIT Vellore trips.

Usage:
    streamlit run src/dashboard/app.py
"""

import sys
import os

# Ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
# pyrefly: ignore [import-unresolved, missing-import]
import plotly.graph_objects as go
# pyrefly: ignore [import-unresolved, missing-import]
import plotly.express as px
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.schema import TelemetryRecord, TrustAssessment, Action, Confidence
from src.injector.anomaly_injector import AnomalyInjector, AnomalyType
from src.engine.trust_scoring_engine import TrustScoringEngine, ScoringConfig
from src.data_loader.own_data_loader import OwnDataLoader


# -- Page config --
st.set_page_config(
    page_title="TAIS - Trust Assessment Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -- Custom CSS for a clean, readable design --
st.markdown("""
<style>
    /* Overall font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
        padding: 16px 20px;
        border-radius: 12px;
        border: 1px solid #475569;
    }
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: 700;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #94a3b8;
    }

    /* Section headers */
    .section-header {
        font-size: 1.4rem;
        font-weight: 600;
        color: #e2e8f0;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
        padding-bottom: 0.5rem;
        border-bottom: 2px solid #3b82f6;
    }

    /* Info cards */
    .info-card {
        background: #1e293b;
        border-radius: 10px;
        padding: 16px;
        border-left: 4px solid #3b82f6;
        margin: 8px 0;
    }
    .info-card-warn {
        border-left-color: #f59e0b;
    }
    .info-card-danger {
        border-left-color: #ef4444;
    }
    .info-card-success {
        border-left-color: #22c55e;
    }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.9rem;
    }
    .score-high { background: #166534; color: #bbf7d0; }
    .score-mid { background: #854d0e; color: #fef08a; }
    .score-low { background: #991b1b; color: #fecaca; }

    /* Rule explanation */
    .rule-card {
        background: #0f172a;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 6px 0;
    }
    .rule-id {
        font-weight: 700;
        color: #60a5fa;
        font-size: 0.9rem;
    }
    .rule-desc {
        color: #cbd5e1;
        font-size: 0.85rem;
        margin-top: 4px;
    }

    /* Hide default streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ==================================================================
# Data loading functions
# ==================================================================

TRIP_DIR = Path(ROOT) / "data" / "raw" / "own_collection"
TDRIVE_DIR = Path(ROOT) / "data" / "raw" / "tdrive"

TRIP_INFO = {
    # Own collected trips
    "trip_01_campus": {
        "label": "Campus Walk (VIT Vellore)",
        "icon": "🏫",
        "description": "Walking around VIT campus - low speed, frequent turns",
        "source": "own",
    },
    "trip_02_city": {
        "label": "City Drive (Vellore)",
        "icon": "🏙️",
        "description": "Driving through Vellore city - mixed speeds, traffic signals",
        "source": "own",
    },
    "trip_03_highway": {
        "label": "Highway Drive",
        "icon": "🛣️",
        "description": "Highway driving - sustained high speed, straight roads",
        "source": "own",
    },
    "trip_05_stationary": {
        "label": "Stationary (Parked)",
        "icon": "🅿️",
        "description": "Phone kept stationary - baseline for GPS drift detection",
        "source": "own",
    },
}

# Dynamically add T-Drive taxis
for txt_file in sorted(TDRIVE_DIR.glob("*.txt")):
    taxi_id = txt_file.stem
    key = f"tdrive_{taxi_id}"
    TRIP_INFO[key] = {
        "label": f"Beijing Taxi #{taxi_id}",
        "icon": "🚕",
        "description": f"T-Drive dataset - Taxi {taxi_id} trajectory in Beijing",
        "source": "tdrive",
    }


@st.cache_data
def load_trip_data(trip_name):
    """Load a trip from either own collection or T-Drive."""
    info = TRIP_INFO[trip_name]
    if info["source"] == "own":
        loader = OwnDataLoader()
        device_id = f"ARYAN_{trip_name.split('_')[2].upper()}"
        records = loader.load_trip(str(TRIP_DIR / f"{trip_name}.csv"), device_id=device_id)
    else:
        from src.data_loader.tdrive_loader import TDriveLoader
        loader = TDriveLoader(str(TDRIVE_DIR))
        taxi_id = int(trip_name.replace("tdrive_", ""))
        records = loader.load_taxi(taxi_id=taxi_id)
    return records


@st.cache_data
def score_records(_records_hash, records_list, inject_anomaly, seed):
    """Score records through the engine, optionally injecting anomalies."""
    # Reconstruct records from serializable format
    from src.schema import PositionValidity, DeviceStatus
    records = []
    for d in records_list:
        d = dict(d)
        d['timestamp'] = datetime.fromisoformat(d['timestamp'])
        d['position_validity'] = PositionValidity(d['position_validity'])
        d['device_status'] = DeviceStatus(d['device_status'])
        records.append(TelemetryRecord(**d))

    engine = TrustScoringEngine()
    label_indices = set()

    if inject_anomaly and inject_anomaly != "none":
        injector = AnomalyInjector(seed=seed)
        atype = AnomalyType(inject_anomaly)
        records, labels = injector.inject(records, atype)
        label_indices = {l.record_index for l in labels}

    assessments = engine.assess_sequence(records)
    summary = engine.sequence_summary(assessments)
    return assessments, summary, label_indices, records


def make_df(assessments, records, label_indices):
    """Build a combined DataFrame for visualization."""
    rows = []
    for i, (a, r) in enumerate(zip(assessments, records)):
        rows.append({
            "Index": i,
            "Time": a.timestamp,
            "Latitude": r.latitude,
            "Longitude": r.longitude,
            "Speed (km/h)": round(r.speed, 1),
            "Heading": round(r.heading, 1),
            "Satellites": r.satellite_count,
            "HDOP": r.hdop,
            "Trust Score": a.trust_score,
            "Action": a.action.value,
            "Confidence": a.confidence.value,
            "Motion Score": a.sub_scores.get("motion", 100),
            "Trajectory Score": a.sub_scores.get("trajectory", 100),
            "Signal Score": a.sub_scores.get("signal", 100),
            "Temporal Score": a.sub_scores.get("temporal", 100),
            "Issues": "; ".join(a.reasons) if a.reasons else "",
            "Issue Count": len(a.reasons),
            "Is Anomaly": i in label_indices,
            "Source": "GPS" if r.satellite_count > 0 else "Network",
        })
    return pd.DataFrame(rows)


# Human-readable rule explanations
RULE_EXPLANATIONS = {
    "R1": ("Speed Check", "Is the vehicle going faster than physically possible (>200 km/h)?"),
    "R2": ("Acceleration Check", "Did the vehicle speed up or brake impossibly fast?"),
    "R3": ("Position vs Speed", "Does the actual distance moved match the reported speed?"),
    "R4": ("Direction Check", "Does the heading match the actual direction of travel?"),
    "R5": ("GPS Quality (HDOP)", "Is the GPS fix quality good enough to trust the position?"),
    "R6": ("Satellite Count", "Are there enough satellites for a reliable GPS fix (need 4+)?"),
    "R7": ("Time Check", "Are timestamps consistent (no gaps, jumps, or going backwards)?"),
}


# ==================================================================
# Sidebar — Trip Selection
# ==================================================================

st.sidebar.markdown("# 🛡️ TAIS Dashboard")
st.sidebar.markdown("*Telemetry Assessment & Integrity System*")
st.sidebar.markdown("---")

# Find available trips from both sources
available_trips = []
for name, info in TRIP_INFO.items():
    if info["source"] == "own" and (TRIP_DIR / f"{name}.csv").exists():
        available_trips.append(name)
    elif info["source"] == "tdrive" and (TDRIVE_DIR / f"{name.replace('tdrive_', '')}.txt").exists():
        available_trips.append(name)

if not available_trips:
    st.error("No trip data found!")
    st.stop()

# Data source filter
st.sidebar.markdown("### Data Source")
source_filter = st.sidebar.radio(
    "Show trips from:",
    ["All", "Own Collection (Vellore)", "T-Drive (Beijing)"],
    index=0,
    label_visibility="collapsed",
)

if source_filter == "Own Collection (Vellore)":
    filtered_trips = [t for t in available_trips if TRIP_INFO[t]["source"] == "own"]
elif source_filter == "T-Drive (Beijing)":
    filtered_trips = [t for t in available_trips if TRIP_INFO[t]["source"] == "tdrive"]
else:
    filtered_trips = available_trips

# Trip selector
st.sidebar.markdown("### Select Trip")
selected_trip = st.sidebar.selectbox(
    "Choose a trip to analyze",
    filtered_trips,
    format_func=lambda x: f"{TRIP_INFO[x]['icon']} {TRIP_INFO[x]['label']}",
    label_visibility="collapsed",
)

trip_info = TRIP_INFO[selected_trip]
source_badge = "📱 Self-collected" if trip_info["source"] == "own" else "📊 T-Drive Dataset"
st.sidebar.info(f"**{trip_info['label']}**\n\n{trip_info['description']}\n\n*Source: {source_badge}*")

# Anomaly injection toggle
st.sidebar.markdown("---")
st.sidebar.markdown("### Anomaly Simulation")
st.sidebar.caption(
    "Inject a fake anomaly into the real data to test if the engine detects it."
)

inject_anomaly = st.sidebar.selectbox(
    "Inject anomaly type",
    ["none", "position_jump", "speed_injection", "gps_freeze",
     "drift", "heading_change", "replay"],
    format_func=lambda x: {
        "none": "No injection (clean data)",
        "position_jump": "Position Jump (teleport)",
        "speed_injection": "Impossible Speed (>300 km/h)",
        "gps_freeze": "GPS Freeze (stuck position)",
        "drift": "Slow Drift (gradual position shift)",
        "heading_change": "Heading Flip (sudden direction change)",
        "replay": "Replay Attack (repeated old data)",
    }.get(x, x),
)

seed = st.sidebar.number_input("Random seed", value=42, step=1)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**TAIS v2.0** | 25MCA0022\n\n"
    "Aryan Bhagat | VIT Vellore\n\n"
    "Guide: Dr. Sathiyamoorthy E"
)


# ==================================================================
# Load & process data
# ==================================================================

records = load_trip_data(selected_trip)
records_dicts = [tuple(sorted(r.to_dict().items())) for r in records]
records_list = [r.to_dict() for r in records]
records_hash = hash(tuple(records_dicts))

assessments, summary, label_indices, scored_records = score_records(
    records_hash, records_list, inject_anomaly, seed
)
df = make_df(assessments, scored_records, label_indices)


# ==================================================================
# Header
# ==================================================================

st.markdown(f"# {trip_info['icon']} {trip_info['label']}")

if inject_anomaly != "none":
    st.warning(
        f"**Anomaly Injected:** `{inject_anomaly}` -- "
        f"The engine is analyzing data WITH a simulated attack to test detection."
    )

# Trip metadata
duration_s = (records[-1].timestamp - records[0].timestamp).total_seconds()
col_info1, col_info2, col_info3, col_info4 = st.columns(4)
with col_info1:
    st.caption("RECORDS")
    st.markdown(f"**{len(records):,}** data points")
with col_info2:
    st.caption("DURATION")
    if duration_s < 3600:
        st.markdown(f"**{duration_s/60:.0f}** minutes")
    else:
        st.markdown(f"**{duration_s/3600:.1f}** hours")
with col_info3:
    st.caption("DISTANCE")
    st.markdown(f"**{records[-1].mileage:.1f}** km")
with col_info4:
    st.caption("MAX SPEED")
    st.markdown(f"**{max(r.speed for r in records):.0f}** km/h")


# ==================================================================
# Trust Score Overview
# ==================================================================

st.markdown("---")
st.markdown('<div class="section-header">Trust Score Overview</div>', unsafe_allow_html=True)

# Metric cards
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Average Score", f"{summary['mean_score']:.1f}/100")
with m2:
    st.metric("Lowest Score", f"{summary['min_score']:.1f}/100")
with m3:
    delta_n = None if summary['normal_count'] == summary['count'] else f"{summary['normal_count']}/{summary['count']}"
    st.metric("Normal", f"{summary['normal_count']}")
with m4:
    st.metric("Flagged", f"{summary['flagged_count']}",
              delta=f"-{summary['flagged_count']}" if summary['flagged_count'] > 0 else None,
              delta_color="inverse")
with m5:
    st.metric("Escalated", f"{summary['escalate_count']}",
              delta=f"-{summary['escalate_count']}" if summary['escalate_count'] > 0 else None,
              delta_color="inverse")

# Quick verdict
if summary['escalate_count'] > 0:
    st.error("**ALERT:** Some records scored critically low and need investigation!")
elif summary['flagged_count'] > 0:
    st.warning(f"**{summary['flagged_count']} records** were flagged for review. "
               "This could indicate GPS noise or a genuine anomaly.")
else:
    st.success("**All records passed** -- no anomalies detected in this trip.")


# ==================================================================
# Trust Score Timeline
# ==================================================================

st.markdown("---")
st.markdown('<div class="section-header">Trust Score Over Time</div>', unsafe_allow_html=True)
st.caption(
    "Each dot is one GPS reading. Green = Normal, Orange = Flagged, Red = Escalated. "
    "The colored bands show the score zones."
)

fig_timeline = go.Figure()

# Zone bands
fig_timeline.add_hrect(y0=70, y1=100, fillcolor="rgba(34,197,94,0.08)",
                        line_width=0, annotation_text="NORMAL",
                        annotation_position="top left",
                        annotation=dict(font_color="#4ade80", font_size=11))
fig_timeline.add_hrect(y0=40, y1=70, fillcolor="rgba(245,158,11,0.08)",
                        line_width=0, annotation_text="FLAGGED",
                        annotation_position="top left",
                        annotation=dict(font_color="#fbbf24", font_size=11))
fig_timeline.add_hrect(y0=0, y1=40, fillcolor="rgba(239,68,68,0.08)",
                        line_width=0, annotation_text="ESCALATE",
                        annotation_position="top left",
                        annotation=dict(font_color="#f87171", font_size=11))

# Color map for dots
color_map = {"Normal": "#22c55e", "Flagged for review": "#f59e0b", "Escalate": "#ef4444"}
dot_colors = [color_map.get(a, "#22c55e") for a in df["Action"]]

fig_timeline.add_trace(go.Scatter(
    x=df["Time"], y=df["Trust Score"],
    mode="lines+markers",
    line=dict(color="#60a5fa", width=1.5),
    marker=dict(color=dot_colors, size=5),
    hovertemplate=(
        "<b>Time:</b> %{x|%H:%M:%S}<br>"
        "<b>Trust Score:</b> %{y:.1f}/100<br>"
        "<extra></extra>"
    ),
    name="Trust Score",
))

# Mark injected anomalies
if label_indices:
    anom_df = df[df["Is Anomaly"]]
    fig_timeline.add_trace(go.Scatter(
        x=anom_df["Time"], y=anom_df["Trust Score"],
        mode="markers",
        marker=dict(color="#ef4444", size=14, symbol="x",
                    line=dict(width=2, color="white")),
        name="Injected Anomaly",
        hovertemplate="<b>ANOMALY INJECTED HERE</b><br>Score: %{y:.1f}<extra></extra>",
    ))

fig_timeline.update_layout(
    template="plotly_dark",
    height=380,
    margin=dict(l=50, r=30, t=20, b=50),
    xaxis_title="Time",
    yaxis_title="Trust Score",
    yaxis=dict(range=[-2, 105]),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0.5, xanchor="center"),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)

st.plotly_chart(fig_timeline, use_container_width=True)


# ==================================================================
# Two-column: Sub-scores + GPS Map
# ==================================================================

st.markdown("---")
col_left, col_right = st.columns([3, 2])

with col_left:
    st.markdown('<div class="section-header">What the Engine Checks (4 Dimensions)</div>',
                unsafe_allow_html=True)
    st.caption(
        "The trust score is built from 4 independent checks. "
        "A drop in any dimension explains WHY a record was flagged."
    )

    fig_sub = go.Figure()
    dims = [
        ("Motion Score", "#3b82f6", "Speed & acceleration checks (R1, R2)"),
        ("Trajectory Score", "#22c55e", "Position vs speed & heading checks (R3, R4)"),
        ("Signal Score", "#f59e0b", "GPS quality & satellite count (R5, R6)"),
        ("Temporal Score", "#ef4444", "Timestamp consistency (R7)"),
    ]
    for col_name, color, desc in dims:
        fig_sub.add_trace(go.Scatter(
            x=df["Time"], y=df[col_name],
            mode="lines", name=col_name.replace(" Score", ""),
            line=dict(color=color, width=1.5),
            hovertemplate=f"<b>{col_name}:</b> " + "%{y:.1f}<extra></extra>",
        ))

    fig_sub.update_layout(
        template="plotly_dark",
        height=300,
        margin=dict(l=50, r=30, t=10, b=40),
        yaxis=dict(range=[-2, 105], title="Score"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0.5, xanchor="center"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_sub, use_container_width=True)

with col_right:
    st.markdown('<div class="section-header">Trip Route on Map</div>',
                unsafe_allow_html=True)
    st.caption("GPS points plotted on map. Color = trust score.")

    map_df = df[["Latitude", "Longitude", "Trust Score", "Speed (km/h)"]].copy()
    map_df = map_df.rename(columns={"Latitude": "lat", "Longitude": "lon"})
    # Filter out obviously wrong points (network jumps)
    map_df = map_df[(map_df["lat"] > 12.5) & (map_df["lat"] < 13.5)]

    st.map(map_df, size=8)


# ==================================================================
# Speed & Satellite Profile
# ==================================================================

st.markdown("---")
st.markdown('<div class="section-header">Speed & Signal Quality Profile</div>',
            unsafe_allow_html=True)
st.caption(
    "Top: Vehicle speed over time. Bottom: Number of satellites tracking your position. "
    "Below 4 satellites = unreliable fix."
)

fig_speed = go.Figure()

# Speed trace
fig_speed.add_trace(go.Scatter(
    x=df["Time"], y=df["Speed (km/h)"],
    mode="lines", name="Speed",
    line=dict(color="#8b5cf6", width=1.5),
    hovertemplate="<b>Speed:</b> %{y:.1f} km/h<extra></extra>",
))

fig_speed.update_layout(
    template="plotly_dark",
    height=200,
    margin=dict(l=50, r=30, t=10, b=30),
    yaxis_title="Speed (km/h)",
    showlegend=False,
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_speed, use_container_width=True)

fig_sats = go.Figure()
fig_sats.add_trace(go.Bar(
    x=df["Time"], y=df["Satellites"],
    marker_color=["#22c55e" if s >= 4 else "#ef4444" for s in df["Satellites"]],
    hovertemplate="<b>Satellites:</b> %{y}<extra></extra>",
))
fig_sats.add_hline(y=4, line_dash="dash", line_color="#f59e0b",
                    annotation_text="Minimum for 3D fix",
                    annotation_position="top left",
                    annotation_font_color="#fbbf24")
fig_sats.update_layout(
    template="plotly_dark",
    height=180,
    margin=dict(l=50, r=30, t=10, b=30),
    yaxis_title="Satellites",
    showlegend=False,
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_sats, use_container_width=True)


# ==================================================================
# Flagged Records Table
# ==================================================================

st.markdown("---")
st.markdown('<div class="section-header">Flagged Records Detail</div>',
            unsafe_allow_html=True)

flagged_df = df[df["Issue Count"] > 0][
    ["Index", "Time", "Trust Score", "Action", "Speed (km/h)",
     "Satellites", "HDOP", "Source", "Issues"]
].copy()

if len(flagged_df) > 0:
    st.caption(
        f"**{len(flagged_df)} records** had issues detected. "
        "Click any row to see the full explanation below."
    )

    # Color-code rows
    def highlight_action(row):
        if row["Action"] == "Escalate":
            return ["background-color: rgba(239,68,68,0.2)"] * len(row)
        elif row["Action"] == "Flagged for review":
            return ["background-color: rgba(245,158,11,0.15)"] * len(row)
        return [""] * len(row)

    st.dataframe(
        flagged_df.style.apply(highlight_action, axis=1),
        use_container_width=True,
        height=min(400, len(flagged_df) * 35 + 40),
    )
else:
    st.success("No issues detected -- all records passed all 7 checks!")


# ==================================================================
# Record Inspector
# ==================================================================

st.markdown("---")
st.markdown('<div class="section-header">Record Inspector</div>', unsafe_allow_html=True)
st.caption("Slide to inspect any individual GPS reading and see exactly what the engine found.")

idx = st.slider("Select record #", 0, len(assessments) - 1, 0)

a = assessments[idx]
r = scored_records[idx]

c1, c2, c3 = st.columns([1, 1, 1])

with c1:
    st.markdown("#### GPS Data")
    st.markdown(f"""
| Field | Value |
|-------|-------|
| **Time** | {r.timestamp.strftime('%H:%M:%S')} |
| **Location** | {r.latitude:.6f}, {r.longitude:.6f} |
| **Speed** | {r.speed:.1f} km/h |
| **Heading** | {r.heading:.0f} deg |
| **Satellites** | {r.satellite_count} |
| **HDOP** | {r.hdop} |
| **Source** | {'GPS' if r.satellite_count > 0 else 'Network'} |
""")

with c2:
    st.markdown("#### Trust Assessment")

    # Score with color
    if a.trust_score > 70:
        score_class = "score-high"
    elif a.trust_score > 40:
        score_class = "score-mid"
    else:
        score_class = "score-low"

    st.markdown(
        f'<span class="score-badge {score_class}">{a.trust_score}/100</span> '
        f'&nbsp; **{a.action.value}** &nbsp; ({a.confidence.value} confidence)',
        unsafe_allow_html=True,
    )

    st.markdown("")
    for dim_name, dim_key in [("Motion", "motion"), ("Trajectory", "trajectory"),
                                ("Signal", "signal"), ("Temporal", "temporal")]:
        score = a.sub_scores.get(dim_key, 100)
        color = "green" if score > 80 else "orange" if score > 50 else "red"
        st.progress(score / 100, text=f"{dim_name}: {score:.0f}/100")

with c3:
    st.markdown("#### What Was Found")
    if a.reasons:
        for reason in a.reasons:
            rule_id = reason.split(":")[0].strip()
            rule_name, rule_explain = RULE_EXPLANATIONS.get(rule_id, ("Unknown", ""))
            detail = reason.split(":", 1)[1].strip() if ":" in reason else reason
            st.markdown(f"""
<div class="rule-card">
    <span class="rule-id">{rule_id}: {rule_name}</span>
    <div class="rule-desc">{detail}</div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown("""
<div class="info-card info-card-success">
    <b>All clear!</b> This record passed all 7 checks with no issues.
</div>
""", unsafe_allow_html=True)

    if idx in label_indices:
        st.markdown(f"""
<div class="info-card info-card-danger">
    <b>INJECTED ANOMALY</b><br>
    A <code>{inject_anomaly}</code> anomaly was injected at this record for testing.
</div>
""", unsafe_allow_html=True)


# ==================================================================
# How the Scoring Works (Educational)
# ==================================================================

st.markdown("---")
with st.expander("How does the Trust Scoring Engine work?", expanded=False):
    st.markdown("""
### How TAIS Scores Each GPS Reading

Every GPS reading is checked against **7 rules** grouped into **4 dimensions**.
Each dimension starts at **100 points** and loses points for violations.
The final trust score is a weighted average:

| Dimension | Weight | Rules | What It Checks |
|-----------|--------|-------|----------------|
| **Motion** | 35% | R1, R2 | Is the speed/acceleration physically possible? |
| **Trajectory** | 30% | R3, R4 | Does the position match the speed and direction? |
| **Signal** | 15% | R5, R6 | Is the GPS signal reliable (HDOP, satellites)? |
| **Temporal** | 20% | R7 | Are timestamps consistent and sequential? |

### Action Thresholds

| Score | Action | Meaning |
|-------|--------|---------|
| **> 70** | Normal | Data looks trustworthy |
| **40 - 70** | Flagged | Something looks off, needs human review |
| **< 40** | Escalate | Strong evidence of tampering or failure |

### Why This Matters

Fleet tracking devices can be tampered with to hide theft, misuse, or non-compliance.
TAIS catches these by looking for **physically impossible patterns** in the GPS data,
like a vehicle teleporting, going 500 km/h, or reporting movement while the GPS
shows no position change.
""")
