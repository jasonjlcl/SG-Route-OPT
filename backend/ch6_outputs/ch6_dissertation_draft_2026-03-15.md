# Chapter 6 Draft Text and Tables

## 6.X Local Experimental Evaluation Using Recoverable Repository Data

This section reports the strongest experimental evidence that could be recovered and regenerated from the local repository as of 15 March 2026. The local evaluation had two stages. First, the recoverable on-disk ML travel-time artifacts were rerun against the implemented system baseline to determine whether they improved route-planning performance. Second, after those artifacts were found to be miscalibrated, a small local retraining and calibration exercise was carried out to test whether the regression could be removed without changing the routing solver itself. To avoid overstating the evidence, only scenarios backed by complete local origin-destination (OD) cache coverage were used for fresh reruns.

Within the current implementation, the A/B comparison baseline is the system's fallback travel-time matrix (`fallback_v1`), not a manual dispatch sequence and not a nearest-neighbour routing heuristic. For each experiment, the same VRPTW optimisation model, operational constraints, and solver configuration were applied to both variants; the only changing component was the travel-time matrix used by the solver.

### 6.X.1 Recoverable Local Evidence

Table 6.1 summarises the types of evaluation evidence that were available locally and whether they were suitable for dissertation use.

**Table 6.1. Recoverable local evaluation evidence**

| Evidence category | Local status | Suitability for Chapter 6 |
| --- | --- | --- |
| Scenario inputs, stop lists, demands, service times, and time windows | Available in `backend/app.db` | Suitable |
| Persisted route outputs, stop sequences, ETAs, route durations, and unserved stops | Available in `backend/app.db` | Suitable |
| Baseline-versus-ML A/B routing experiments | Runnable locally on selected datasets | Suitable |
| Actual-versus-predicted travel-time evaluation | Not available locally because `actual_travel_times = 0` | Not suitable |
| Uplift-model evaluation | Not meaningful locally because the available uplift sample file is degenerate | Not suitable |
| Manual-order baseline | Not implemented in the current repository | Not suitable |
| Nearest-neighbour baseline | Not implemented in the current repository | Not suitable |
| Exact API billing or cloud-cost analysis | Not tracked as a first-class metric | Not suitable |

The main implication of Table 6.1 is that the local repository can support a planning-level comparison between the implemented fallback baseline and local ML travel-time models, but it cannot support a formal prediction-accuracy study against real observed travel times.

### 6.X.2 Local Experimental Setup

Three locally stored datasets were inspected. Dataset 1 had full cached route-matrix coverage but contained only three stops, making it too small for a meaningful routing comparison. Dataset 4 contained 30 stops but had zero cached route-matrix coverage at the tested departure bucket, meaning any rerun would depend heavily on newly generated heuristic fallback routes and would therefore be weaker as experimental evidence. Dataset 3 was selected for the fresh reruns because it provided the strongest local basis for comparison: it had 12 geocoded stops and complete cached OD coverage for the tested bucket.

The shared experimental dataset profile is shown in Table 6.2.

**Table 6.2. Local dataset selected for fresh Chapter 6 reruns**

| Item | Value |
| --- | --- |
| Dataset ID | 3 |
| Source filename | `sample_stops.csv` |
| Number of geocoded stops | 12 |
| Total demand | 16 parcels |
| Average service time | 7.83 minutes |
| Delivery time-window span | 09:00 to 18:00 |
| Depot coordinates | 1.3521, 103.8198 |
| Cached OD coverage at tested departure bucket | 156 / 156 OD pairs (100%) |
| Baseline travel-time source | `fallback_v1` |
| Initial active ML artifact tested | `v20260315045420274714` |
| Best retrained artifact | `v20260315063821017757` |
| Optimisation method | VRPTW solver with identical constraints across both variants |

Five scenario variants were then rerun on Dataset 3 to test whether the result was sensitive to fleet size, capacity, operating window, and drop-visit settings.

**Table 6.3. Scenario definitions for local A/B reruns**

| Scenario ID | Number of vehicles | Vehicle capacity | Workday | Drop visits allowed |
| --- | ---: | ---: | --- | --- |
| S1 Nominal | 2 | 20 | 08:00-18:00 | Yes |
| S2 Single vehicle | 1 | 20 | 08:00-18:00 | Yes |
| S3 Tight capacity | 2 | 8 | 08:00-18:00 | Yes |
| S4 Shorter workday | 2 | 20 | 09:00-17:00 | Yes |
| S5 No-drop variant | 2 | 20 | 08:00-18:00 | No |

### 6.X.3 Initial Local Rerun Result Before Retraining

The first rerun stage used the recoverable local artifact `v20260315045420274714`, which represented the best available active local model path after missing historical registry artifacts were bypassed. Table 6.4 shows the planning-level results for the five rerun scenarios. For clarity, the percentage columns are expressed as the percentage increase in the ML solution relative to the fallback baseline for lower-is-better metrics. A positive percentage therefore indicates worse performance by the ML variant.

**Table 6.4. Planning performance of fallback baseline versus initial local ML model**

