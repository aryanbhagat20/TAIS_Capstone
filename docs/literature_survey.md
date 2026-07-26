# Literature Survey — TAIS (Telemetry Assessment and Integrity System)

*Week 1 draft — for Review-1. Expands the 10 references submitted at Zeroth Review into a
proper thematic narrative, and states precisely what is already solved vs. where TAIS's
contribution sits.*

---

## 1. GNSS Integrity Monitoring — The Established Foundation

The idea of checking whether a GNSS position fix can be *trusted*, rather than just accepting
it, is not new. Receiver Autonomous Integrity Monitoring (RAIM) is the foundational technique
in this space, originally developed for aviation, where redundant satellite measurements are
cross-checked against each other to detect faults. **Huang et al. (2025)**, a recent survey of
GNSS receiver autonomous integrity monitoring, confirms this remains an active research area —
including machine-learning-enhanced RAIM variants — but explicitly identifies a real-world gap:
current research over-relies on simulated or aviation-context data and lacks realistic datasets
from application contexts like automobiles. **This single finding is the direct motivation for
TAIS's dataset-and-validation focus** (Section 5 of the project one-pager). **Martin (2020)**
extends this into tightly-coupled GNSS/inertial integrity monitoring, showing that combining
satellite data with inertial sensors is an established way to strengthen integrity checks —
again, at the receiver level, which standard vehicle-tracking hardware does not expose.

## 2. GNSS Spoofing — Nature of the Threat

**Psiaki & Humphreys (2016)**, published in *Proceedings of the IEEE*, remains one of the most
cited overviews of how GNSS spoofing works and how it can be detected, covering the core attack
mechanics (an attacker broadcasting fabricated satellite signals to deceive a receiver) and the
general families of countermeasures. **Wu et al. (2020)**, an *IEEE Access* survey, catalogues
spoofing and anti-spoofing techniques more broadly across the GNSS ecosystem. Taken together,
these confirm that **spoofing detection as a general problem is mature and well-studied** — the
literature does not lack awareness of the threat, or ideas for detecting it in principle.

## 3. Sensor Fusion for Navigation and Spoofing Detection

A cluster of papers demonstrates that combining GPS with inertial sensors (accelerometer +
gyroscope, i.e. an IMU) via Kalman-filter-family techniques is a long-established engineering
pattern, not a novel one. **Fakharian, Gustafsson & Mehrfam (2011)** and **Zhang et al. (2005)**
both describe GPS/IMU integration using Kalman/unscented Kalman filtering for improved
navigation accuracy — originally motivated by accuracy during signal loss (tunnels, urban
canyons), not adversarial spoofing. **Shen et al. (2019)** and **Dhongade & Khandekar (2019)**
extend this into multi-sensor fusion and practical vehicle implementations respectively,
confirming this is commodity technique territory by now. Most directly relevant, **Dasgupta et
al. (2022)**, published in *IEEE Transactions on Intelligent Transportation Systems*, proposes a
sensor-fusion-based GNSS spoofing detection framework specifically for autonomous vehicles —
meaning the exact combination this project initially considered (GPS + IMU fusion for spoofing
detection in a vehicle context) has already been directly published.

**This is stated plainly because it matters for TAIS's framing: the algorithmic core of
GPS-IMU fusion for spoofing detection is not this project's novel contribution.**

## 4. Vehicle Telemetry Anomaly Detection (Broader Context)

**Cao et al. (2024)**, also in *IEEE Transactions on Intelligent Transportation Systems*,
addresses anomaly detection for in-vehicle networks using self-supervised learning with
vehicle-cloud collaboration. This confirms growing research interest in vehicle telemetry
anomaly detection generally — but this and similar work targets in-vehicle network traffic
(e.g., CAN bus), not the specific, standardized, already-mandated AIS-140 backend telemetry
format that is the subject of this project.

## 5. Synthesis — Where the Established Literature Stops, and Where TAIS Starts

Pulling the above together, three things are true simultaneously:

1. **RAIM and GPS/IMU sensor fusion for spoofing detection are mature, published, and in at
   least one case (Dasgupta et al., 2022) already applied to vehicles.** TAIS does not claim to
   invent a new detection algorithm.
