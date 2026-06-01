# Running Performance Metrics: Research & First Principles

**Compiled:** 2026-03-04
**Purpose:** Source documentation for Domos metric implementations. For each metric: original source, formula, implementation notes, and known limitations.

---

## Table of Contents

1. [VO2Max Estimation](#1-vo2max-estimation)
2. [VDOT (Jack Daniels)](#2-vdot-jack-daniels)
3. [Race Time Prediction](#3-race-time-prediction)
4. [Lactate Threshold Estimation](#4-lactate-threshold-estimation)
5. [Training Stress Score (TSS / hrTSS)](#5-training-stress-score-tss--hrtss)
6. [ATL / CTL / TSB (Performance Manager)](#6-atl--ctl--tsb-performance-manager)
7. [Running Economy](#7-running-economy)
8. [Grade-Adjusted Pace (GAP)](#8-grade-adjusted-pace-gap)
9. [Cadence and Stride Length](#9-cadence-and-stride-length)

---

## 1. VO2Max Estimation

### What it measures
VO2max (maximal oxygen uptake) is the maximum rate at which the body can consume oxygen during exhaustive exercise. Units: mL·kg⁻¹·min⁻¹. It is the gold-standard measure of aerobic capacity.

---

### 1a. Åstrand-Ryhming Submaximal Test

**Original Source (freely available paper):**
> Åstrand, P.-O. & Ryhming, I. (1954). "A Nomogram for Calculation of Aerobic Capacity (Physical Fitness) From Pulse Rate During Submaximal Work." *Journal of Applied Physiology*, 7(2), 218–221.
> DOI: [10.1152/jappl.1954.7.2.218](https://journals.physiology.org/doi/abs/10.1152/jappl.1954.7.2.218)
> PubMed: PMID 13211501

**Revisit paper (validation/correction):**
> Åstrand, I. (1960). "Aerobic work capacity in men and women with special reference to age." *Acta Physiologica Scandinavica*, 49(Suppl 169), 1–92.

**Method:**
The test requires exercising at a steady-state submaximal workload (originally a step test or cycle ergometer) that elicits a heart rate between 125–170 bpm. A nomogram maps the heart rate at that workload to an estimated VO2max. The 1954 paper was based on data from 50 men and 62 women.

**Formula (approximate, derived from nomogram regression):**
```
VO2max (L/min) = workload_VO2 / (HR_submaximal / HR_max)
```
Because maximal heart rate is not directly measured, the nomogram uses an age-correction factor (Åstrand 1960 revision). The correction factor k decreases from ~1.0 at age 20–25 to ~0.65 at age 65.

**Limitations:**
- Overestimates VO2max in untrained populations by ~10–15%.
- Requires knowledge of true HRmax for best accuracy; age-predicted HRmax introduces error.
- Validated primarily on Scandinavian athletes; population generalizability is uncertain.

**Freely implementable:** Yes — the nomogram regression is in the public domain.

---

### 1b. Cooper 12-Minute Run Test

**Original Source (freely available paper):**
> Cooper, K.H. (1968). "A means of assessing maximal oxygen intake. Correlation between field and treadmill testing." *JAMA*, 203(3), 201–204.
> DOI: [10.1001/jama.1968.03140030033008](https://doi.org/10.1001/jama.1968.03140030033008)
> PubMed: PMID 5694044

**Formula:**
```
VO2max (mL·kg⁻¹·min⁻¹) = (distance_km × 1000 − 504.9) / 44.73
```
Equivalently:
```
VO2max = (22.351 × distance_km) − 11.288
```
Where `distance_km` is the total distance covered in 12 minutes.

**Cooper (1968) validation:** r = 0.90 between VO2max and 12-min run distance in military personnel.

**Limitations:**
- Developed on military males; less accurate for women and sedentary individuals.
- Pacing strategy significantly affects results.
- Running surface, weather, and motivation introduce variance.
- Correlation degrades in populations outside the original validation sample.

**Freely implementable:** Yes.

---

### 1c. GPS Watch / Firstbeat Algorithm

**Source (technical white paper, freely available):**
> Firstbeat Technologies Ltd. (2017). "Automated Fitness Level (VO2max) Estimation with Heart Rate and Speed Data." White paper.
> URL: https://assets.firstbeat.com/firstbeat/uploads/2017/06/white_paper_VO2max_30.6.2017.pdf

**Also cite the patent:**
> US Patent US20110040193A1 — "Fitness test" (Firstbeat Technologies, filed 2009).

**Method:**
The algorithm exploits the linear relationship between running speed (V) and oxygen consumption (VO2) at steady state:

```
VO2 = a × V + b
```

where `a` and `b` are individual calibration constants. Heart rate at submaximal intensities is used as a proxy for VO2 via the linear HR–VO2 relationship:

```
VO2 / VO2max ≈ (HR − HR_rest) / (HR_max − HR_rest)   [heart rate reserve fraction]
```

The algorithm:
1. Segments a run into periods of stable HR and speed.
2. Computes the correlation between HR and speed for each segment; discards low-quality segments.
3. Linearly extrapolates the HR-speed relationship to predicted HRmax to estimate VO2max.
4. Weights segments by reliability and averages across the run.

**HRmax estimation:** Garmin/Firstbeat use an age-predicted HRmax (e.g., 208 − 0.7 × age, from Tanaka et al. 2001) unless the user has established a true HRmax from a maximal effort. This is the primary source of individual error.

**Limitations:**
- Aggregate accuracy is ±3.5 mL·kg⁻¹·min⁻¹ (~1 MET) on average, but individual error can be much larger.
- Age-predicted HRmax is unreliable for some individuals (±10–20 bpm).
- Not valid during interval sessions or non-steady-state running.
- Proprietary weights and exact implementation are not fully public.

**Freely implementable:** The underlying linear extrapolation principle is free; the exact Firstbeat implementation is proprietary (patented).

---

### 1d. Simple Resting HR Formula

**Source:** Commonly attributed to Fox (1975); widely reproduced:
```
VO2max ≈ 15 × (HR_max / HR_rest)
```
A rough heuristic; accuracy is poor (r ≈ 0.60–0.70). Not recommended for precision use.

---

## 2. VDOT (Jack Daniels)

### What it measures
VDOT is a performance-equivalent aerobic index derived from actual race results. It represents the VO2max that would be predicted for an athlete running a given time for a given distance, assuming a standard ("generic") running economy curve. It is not a true VO2max measurement.

### Original Source (book — user must procure)
> Daniels, J. & Gilbert, J. (1979). *Oxygen Power: Performance Tables for Distance Runners.*
> Self-published. Available via used book sellers and university libraries.

The equations were subsequently reproduced and explained in:
> Daniels, J. (2005, 2014, 2021). *Daniels' Running Formula.* 3rd ed. Human Kinetics, Champaign, IL.
> ISBN: 978-1-4925-9486-4 (3rd ed.) — **Book, user must procure.**

### The Two Regression Equations

The VDOT system rests on two empirically-derived regression equations fit to laboratory and competition data:

**Equation 1 — VO2 as a function of velocity:**
```
VO2(V) = −4.60 + 0.182258·V + 0.000104·V²
```
Where V = running velocity in m·min⁻¹.

**Equation 2 — Fraction of VO2max sustainable as a function of duration:**
```
%VO2max(T) = 0.8 + 0.1894393·e^(−0.012778·T) + 0.2989558·e^(−0.1932605·T)
```
Where T = race duration in minutes.

**Combined VDOT formula:**
```
VDOT = VO2(V) / %VO2max(T)
     = (−4.60 + 0.182258·V + 0.000104·V²)
       / (0.8 + 0.1894393·e^(−0.012778·T) + 0.2989558·e^(−0.1932605·T))
```

**Interpretation:** Given a race time T at distance D (which determines V = D/T), VDOT is the effective VO2max index. Training paces are then prescribed as percentages of VDOT back-solved to velocities.

### Copyright / Implementation Status
- The **VDOT tables** as published are copyrighted by Jack Daniels / The Run SMART Project, LLC.
- The **underlying mathematical formulas** cannot be copyrighted (mathematical facts are not copyrightable under US law).
- "VDOT" is a **registered trademark** of The Run SMART Project, LLC — using the name commercially requires caution.
- **Freely implementable:** Yes, the equations may be freely implemented in software. Use of the "VDOT" name may require care; calling it "performance index" or "Daniels-Gilbert index" is safer.

### Limitations
- The %VO2max curve is a population average, not individualized. Elite runners can sustain higher fractions at marathon pace; beginners sustain lower fractions.
- Running economy is assumed constant ("generic economy curve") — athletes with unusually high or low economy relative to their VO2max will get inaccurate training pace prescriptions.
- Tables were originally calibrated on competitive runners; predictive accuracy degrades for very slow or very fast athletes.
- A single recent race time is assumed to be fully maximal and well-paced. Poor pacing or illness skews the output.

---

## 3. Race Time Prediction

### 3a. Riegel Formula

**Original Source (freely available paper):**
> Riegel, P.S. (1981). "Athletic Records and Human Endurance." *American Scientist*, 69(3), 285–290.
> PubMed: PMID 7235349
> ADS: [1981AmSci..69..285R](https://ui.adsabs.harvard.edu/abs/1981AmSci..69..285R/abstract)

An earlier version appeared in:
> Riegel, P.S. (1977). "Athletic records and human endurance." *Runner's World* (popularized form).

**Formula:**
```
T₂ = T₁ × (D₂ / D₁)^1.06
```
Where:
- T₁ = known race time
- D₁ = known race distance
- D₂ = target distance
- T₂ = predicted time for D₂
- Exponent 1.06 = empirically fit fatigue exponent

**How the exponent was derived:**
Riegel fit a power law to world-record performances across distances from ~200 m to several hundred miles:
```
T = a × D^b
```
He found b ≈ 1.06 fits aerobic endurance events lasting 3.5–230 minutes across running, swimming, and walking. The exponent reflects the fact that pace slows with distance (fatigue/economy degradation).

**Validity range:** Best for distances and durations within roughly 2× of the base distance. Accuracy degrades with large extrapolations (e.g., predicting marathon from 5K).

**Freely implementable:** Yes. Simple formula, public domain.

**Limitations:**
- Assumes physiological similarity across distances; in practice, specialists at short vs. long events have different fatigue curves.
- The 1.06 exponent was fit to world records (elite athletes). Recreational runners, particularly at the marathon, may have a higher effective exponent (≥1.08).
- Does not account for training status, terrain, weather, or race-day conditions.
- Systematically overestimates marathon times for slower runners (who struggle more with fatigue at that distance).

---

### 3b. Cameron Formula

**Source:**
David Cameron (unpublished/informal; widely disseminated online). Cameron performed a nonlinear regression on world-record and national-record performances across distances from 400 m to 50 miles.

**Formula:**
```
Speed (m/s) = a / (b + c × ln(D))
```
where a, b, c are regression constants. Alternatively expressed in terms of pace.

The formula is described at: https://www.had2know.org/sports/race-performance-prediction-calculator-cameron.html

**Status:** No formal peer-reviewed publication found. The Cameron formula is an empirical fit shared informally and replicated across running tools. It is generally considered more accurate than Riegel for longer distances (half-marathon to ultramarathon).

**Freely implementable:** Yes.

**Limitations:**
- No peer-reviewed validation paper.
- Works best for elite and sub-elite athletes whose training aligns with world-record performance curves.

---

### 3c. VDOT-Based Prediction (Daniels-Gilbert)

The VDOT equations (Section 2) can also be used for race prediction: given VDOT from one performance, invert the equation to find the time T₂ at any target distance D₂. This tends to be more physiologically grounded than the Riegel power law. See Section 2 for sources.

---

## 4. Lactate Threshold Estimation

### What it measures
Lactate threshold (LT), also called the anaerobic threshold (AT) or ventilatory threshold (VT), is the exercise intensity above which blood lactate accumulates faster than it can be cleared. It is a critical performance determinant for endurance events. Multiple operational definitions exist (LT1, LT2, MLSS, OBLA, VT1, VT2).

**Comprehensive review of methods:**
> Svedahl, K. & MacIntosh, B.R. (2003). "Anaerobic Threshold: The Concept and Methods of Measurement." *Canadian Journal of Applied Physiology*, 28(2), 299–323.
> DOI: [10.1139/h03-023](https://cdnsciencepub.com/doi/10.1139/h03-023) — **freely available**

---

### 4a. Conconi Test (Heart Rate Deflection)

**Original Source (freely available paper):**
> Conconi, F., Ferrari, M., Ziglio, P.G., Droghetti, P., & Codeca, L. (1982). "Determination of the anaerobic threshold by a noninvasive field test in runners." *Journal of Applied Physiology: Respiratory, Environmental and Exercise Physiology*, 52(4), 869–873.
> DOI: [10.1152/jappl.1982.52.4.869](https://journals.physiology.org/doi/abs/10.1152/jappl.1982.52.4.869)
> PubMed: PMID 7085420

**Method:**
During a continuous incremental treadmill or track protocol, heart rate is plotted against running speed. At submaximal intensities, HR increases linearly with speed. The Conconi test identifies the **heart rate deflection point (HRd)** — where this linear relationship breaks down — as a non-invasive proxy for lactate threshold.

Protocol: Start at 12–14 km/h; increase speed by 0.5 km/h every 200 m (track) or every minute (treadmill). Plot HR vs. speed; identify the departure from linearity.

**Critical validity issues:**
> Kuipers, H. et al. (1988). "Variability of aerobic performance in the laboratory and its physiologic correlates." *International Journal of Sports Medicine*, 9(3), 197–201.

Multiple studies failed to reproduce the deflection reliably. Key criticisms:
- The deflection is not consistently detectable (found in ~50–70% of subjects in most studies).
- The original Conconi (1982) blood lactate data were collected in a separate session with a different protocol — the simultaneous coincidence was not demonstrated.
- HR deflection corresponds to the onset of HR plateau (approaching HRmax) more than to lactate dynamics.

**Verdict:** The Conconi test is widely considered methodologically flawed and not a valid proxy for LT in most subjects. Avoid using it as a primary LT estimator.

**Freely implementable:** Yes, but validity is poor.

---

### 4b. Friel 30-Minute Field Test (LTHR)

**Source (practitioner method, not a peer-reviewed paper):**
> Friel, J. (originally published 2000 in *Inside Triathlon* magazine; formalized in):
> Friel, J. (2009). *The Triathlete's Training Bible.* 3rd ed. VeloPress.
> Friel, J. (2012). *The Cyclist's Training Bible.* 5th ed. VeloPress.
> Available at: https://joefrieltraining.com/determining-your-lthr/ — **Book (user must procure).**

**Method:**
1. Perform a solo, maximal 30-minute time trial (running or cycling).
2. Press the lap button at the 10-minute mark.
3. Record the **average heart rate for the final 20 minutes**.
4. That average HR is used as an estimate of Lactate Threshold Heart Rate (LTHR).

**Rationale:** A 30-minute maximal effort corresponds approximately to the intensity sustainable at LT2 (the second lactate threshold / maximal lactate steady state). The first 10 minutes are excluded to avoid the warm-up HR elevation transient.

**Training zones (Friel running zones based on %LTHR):**
| Zone | %LTHR |
|------|-------|
| Z1   | <85%  |
| Z2   | 85–89% |
| Z3   | 90–94% |
| Z4   | 95–99% |
| Z5a  | 100–102% |
| Z5b  | 103–106% |
| Z5c  | >106% |

**Limitations:**
- No formal peer-reviewed validation against blood lactate measurements for this exact protocol.
- Requires a truly maximal, solo effort (social or competitive context inflates HR, terrain and heat affect results).
- LTHR is sport-specific: cycling LTHR is typically 5–10 bpm lower than running LTHR.
- 30 minutes may not correspond to MLSS for all fitness levels.

**Freely implementable:** Yes — the protocol is a publicly described field method.

---

### 4c. Coggan's Functional Threshold Power / Pace

For cycling, Coggan proposed a similar 20-minute maximal test, multiplying the result by 0.95 to estimate FTP. For running, the analogous concept is **Functional Threshold Pace (FTPa)** — the pace sustainable for approximately one hour. TrainingPeaks uses FTPa to calculate rTSS (see Section 5).

**Source (book — user must procure):**
> Allen, H. & Coggan, A. (2010). *Training and Racing with a Power Meter.* 2nd ed. VeloPress.
> ISBN: 978-1-934030-79-5

**Freely implementable:** Yes.

---

## 5. Training Stress Score (TSS / hrTSS)

### 5a. Banister TRIMP (Training IMPulse)

**Original Source — foundational systems model paper (freely available):**
> Calvert, T.W., Banister, E.W., Savage, M.V., & Bach, T. (1976). "A Systems Model of the Effects of Training on Physical Performance." *IEEE Transactions on Systems, Man, and Cybernetics*, 6(2), 94–102.
> DOI: [10.1109/TSMC.1976.5409179](https://doi.org/10.1109/TSMC.1976.5409179)

**TRIMP formula paper (book chapter — user must procure):**
> Banister, E.W. (1991). "Modeling Elite Athletic Performance." In: MacDougall, J.D., Wenger, H.A., & Green, H.J. (Eds.), *Physiological Testing of Elite Athletes*, pp. 403–424. Human Kinetics, Champaign, IL.

**Also published as a journal paper:**
> Morton, R.H., Fitz-Clarke, J.R., & Banister, E.W. (1990). "Modeling human performance in running." *Journal of Applied Physiology*, 69(3), 1171–1177.
> DOI: [10.1152/jappl.1990.69.3.1171](https://journals.physiology.org/doi/abs/10.1152/jappl.1990.69.3.1171)

**TRIMP Formula:**
```
TRIMP = Duration (min) × ΔHR_ratio × e^(b × ΔHR_ratio)
```
Where:
- `ΔHR_ratio = (HR_exercise − HR_rest) / (HR_max − HR_rest)` — heart rate reserve fraction
- `b` = 1.92 for men, 1.67 for women (empirically derived weighting constants)
- `e` = Euler's number

The exponential weighting factor means that high-intensity exercise is penalized non-linearly — a session at 90% HRR contributes disproportionately more TRIMP than one at 50% HRR. This reflects the non-linear physiological cost of high-intensity work.

**Freely implementable:** Yes.

---

### 5b. Coggan TSS (Power-Based, Cycling)

**Source (book — user must procure):**
> Allen, H. & Coggan, A. (2010). *Training and Racing with a Power Meter.* 2nd ed. VeloPress.

**Also described in:**
> TrainingPeaks blog: "The Development of the Training Stress Score." https://www.trainingpeaks.com/blog/the-development-of-the-training-stress-score/

**TSS Formula:**
```
TSS = (T_seconds × NP × IF) / (FTP × 3600) × 100
```
Equivalently:
```
TSS = (T_seconds × NP²) / (FTP² × 36)
```
Where:
- `T_seconds` = workout duration in seconds
- `NP` = Normalized Power (4th-power rolling average of 30-second power)
- `IF` = Intensity Factor = NP / FTP
- `FTP` = Functional Threshold Power (watts)

**Calibration:** TSS = 100 corresponds exactly to one hour at FTP (IF = 1.0). This is the defining constraint.

**Normalized Power formula:**
1. Compute a rolling 30-second average of power data.
2. Raise each value to the 4th power.
3. Average all 4th-power values.
4. Take the 4th root.

The 4th-power transform reflects the non-linear metabolic cost of high-intensity efforts.

**Freely implementable:** Yes — Coggan has made the formulas public. TrainingPeaks trademarked "TSS" in software context but cannot copyright the formula.

---

### 5c. hrTSS (Heart Rate–Based TSS)

**Source:** TrainingPeaks proprietary implementation, based on Banister TRIMP principles. Described at:
https://help.trainingpeaks.com/hc/en-us/articles/204071944-Training-Stress-Scores-TSS-Explained

**Method:**
hrTSS converts heart-rate-based TRIMP into TSS-equivalent units by normalizing against a reference effort. TrainingPeaks uses time in heart rate zones (derived from LTHR) with zone-specific TSS-per-hour multipliers, rather than the continuous exponential TRIMP formula.

**Approximate zone-TSS/hour table (from TrainingPeaks):**
| Zone | %LTHR | TSS/hour |
|------|-------|----------|
| Z1   | <85%  | ~20–30   |
| Z2   | 85–89%| ~40–50   |
| Z3   | 90–94%| ~60–70   |
| Z4   | 95–99%| ~80–90   |
| Z5   | >100% | ~100+    |

**Note:** The exact multipliers are TrainingPeaks' proprietary mapping and may not be publicly documented precisely. The principle (zone-weighted time → TSS) is freely reproducible; the exact constants require reverse-engineering or approximation.

**rTSS (Running TSS):** Uses pace and FTPa (functional threshold pace) analogously to power-based TSS:
```
rTSS = (T_seconds × NGP × IF_pace) / (FTPa × 3600) × 100
```
Where NGP = Normalized Graded Pace (adjusts pace for elevation).

**Freely implementable:** The formulas are public. "TSS," "hrTSS," "rTSS" are TrainingPeaks terms; the underlying math can be reproduced.

---

## 6. ATL / CTL / TSB (Performance Manager)

### What they measure
- **CTL (Chronic Training Load)** — "Fitness": long-term accumulated training stress. Modeled as an exponentially weighted moving average (EWMA) with a ~42-day time constant.
- **ATL (Acute Training Load)** — "Fatigue": recent training stress. EWMA with a ~7-day time constant.
- **TSB (Training Stress Balance)** — "Form": CTL − ATL. Positive = fresh/undertrained; negative = fatigued.

### Original Sources

**Foundational systems model (freely available paper):**
> Calvert, T.W., Banister, E.W., Savage, M.V., & Bach, T. (1976). "A Systems Model of the Effects of Training on Physical Performance." *IEEE Transactions on Systems, Man, and Cybernetics*, 6(2), 94–102.
> DOI: [10.1109/TSMC.1976.5409179](https://doi.org/10.1109/TSMC.1976.5409179)

**Mathematical elaboration (freely available paper):**
> Morton, R.H., Fitz-Clarke, J.R., & Banister, E.W. (1990). "Modeling human performance in running." *Journal of Applied Physiology*, 69(3), 1171–1177.
> DOI: [10.1152/jappl.1990.69.3.1171](https://journals.physiology.org/doi/abs/10.1152/jappl.1990.69.3.1171)

**Book chapter formalizing TRIMP + model (book — user must procure):**
> Banister, E.W. (1991). "Modeling Elite Athletic Performance." In: MacDougall, J.D., Wenger, H.A., & Green, H.J. (Eds.), *Physiological Testing of Elite Athletes*, pp. 403–424. Human Kinetics.

**Busso variable dose-response refinement (freely available paper):**
> Busso, T. (2003). "Variable Dose-Response Relationship between Exercise Training and Performance." *Medicine & Science in Sports & Exercise*, 35(7), 1188–1195.
> DOI: [10.1249/01.MSS.0000074465.13922.B9](https://journals.lww.com/acsm-msse/Fulltext/2003/07000/Variable_Dose_Response_Relationship_between.18.aspx)
> PubMed: PMID 12840641

**Coggan's TSB simplification:** Coggan adapted the Banister impulse-response model into the CTL/ATL/TSB framework used by TrainingPeaks. This was a practical implementation rather than a separate academic publication; it is described in the Allen & Coggan book (Section 5b).

### Recurrence Equations

The EWMA formulas for each day:
```
CTL_today = CTL_yesterday × e^(−1/τ_CTL) + TSS_today × (1 − e^(−1/τ_CTL))
ATL_today = ATL_yesterday × e^(−1/τ_ATL) + TSS_today × (1 − e^(−1/τ_ATL))
TSB_today = CTL_today − ATL_today
```
Default time constants:
- τ_CTL = 42 days (fitness decay constant)
- τ_ATL = 7 days (fatigue decay constant)

These time constants were chosen empirically by Banister/Coggan based on approximate physiological adaptation and recovery timescales. They can be individually tuned.

**Banister's original "performance" equation:**
```
p(t) = p₀ + k₁·g(t) − k₂·h(t)
```
Where:
- `p(t)` = modeled performance at time t
- `p₀` = baseline performance
- `g(t)` = fitness (positive adaptation, long time constant ~45 days)
- `h(t)` = fatigue (negative adaptation, short time constant ~15 days)
- `k₁`, `k₂` = individual gain coefficients

The CTL/ATL framework is a simplified version that replaces `g(t)` with CTL and `h(t)` with ATL, and drops the explicit performance model (using TSB as a surrogate for readiness).

### Limitations
- Time constants are population averages; optimal individual constants vary significantly.
- The model assumes TSS is a valid proxy for physiological training stress across all workout types (false for strength work, extreme heat, illness).
- TSB does not account for training monotony or sequence effects.
- The linear relationship between TSB and "form" breaks down at extremes (very high CTL athletes can tolerate larger ATL).
- Performance is not directly predicted — TSB is a heuristic indicator, not a validated performance predictor.

**Freely implementable:** Yes — the equations are public domain.

---

## 7. Running Economy

### What it measures
Running economy (RE) is the oxygen cost of running at a given submaximal speed. It is expressed as:
- **VO2 at a fixed speed** (e.g., mL·kg⁻¹·min⁻¹ at 16 km/h), or
- **Energy cost per unit distance** (J·kg⁻¹·m⁻¹ or mL·kg⁻¹·km⁻¹)

A runner with "good economy" uses less oxygen at a given speed than one with "poor economy."

### Original / Foundational Sources

**Demonstration that RE predicts performance better than VO2max in homogeneous groups (freely available paper):**
> Conley, D.L. & Krahenbuhl, G.S. (1980). "Running economy and distance running performance of highly trained athletes." *Medicine & Science in Sports & Exercise*, 12(5), 357–360.
> DOI: [10.1249/00005768-198025000-00010](https://doi.org/10.1249/00005768-198025000-00010)
> PubMed: PMID 7453514

This landmark study found r = −0.12 between VO2max and 10 km performance within a homogeneous elite group, but r = 0.79–0.83 between running economy (VO2 at fixed speeds) and 10 km time. RE explained 65.4% of variance in performance.

**Comprehensive review — measurement, norms, determinants (freely available paper):**
> Barnes, K.R. & Kilding, A.E. (2015). "Running economy: measurement, norms, and determining factors." *Sports Medicine – Open*, 1, 8.
> DOI: [10.1186/s40798-015-0007-y](https://link.springer.com/article/10.1186/s40798-015-0007-y) — Open access

**Beyond VO2 — energy cost perspective (freely available paper):**
> Fletcher, J.R., Esau, S.P., & MacIntosh, B.R. (2009). "Economy of running: beyond the measurement of oxygen uptake." *Journal of Applied Physiology*, 107(6), 1918–1922.
> DOI: [10.1152/japplphysiol.00307.2009](https://journals.physiology.org/doi/full/10.1152/japplphysiol.00307.2009)

### Formula / Measurement

**Standard measurement protocol:**
1. Athlete runs at a fixed submaximal speed on a level treadmill (typically 14–18 km/h for trained runners) for ≥5 minutes to reach metabolic steady state.
2. Expired gas is collected (metabolic cart). VO2 is measured at steady state.
3. RE = VO2 (mL·kg⁻¹·min⁻¹) at that speed, or converted to energy cost:

```
Energy cost (J·kg⁻¹·m⁻¹) = VO2 (mL·kg⁻¹·min⁻¹) × caloric equivalent / speed (m·min⁻¹)
```
Caloric equivalent ≈ 20.9 J·mL O₂⁻¹ (for RER ≈ 0.90).

**Relationship to performance:**
```
Performance ≈ f(VO2max, %VO2max at LT, Running Economy)
Velocity at LT = VO2max × %VO2max_at_LT / VO2_per_meter_at_speed
```
Combining all three factors: velocity at the lactate threshold expressed in m/min = VO2max × (fraction at LT) / (oxygen cost per meter). This is the practical "master equation" of distance running performance.

**Typical RE values (from Barnes & Kilding 2015):**
| Population | VO2 at 16 km/h (mL·kg⁻¹·min⁻¹) |
|------------|----------------------------------|
| Elite men  | 44–52 |
| Elite women| 45–55 |
| Recreational| 55–70 |

### Limitations
- RE measurement requires laboratory metabolic equipment; no validated simple field test exists.
- RE is speed-specific — it must be measured at the same speed for comparisons.
- Body weight normalization by ratio scaling (per kg) disadvantages heavier runners; allometric scaling is more appropriate but less common.
- RE varies with fatigue, nutrition, altitude, shoes, terrain.
- RE can vary by up to 30% within athletes of identical VO2max.

**Freely implementable:** RE is a measured quantity, not a formula to implement per se. The calculation from raw VO2 data is standard and public domain.

---

## 8. Grade-Adjusted Pace (GAP)

### What it measures
GAP converts actual running pace on variable terrain to an equivalent flat-ground pace, enabling fair comparison of effort across hilly and flat runs.

### Original Academic Source

**Minetti energy cost polynomial (freely available paper):**
> Minetti, A.E., Moia, C., Roi, G.S., Susta, D., & Ferretti, G. (2002). "Energy cost of walking and running at extreme uphill and downhill slopes." *Journal of Applied Physiology*, 93(3), 1039–1046.
> DOI: [10.1152/japplphysiol.01177.2001](https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001)
> PubMed: PMID 12183501

**Study design:** 10 runners on a treadmill at slopes from −45% to +45% grade. Energy cost (J·kg⁻¹·m⁻¹) was measured via indirect calorimetry.

**Minetti polynomial (energy cost of running as a function of grade):**
```
Cr(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² + 19.5i + 3.6
```
Where:
- `Cr` = energy cost of running (J·kg⁻¹·m⁻¹)
- `i` = fractional grade (0.01 = 1% grade; negative = downhill)

**GAP implementation:**
```
effort_ratio = Cr(grade) / Cr(0)   [where Cr(0) = 3.6 J·kg⁻¹·m⁻¹ on flat]
GAP = actual_pace / effort_ratio
```
A faster GAP than actual pace on uphills reflects the extra effort expended.

### Strava's Implementation

**Original Strava model:** Used the Minetti (2002) polynomial directly.

**Improved Strava model (data-driven refinement):**
> Robb, D. (2017). "An Improved GAP Model." Strava Engineering Blog. https://medium.com/strava-engineering/an-improved-gap-model-8b07ae8886c3

Strava found the Minetti model worked well for uphill but significantly overestimated the benefit of downhill running (the lab polynomial suggested flat-equivalent pace much slower than actual downhill pace). Using their large database of user activities and race results, Strava derived a corrected empirical curve particularly for downhill grades:
- The downhill GAP benefit peaks at approximately −10% grade, then diminishes.
- Very steep downhills (>−20%) carry braking cost that partially negates the grade benefit.

The exact coefficients of Strava's revised polynomial are not publicly documented.

### Limitations
- Minetti (2002) was conducted in a lab on a treadmill with 10 elite runners — may not generalize to trails, varying surfaces, or fatigue states.
- GAP does not account for technical terrain difficulty (roots, rocks, mud).
- Individual biomechanics affect uphill and downhill efficiency significantly.
- Short-segment GAP calculations are noisy due to GPS elevation error.

**Freely implementable:** The Minetti polynomial is from a public paper. Strava's refinement is proprietary. A reasonable implementation can use Minetti (2002) directly, with the caveat that downhill predictions are less accurate.

---

## 9. Cadence and Stride Length

### What they measure
- **Cadence** (step rate): number of foot strikes per minute (steps/min) or strides/min.
- **Stride length**: distance covered per complete gait cycle (both feet striking once each).
- **Relationship:** `Running speed = cadence (strides/min) × stride length (m)`

### The "180 spm" Observation

**Source (observation, not a formal study):**
> Daniels, J. (1984, unpublished observation). At the 1984 Los Angeles Olympics, Jack Daniels counted the stride rates of elite distance runners using a stopwatch. Of 46 competitors observed, only one ran below 180 steps/min (one athlete at 176 spm).

This observation was popularized in:
> Daniels, J. (2005). *Daniels' Running Formula.* Human Kinetics. — **Book, user must procure.**

**Important caveat:** This was not a controlled study. The athletes were running at race pace (fast), which naturally produces higher cadences. The "180 rule" conflates optimal cadence with the cadence used by fast athletes running fast.

### Key Research Papers

**Heiderscheit et al. — Biomechanical effects of step rate manipulation (freely available paper):**
> Heiderscheit, B.C., Chumanov, E.S., Michalski, M.P., Wille, C.M., & Ryan, M.B. (2011). "Effects of Step Rate Manipulation on Joint Mechanics during Running." *Medicine & Science in Sports & Exercise*, 43(2), 296–302.
> DOI: [10.1249/MSS.0b013e3181ebedf4](https://doi.org/10.1249/MSS.0b013e3181ebedf4)
> PMC: [PMC3022995](https://pmc.ncbi.nlm.nih.gov/articles/PMC3022995/)

**Key findings:**
- 45 recreational runners tested at preferred cadence and ±5%, ±10% of preferred.
- A 10% increase in step rate reduced energy absorption at the knee by 34%.
- RPE increased by 6% with a 10% cadence increase.
- A **5–10% increase above preferred** (not a universal 180 target) is the evidence-based recommendation.

**Systematic review on stride frequency/length (freely available paper):**
> Heiderscheit, B.C. et al. (2014). "Influence of stride frequency and length on running mechanics: a systematic review." *Physical Therapy in Sport*, 15(3), 153–162.
> PubMed: PMID 24790690

**Individual optimal step frequency paper (freely available paper):**
> Ogueta-Alday, A. et al. (2020). "Individual optimal step frequency during outdoor running." *European Journal of Sport Science*, 20(3), 323–331.
> DOI: [10.1080/17461391.2019.1626911](https://www.tandfonline.com/doi/full/10.1080/17461391.2019.1626911)

### Formulas

**Speed–cadence–stride length relationship:**
```
v (m/s) = (cadence_steps_per_min / 60) × stride_length_m / 2
```
(Divide cadence by 2 if counting steps rather than full strides, since one stride = 2 steps.)

Or equivalently:
```
stride_length (m) = speed (m/s) × 60 × 2 / cadence (steps/min)
```

**Optimal cadence (individualized, Heiderscheit 2011):**
There is no single universal optimal cadence. The research-supported approach is:
- Determine an individual's **preferred cadence** at a given speed.
- If injury risk is a concern, increase by **5–10%** above preferred.
- Optimal cadence scales with speed — higher speeds naturally require higher cadences.

**Typical range:** 160–190 steps/min across recreational and elite runners at moderate paces. Below ~155 spm typically indicates overstriding.

### Limitations
- "180 spm" is an observation from elite race conditions, not a universal prescription.
- Imposed cadence changes >10% above preferred increase metabolic cost.
- Optimal cadence varies by individual anatomy, leg length, and running speed.
- Very short-term interventions may increase injury risk before adaptation.
- GPS watches that measure cadence via accelerometer may confuse arm swing cadence with foot strike cadence.

**Freely implementable:** The speed/cadence/stride formula is basic arithmetic. No proprietary elements.

---

## Summary Table

| Metric | Primary Source | Source Type | Freely Implementable |
|--------|---------------|-------------|----------------------|
| VO2max (Åstrand-Ryhming) | Åstrand & Ryhming, 1954, *J Appl Physiol* | **Paper** (freely available) | Yes |
| VO2max (Cooper test) | Cooper, 1968, *JAMA* | **Paper** (freely available) | Yes |
| VO2max (GPS watch) | Firstbeat white paper, 2017 | **White paper** (freely available) | Partially (core principle yes; exact algo proprietary) |
| VDOT | Daniels & Gilbert, 1979, *Oxygen Power* | **Book** (procure) | Yes (equations); "VDOT" name is trademarked |
| Race prediction (Riegel) | Riegel, 1981, *American Scientist* | **Paper** (freely available) | Yes |
| Race prediction (Cameron) | Cameron (informal, unpublished) | **Web/informal** | Yes |
| Lactate threshold (Conconi) | Conconi et al., 1982, *J Appl Physiol* | **Paper** (freely available) | Yes (but poor validity) |
| Lactate threshold (Friel) | Friel, 2000, *Inside Triathlon*; expanded in books | **Article/Book** (procure) | Yes |
| Lactate threshold review | Svedahl & MacIntosh, 2003, *Can J Appl Physiol* | **Paper** (freely available) | Yes |
| TRIMP | Calvert et al., 1976, *IEEE Trans SMC*; Banister 1991 book chapter | **Paper** + **Book** | Yes |
| TSS (power) | Allen & Coggan, 2010, *Training & Racing with a Power Meter* | **Book** (procure) | Yes |
| hrTSS | TrainingPeaks (proprietary, based on TRIMP) | **Proprietary** | Approximately |
| ATL/CTL/TSB | Calvert et al. 1976; Morton et al. 1990 | **Papers** (freely available) | Yes |
| Running Economy | Conley & Krahenbuhl 1980; Barnes & Kilding 2015 | **Papers** (freely available) | Yes (measurement, not formula) |
| GAP | Minetti et al., 2002, *J Appl Physiol* | **Paper** (freely available) | Yes |
| Cadence/stride | Heiderscheit et al., 2011, *Med Sci Sports Exerc* | **Paper** (freely available) | Yes |

---

## Books to Procure

1. **Daniels, J. & Gilbert, J. (1979).** *Oxygen Power: Performance Tables for Distance Runners.* Self-published. (Original VDOT equations)
2. **Daniels, J. (2021).** *Daniels' Running Formula.* 3rd ed. Human Kinetics. (Accessible formulation of VDOT system + 180 cadence observation)
3. **Allen, H. & Coggan, A. (2010).** *Training and Racing with a Power Meter.* 2nd ed. VeloPress. (TSS, NP, CTL/ATL/TSB implementation)
4. **Friel, J. (2009).** *The Triathlete's Training Bible.* 3rd ed. VeloPress. (LTHR field test, zone definitions)
5. **Banister, E.W. (1991).** "Modeling Elite Athletic Performance." In MacDougall et al. (Eds.), *Physiological Testing of Elite Athletes.* Human Kinetics. (TRIMP + impulse-response model — book chapter)

---

## Freely Available Papers (Key DOIs)

| Paper | DOI |
|-------|-----|
| Åstrand & Ryhming 1954 (VO2max nomogram) | 10.1152/jappl.1954.7.2.218 |
| Cooper 1968 (12-min run) | 10.1001/jama.1968.03140030033008 |
| Conconi et al. 1982 (HR deflection) | 10.1152/jappl.1982.52.4.869 |
| Calvert et al. 1976 (systems model) | 10.1109/TSMC.1976.5409179 |
| Morton et al. 1990 (modeling running) | 10.1152/jappl.1990.69.3.1171 |
| Conley & Krahenbuhl 1980 (running economy) | 10.1249/00005768-198025000-00010 |
| Riegel 1981 (race prediction) | (PubMed PMID 7235349; in *American Scientist* 69(3):285) |
| Minetti et al. 2002 (energy cost, grade) | 10.1152/japplphysiol.01177.2001 |
| Heiderscheit et al. 2011 (step rate) | 10.1249/MSS.0b013e3181ebedf4 |
| Barnes & Kilding 2015 (running economy review) | 10.1186/s40798-015-0007-y |
| Busso 2003 (variable dose-response) | 10.1249/01.MSS.0000074465.13922.B9 |
| Svedahl & MacIntosh 2003 (LT review) | 10.1139/h03-023 |
| Fletcher et al. 2009 (RE beyond VO2) | 10.1152/japplphysiol.00307.2009 |