| Scenario | Baseline makespan (s) | ML makespan (s) | ML increase in makespan | Baseline distance (m) | ML distance (m) | ML increase in distance | Served stops | On-time rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| S1 Nominal | 15,778 | 25,630 | 62.44% | 6,936.10 | 12,545.34 | 80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S2 Single vehicle | 15,778 | 25,630 | 62.44% | 6,936.10 | 12,545.34 | 80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S3 Tight capacity | 14,268 | 20,442 | 43.27% | 8,362.79 | 13,902.68 | 66.24% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S4 Shorter workday | 12,178 | 22,040 | 80.98% | 6,936.10 | 12,545.34 | 80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S5 No-drop variant | 15,778 | 25,630 | 62.44% | 6,936.10 | 12,545.34 | 80.87% | 12/12 vs 12/12 | 1.00 vs 1.00 |

Table 6.4 shows a consistent negative pattern across all five scenario variants. The ML-assisted route plans did not improve service feasibility, because both the fallback and ML variants served all 12 stops and achieved an on-time rate of 100%. However, the ML variant produced substantially longer route durations and longer travel distances in every tested configuration. In the nominal scenario, the ML artifact increased makespan by 62.44% and distance by 80.87% relative to the fallback baseline.

This result indicates that, under the strongest locally recoverable experimental conditions, the initially recoverable ML travel-time artifact did not improve operational routing performance. Instead, it appears to have inflated leg travel times sufficiently to produce longer routes and higher total travel distance without any measurable gain in service level.

### 6.X.4 Cross-Check Across Local ML Artifact Families

To test whether the negative result was caused only by the selected active artifact, additional on-disk model families were screened against the nominal scenario. Table 6.5 compares the offline artifact metrics with the corresponding routing outcome on Dataset 3.

**Table 6.5. Cross-check of local ML artifact families under the nominal scenario**

| Model version | Offline rows | Offline MAE (s) | Mean predicted/fallback ratio on dataset 3 legs | ML makespan (s) | ML increase in makespan | ML distance (m) | ML increase in distance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `v20260216105011` | 60 | 46.89 | 4.70x | 18,788 | 19.08% | 15,447.02 | 122.70% |
| `v20260216103502` | 80 | 2.57 | 7.40x | 25,630 | 62.44% | 12,545.34 | 80.87% |
| `v20260315045420274714` | 80 | 2.57 | 7.40x | 25,630 | 62.44% | 12,545.34 | 80.87% |

Table 6.5 is important because it shows that the negative routing result was not limited to a single active model version. Even the artifact families with the best recorded offline MAE values performed poorly when applied to the locally cached Singapore OD matrix used in the routing experiments. The large predicted-to-fallback ratios suggest a calibration mismatch between the offline training artifacts and the route-matrix context represented in the local repository.

### 6.X.5 Local Retraining and Calibration

Because all recoverable artifact families underperformed, a small local retraining and calibration exercise was conducted to test whether the failure was due to model calibration rather than the solver. Four candidate datasets were generated locally. Three were calibration-style datasets derived from the local OneMap label store, and one was derived directly from the local OD cache used by the routing experiments.

**Table 6.6. Candidate local retraining datasets and offline training results**

| Candidate dataset | Construction summary | Model version | Rows | Offline MAE (s) | Offline MAPE |
| --- | --- | --- | ---: | ---: | ---: |
| `onemap_identity.csv` | OneMap labels with `base_duration_s = actual_duration_s` | `v20260315063816867841` | 2,600 | 3.47 | 0.00441 |
| `onemap_identity_multi_hour.csv` | Same labels duplicated across representative hours `00, 08, 12, 18` | `v20260315063819799285` | 10,400 | 2.79 | 0.00372 |
| `onemap_routebase.csv` | OneMap labels with `base_duration_s = route_distance_m / 9.0` | `v20260315063820648976` | 2,600 | 73.16 | 0.08683 |
| `od_cache_identity_multi_hour.csv` | Local OD cache with `actual_duration_s = base_duration_s`, duplicated across representative hours `00, 08, 12, 18` | `v20260315063821017757` | 1,292 | 0.15 | 0.00150 |

The offline metrics in Table 6.6 should not be interpreted as real-world prediction-accuracy evidence because the retraining data were generated from local surrogate sources rather than observed travel-time labels. Their role in this study was narrower: to test whether local recalibration could remove the severe routing regression seen in the initial reruns.

Under nominal-scenario screening, the OD-cache-calibrated candidate `v20260315063821017757` was selected for full reruns because it was the only candidate that improved makespan without worsening total distance. The multi-hour OneMap identity candidate slightly improved makespan but worsened distance, while the remaining candidates worsened makespan, distance, or both.

### 6.X.6 Final Rerun Results With the Best Calibrated Model

Table 6.7 reports the full rerun results for the selected calibrated model `v20260315063821017757`.

**Table 6.7. Planning performance of fallback baseline versus the best calibrated local model**