2. **All of this prior work operates at the receiver level** — using raw satellite/pseudorange
   data, or raw continuous IMU streams, that a receiver has internal access to. Verified against
   real AIS-140 protocol documentation (see `docs/verified_ais140_fields.md`), **standard AIS-140
   devices do not transmit this raw data to a backend server** — they transmit an already-fused
   position, speed, heading, signal-quality indicators (HDOP/PDOP/satellite count), and boolean
   motion-event flags. No existing published work evaluates integrity **at this specific,
   already-standardized, telemetry level**, in the Indian AIS-140/GNSS-tolling context.
3. **Huang et al. (2025) explicitly flags a lack of real-world automotive datasets** for GNSS
   integrity work — a gap this project's own data-collection/simulation effort directly
   addresses, regardless of which detection technique is used on top of it.

**TAIS's contribution, precisely stated:** a telemetry-level (not receiver-level) trust-scoring
system, built and evaluated on a real dataset generated specifically for this project, targeting
a specific, currently-unaddressed, India-specific regulatory and infrastructure context — not a
new spoofing-detection algorithm.

---

## Open Item — To Verify Before Final Report

Reference #7 (Shen, Huang, Liu, Chen, **Weijinya, U.**, & Shi, 2019) has an author name
("Weijinya, U.") that looks like a possible OCR/transcription artifact rather than a standard
name format. **Action for later this week:** open the IEEEXplore page directly and confirm the
exact author list before this survey (or the final dissertation report) is considered final.

## Reference List (APA), Grouped by Theme

**Integrity Monitoring Foundations**
- Huang, Z., Mou, W., Wang, R., Li, P., Lyu, Z., & Ou, G. (2025). A survey of GNSS receiver autonomous integrity monitoring: Research status and opportunities. *Frontiers in Physics, 13*, Article 1567301.
- Martin, T. (2020). Advanced receiver autonomous integrity monitoring in tightly integrated GNSS/Inertial systems. In *2020 DGON Inertial Sensors and Systems (ISS)* (pp. 1–20).

**Spoofing Threat & Detection**
- Psiaki, M. L., & Humphreys, T. E. (2016). GNSS spoofing and detection. *Proceedings of the IEEE, 104*(6), 1258–1270.
- Wu, Z., Zhang, Y., Yang, Y., Liang, C., & Liu, R. (2020). Spoofing and anti-spoofing technologies of Global Navigation Satellite System: A survey. *IEEE Access, 8*, 165444–165496.

**Sensor Fusion (GPS/IMU/INS)**
- Dasgupta, S., Rahman, M., Islam, M., & Chowdhury, M. (2022). A sensor fusion-based GNSS spoofing attack detection framework for autonomous vehicles. *IEEE Transactions on Intelligent Transportation Systems, 23*(12), 23559–23572.
- Fakharian, A., Gustafsson, T., & Mehrfam, M. (2011). Adaptive Kalman filtering based navigation: An IMU/GPS integration approach. In *Proceedings of the IEEE International Conference on Networking, Sensing and Control (ICNSC)* (pp. 181–185).
- Zhang, P., Gu, J., Milios, E., & Huynh, P. (2005). Navigation with IMU/GPS/digital compass with unscented Kalman filter. In *Proceedings of the IEEE International Conference on Mechatronics and Automation* (Vol. 3, pp. 1497–1502).
- Shen, C., Huang, C., Liu, J., Chen, X., Weijinya, U., & Shi, G. (2019). Integrated navigation accuracy improvement algorithm based on multi-sensor fusion. In *2019 IEEE 2nd International Conference on Micro/Nano Sensors for AI, Healthcare, and Robotics (NSENS)* (pp. 1–5). *(Author name to verify — see Open Item above.)*
- Dhongade, A. P., & Khandekar, M. A. (2019). GPS and IMU integration on an autonomous vehicle using Kalman filter (LabView tool). In *2019 International Conference on Intelligent Computing and Control Systems (ICCS)* (pp. 1135–1139).

**Vehicle Telemetry Anomaly Detection (Broader Context)**
- Cao, J., Di, X., Liu, X., Li, J., Li, Z., & Zhao, L. (2024). Anomaly detection for in-vehicle network using self-supervised learning with vehicle-cloud collaboration update. *IEEE Transactions on Intelligent Transportation Systems, 25*(7), 7454–7466.
