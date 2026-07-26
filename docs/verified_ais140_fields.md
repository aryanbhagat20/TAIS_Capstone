# Verified AIS-140 Telemetry Fields

*This document records how the field set in `src/schema.py` was verified, so nobody
(including future-you in Week 6) has to re-derive it or wonder if it was guessed.*

## Why This Needed Verification

The primary ARAI/MoRTH AIS-140 specification PDF is not fetchable via automated tools
(robots-disallowed). Rather than rely on secondary blog summaries — which, on a related
project this semester, turned out to contain a factual error that wasn't caught until late —
the field set below was cross-checked against a real commercial telematics platform's
field-level AIS-140 packet parser, which has to correctly parse real deployed devices to
function as a commercial product.

## Confirmed Fields (transmitted by real AIS-140 devices to a backend)

| Field | Notes |
|---|---|
| Timestamp | |
| Latitude / Longitude / Altitude | |
| Speed | km/h |
| Heading | degrees |
| HDOP, PDOP | signal quality indicators |
| Satellite count | single aggregate number |
| Position-validity flag | |
| Harsh-acceleration / braking / cornering | **boolean flags only, not raw accelerometer data** |
| Tamper / tilt / SOS status | existing physical-tamper detection |
| Mileage (odometer) | |
| GSM cell info, battery status | |

## Explicitly NOT Available (confirmed absence — important for scoping)

- **No per-constellation breakdown.** The device fuses GPS + NavIC internally and reports one
  blended position. There is no `gps_satellite_count` vs `navic_satellite_count` split in the
  standard packet.
- **No raw continuous IMU data.** Motion events arrive as discrete boolean flags
  (harsh-braking = true/false), not a continuous accelerometer/gyroscope stream.
- **No raw per-satellite pseudoranges.** This is what rules out true RAIM (Section 1 of the
  literature survey) — RAIM needs receiver-internal data that never reaches the backend.

## Why This Matters for TAIS's Scope

This is precisely why TAIS is framed as **telemetry-level** trust assessment rather than
**receiver-level** integrity monitoring (like RAIM) — the project works with what a backend
server actually receives today, not what a receiver could theoretically expose. It's also why
GPS-vs-NavIC cross-validation is documented as a **future protocol-extension proposal**
(what a future AIS-140 revision would need to add) rather than something implemented in the
current system — the current standard simply doesn't carry that data downstream.