| Scenario | Baseline makespan (s) | Calibrated model makespan (s) | Makespan improvement | Baseline distance (m) | Calibrated model distance (m) | Distance improvement | Served stops | On-time rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| S1 Nominal | 15,778 | 15,694 | 0.53% | 6,936.10 | 6,936.10 | 0.00% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S2 Single vehicle | 15,778 | 15,694 | 0.53% | 6,936.10 | 6,936.10 | 0.00% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S3 Tight capacity | 14,268 | 14,221 | 0.33% | 8,362.79 | 8,362.79 | 0.00% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S4 Shorter workday | 12,178 | 12,094 | 0.69% | 6,936.10 | 6,936.10 | 0.00% | 12/12 vs 12/12 | 1.00 vs 1.00 |
| S5 No-drop variant | 15,778 | 15,694 | 0.53% | 6,936.10 | 6,936.10 | 0.00% | 12/12 vs 12/12 | 1.00 vs 1.00 |

Table 6.7 shows that the calibrated model removed the severe regression seen in Table 6.4 and produced small but consistent makespan improvements across all tested scenarios. The improvement ranged from 0.33% in the tight-capacity scenario to 0.69% in the shorter-workday scenario. Total route distance did not improve, but it also did not worsen. Service-level metrics remained unchanged: all stops were served, no stops were unserved, and on-time performance remained 100% in every rerun. In the tight-capacity scenario, the sum of vehicle durations also improved by 10.42%, indicating that the recalibrated timings produced a modest schedule benefit even though route geometry was unchanged.

The practical interpretation is that the main gain from local calibration was schedule timing rather than route structure. The fallback and calibrated variants typically selected the same geometric route pattern, but the calibrated timings reduced route duration slightly without introducing the inflation error seen in the earlier artifact families.

### 6.X.7 Discussion

Taken together, the local evidence supports a more nuanced conclusion than the initial rerun alone. The first-stage experiments showed a valid negative result: the recoverable local ML artifacts were miscalibrated for the repository's cached Singapore OD matrix and materially worsened planning outcomes. This negative result should be retained in the dissertation because it demonstrates that the evaluation did not selectively report only favourable outputs.

At the same time, the retraining and calibration exercise showed that the regression was not inherent to the optimisation pipeline. Once the model was aligned to the OD-cache domain actually used by the local routing experiments, the severe overprediction problem disappeared and the ML variant achieved small but repeatable makespan improvements without degrading distance or service level. The strongest defensible local claim is therefore not that the original recovered ML artifacts improved routing, but that local recalibration was able to convert a harmful model path into a mildly beneficial one.

The magnitude of the local gains remains modest. Makespan improvements of 0.33% to 0.69% indicate that the calibrated model improved schedule timing only slightly, and the unchanged route distances suggest that the local scenarios offered limited headroom for structural route changes. Accordingly, this result should be presented as a limited positive sensitivity finding rather than as strong evidence of broad operational improvement.

### 6.X.8 Validity and Limitations

The conclusions in this subsection should be interpreted within the limits of the local evidence base. First, the baseline in these experiments is the implemented fallback matrix, not a manual dispatcher route and not a nearest-neighbour heuristic; therefore, this subsection evaluates improvement over the deployed system baseline only. Second, the local repository contains no observed travel-time labels in the `actual_travel_times` table, so a formal actual-versus-predicted accuracy study could not be reproduced locally. Third, the available uplift sample file contained constant values for static duration, observed duration, and congestion factor, so uplift evaluation was not meaningful and was excluded from the formal analysis.

Fourth, the retrained local models were calibrated using surrogate local data sources, including an OD-cache-derived identity dataset. That means the calibrated rerun result is useful as evidence of local domain alignment and route-planning sensitivity, but it should not be presented as proof of external predictive generalisation. Fifth, Dataset 3 was the only locally robust OD-backed candidate for strong reruns, so the chapter should avoid implying that the calibrated result has already been demonstrated across a large and diverse operational workload.

Accordingly, the dissertation should not claim from the local evidence alone that the AI-assisted system improves real-world prediction accuracy in production, improves over manual route planning, or improves over a nearest-neighbour baseline. What can be claimed is narrower and defensible: under the strongest locally reproducible conditions, the originally recoverable ML artifacts harmed routing performance, but a locally calibrated replacement model produced small, consistent makespan improvements over the implemented fallback baseline without changing service feasibility.

## Suggested Concluding Paragraph

The local rerun study therefore supports a cautious but defensible Chapter 6 conclusion. When the recoverable on-disk ML travel-time artifacts were tested against the implemented fallback baseline on the only locally robust OD-backed dataset, they consistently worsened route-planning performance despite favourable stored offline metrics. However, a follow-up local calibration exercise using an OD-cache-aligned retrained model removed this regression and yielded small but repeatable makespan improvements of 0.33% to 0.69% while preserving route distance and service level. The local evidence therefore supports a limited claim that travel-time model calibration matters to routing quality and can produce modest schedule gains, but it does not yet support stronger claims regarding real-world prediction accuracy, uplift effectiveness, or superiority over manual and nearest-neighbour baselines.
