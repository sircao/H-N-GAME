# Game: concrete experiment worklist

Prepared 2026-11-03 from `H_GAME_导师审阅与修改建议.md` and inspection of this Game workspace.

Execution update: the current scientific revision is documented in `experiments/SCIENTIFIC_README.md` and `experiments/scientific/final_results/SCIENTIFIC_RESULTS.md`. It uses actual scene actors, 800 vehicles, 127 cabinets and 6,084 finite trips under a fully declared simulation contract, plus a corrected shared solver/runtime path. Unsupported coupled-equilibrium and independent-city-validation claims are withdrawn under the review's Route A. The earlier 53-setting controlled study is historical. Use the final scientific report and closure table for execution status rather than treating this original unchecked design list as an execution log.

The review is source material, not an instruction to implement all proposed extensions. This document translates its experimental requirements into implementation tasks. No experiments were rerun and no solver or runtime code was changed while preparing this list. Existing results below mean artifacts were found and inspected, not independently reproduced in this review.

## 1. What is already available

|Component|Evidence found|What remains|
|---|---|---|
|Synthetic E1–E5 suite|`supplementary_experiments/run_experiments.py`, result CSVs, manifest and independent verifier; saved audit reports 387 runs, 300 feasible plans and 87 infeasible settings|Keep as controlled mechanism evidence; run the original Game scenario separately|
|Original routing solver|`unreal-map-master/Plugins/StackelbergEVOptimization/Python/nested_game_optimizer.py`|Connect route choice, charging feasibility and energy accounting consistently|
|MNL correctness improvements|Actual fixed-point residual, positive iteration index, OD conservation checks; tests include analytic and bisection references|Retain these fixes; add experiment-level diagnostics and coupled-system validation|
|OD parsing|`parse_od_point()` already accepts comma coordinates and Unreal `X=... Y=...` strings|Correct the outdated parser warning in the supplementary README; verify actual input batches|
|Charging windows|Solver explicitly requires parking start/end fields|Ensure original exports supply valid windows; enforce station power and connector occupancy|
|Unreal execution|Runtime loads plans and positions vehicles along planned paths|Current movement is prescribed; measured independent execution validation has not been established|

The synthetic suite uses centralized integer optimization and externally specified congestion. It does not validate the original MNL solver, endogenous traffic feedback, or Unreal execution. Its ten paired seeds and nine scenarios are existing implementation choices, not mandatory numbers imposed by the reviewer.

## 2. Processing order and acceptance gates

Tasks are ordered by dependency. Check a task only after its output and acceptance gate are satisfied. Proposed new filenames below are implementation targets, not files already present.

### Task 1 — Freeze one original scenario and define the experiment contract

- [ ] Select one complete timestamped batch from `unreal-map-master/Saved/EVTrafficSamples/`; explicitly record the five input CSV filenames. Do not automatically compare the earliest and latest batches.
- [ ] Create `experiments/scenario_manifest.json`: input hashes, map/network version, vehicle and task counts, simulation clock origin, complete accounting horizon, random sources/seeds, parameter values and units, code version/hash.
- [ ] Create `experiments/tasks.csv` with task ID, vehicle ID, OD, departure and deadline, feasible station/parking window, battery capacity, initial SOC and terminal SOC requirement. Add a leg ID where a vehicle has multiple trips.
- [ ] Create station inputs with station ID, connector count, connector power and station power limit; separate wholesale price, retail price and carbon factor inputs.
- [ ] Label each input as geographic data, measured observation, simulated output or assumption. Report topology reconstruction, coverage, connectivity, candidate generation and route overlap.
- [ ] Freeze the primary research question: under equal service and storage requirements, when do route and charging flexibility improve outcomes? Use the scheduling/mechanism scope unless full equilibrium evidence is supplied.

**Acceptance:** every evaluated task has an identifiable source, deadline, initial battery state and terminal requirement. Missing fields produce an explicit validation failure; missing observations are not silently invented. Deliver a scenario/parameter table and a “fixed versus varied” table.

Review references: P01, P03, P13, P20, P23–P26, P30–P33, P47–P51.

### Task 2 — Close physical accounting before computing improvements

**Edit:** `charging_requirements()`, `allocate_charging()`, `write_outputs()` in the original optimizer; `EVTrafficRuntimeController.cpp` where baseline task fields must be exported.

- [ ] Replace demand inferred solely from the minimum observed SOC and an 80% target with demand derived from the task's initial energy, selected-route energy and declared terminal requirement. Explicitly declare grid-side versus battery-side charging energy.
- [ ] Enforce chronological battery balance, SOC bounds, efficiency, actual parking availability, departure readiness and arrival deadlines for every trip/charge event.
- [ ] Enforce per-vehicle power, station power and connector occupancy. The current one-hour allocation and `need <= 60` check do not establish these constraints.
- [ ] Separate EV charging from non-EV base load. `leader_search()` currently starts from a series named `total_charging_load_kW` and adds scheduled charging; establish its meaning before using it as background load.
- [ ] Write `experiments/results/energy_service_ledger.csv`, including initial/final energy, traction energy, grid energy, losses, service outcome and failure reason.
- [ ] Include charging before/after the nominal plotting interval in the accounting horizon, or explicitly report boundary energy and remaining obligations.

**Acceptance:** for each task, `initial_kWh + efficiency * grid_kWh - traction_kWh - final_kWh` is within a declared numerical tolerance. All power, occupancy, window and service constraints pass. Preserve infeasible cases and failure causes; never assign them zero cost.

Review references: P09, P13, P26, P28, P30–P33, P37–P38.

### Task 3 — Establish solver and mechanism correctness (E4)

**Use:** existing `test_nested_game_optimizer.py` and the synthetic reference cases. Add reference checks for any changed coupled model.

- [ ] Run two-route/two-period cases against hand calculations, independent enumeration or a clearly specified optimization reference appropriate to the same model. Do not compare a centralized optimum with an SUE and demand identical objectives.
- [ ] Retain existing MNL analytic/bisection and OD parser checks. Record actual fixed-point residuals, feasibility, iterations, termination status and runtime; add a normalized residual for cross-demand comparisons.
- [ ] Evaluate alternative feasible starting flows and tighter tolerances. Inspect residual trajectories rather than relying on small MSA updates.
- [ ] Test flat electricity prices, no charging flexibility, no congestion, one route, insufficient station capacity and insufficient battery capacity. Include a combined no-benefit control.
- [ ] Test fixed energy and fixed carbon intensity: moving charging in time must leave emissions unchanged. Adding the same carbon cost to all alternatives must leave MNL probabilities unchanged.
- [ ] Check discrete vehicle assignments after continuous flow allocation: OD totals, route counts and subsequent physical feasibility.

**Output:** `correctness_results.csv` and `solver_trace.csv`, with reference difference/residual, tolerances and failure classification. Specify thresholds before inspecting favorable results.

**Acceptance:** simple cases match the correct reference within declared tolerances; infeasibility and iteration limits are distinguished; no-benefit cases do not generate artificial savings. Synthetic MILP checks alone do not pass the original-model gate.

Review references: P18, P21–P22, P40–P43, P46, P55, P58.

### Task 4 — Run the fixed-price four-arm experiment (E1)

**Implement:** a proposed `experiments/run_original_experiments.py` around the corrected original model, with independent route-flexibility and charging-flexibility switches. Keep pricing fixed for all four arms.

|Arm|Route policy|Charging policy|
|---|---|---|
|B: baseline|Declared baseline route rule|Declared feasible baseline charging rule|
|R: route only|Route selection enabled|Same baseline charging rule, checked against the selected route|
|C: charging only|Same baseline route rule|Charging scheduling enabled|
|RC: joint|Route selection enabled|Charging scheduling enabled|

- [ ] Use identical tasks, initial/terminal energy requirements, facilities, external conditions, information horizon and paired random inputs in B/R/C/RC. “Same charging rule” does not mean forcing the same kWh when route energy changes.
- [ ] Use a defensible baseline; state its available information. Explain infeasibility without silently repairing one arm using extra resources.
- [ ] Export each arm's plan, prices, physical ledger, solver status and metrics into a separate run directory.
- [ ] Report travel time, waiting, completion, lateness, SOC violations, traction/grid/loss energy, peak load, user expenditure, operator revenue/profit, resource cost and emissions. Mark waiting as unmodeled if it is not calculated.
- [ ] Compare R−B, C−B and RC−B on each raw metric. For a lower-is-better cost, report `J_R + J_C - J_RC - J_B` if claiming an interaction; identify it as a cost-scale interaction, not automatic proof of synergy.

**Output:** `e1_four_arm_metrics.csv`, per-arm plans and a physical/economic/service comparison table.

**Acceptance:** comparisons can be reproduced from the same input manifest; every claimed benefit has a direct metric; joint scheduling is allowed to have tradeoffs or no benefit.

Review references: E1, P02, P32, P51–P52, P63–P64.

### Task 5 — Isolate price feedback (E2)

**Edit:** `leader_search()` and the route/charging cost interface in the original optimizer.

- [ ] Define the leader, objective, allowable retail prices, wholesale costs and response-selection rule. Keep carbon price an external scenario parameter unless explicitly choosing the larger policy-optimization study.
- [ ] Compare RC at fixed prices with RC plus price feedback, holding tasks, wholesale costs and physical constraints fixed.
- [ ] Recompute the complete declared follower/scheduling response for every candidate price. Include the fixed-price candidate in the search.
- [ ] Replace reliance on the average retail price where actual time/route/station decisions need plan-specific charging costs. Use a two-period example to demonstrate the response channel.
- [ ] Report candidate price curves, termination, user payments, purchase costs, revenue, profit, resource costs and physical outcomes separately. State whether the method is a heuristic search, local solution or finite-candidate optimum.
- [ ] Add a frozen-behavior pricing diagnostic only if claiming that behavioral feedback itself creates the gain.

**Acceptance:** higher revenue cannot be presented as resource saving without a corresponding physical/resource-cost change. A price change influences choices through an explicit, tested cost term. Do not claim Stackelberg equilibrium merely because a price search ran.

Review references: E2, P05, P10–P17, P27, P29, P39, P41, P44.

### Task 6 — Audit service, energy and carbon across all arms (E3)

**Implement:** independent checks over exported original-model plans; reuse the synthetic verifier's approach without treating its simplified model as the original model.

- [ ] Recompute battery balance, service outcomes, power/window/occupancy limits and full-horizon energy from exported records.
- [ ] Define one carbon boundary. For grid-purchase emissions, compute `sum(grid_kWh[t] * gamma[t])`; do not also charge the same electricity's emissions to traction consumption. The current original `leader_search()` adds charged energy and route energy and needs this boundary resolved.
- [ ] Keep carbon price, emissions mass and carbon payment as distinct fields. Convert kg to tonnes when applying a price in currency/tonne.
- [ ] Recompute peak, valley, mean, load factor, total energy and costs from the same time series and interval lengths.
- [ ] Produce `e3_accounting_audit.csv` with each check, residual, tolerance, pass/fail and affected run/task.

**Acceptance:** every reported run passes the accounting audit or is explicitly excluded with its failure retained. Pure load shifting at equal energy and fixed gamma reports unchanged emissions.

Review references: E3, P28, P31–P39, P57, P61–P63.

### Task 7 — Run representative scenarios and targeted sensitivity (E5)

- [ ] Vary a small, justified set: demand/congestion, charging capacity, parking duration and candidate-route count. Record overlap and network coverage when diagnosing absent route benefits.
- [ ] Use the same sampled inputs/seeds across arms. Repeat only genuine randomness; use different input cases for deterministic models.
- [ ] Report effect sizes, paired sample counts, uncertainty appropriate to the design, feasibility restoration/failure and unfavorable outcomes. Label observed min/max as ranges, not confidence intervals.
- [ ] Report distributions: median/tail user cost or delay, proportion worse off, low-SOC and tight-deadline cases.
- [ ] If retaining the carbon-price claim, run a separately defined sensitivity experiment with justified units/range and explain the mismatch between the old 30–90 scan and 422 baseline. Isolate fixed/variable route energy and fixed/time-varying gamma; use time-varying gamma only with defensible data.
- [ ] Remove the alleged 60 currency/tonne threshold unless the resulting curve actually supports it. Do not choose a curve to force emissions reductions.
- [ ] Add energy-model or cost-weight sensitivity only where central claims depend on those assumptions.

**Output:** `e5_scenario_effects.csv`, `user_distribution.csv` and, if retained, `carbon_price_sensitivity.csv`, including null and negative results.

**Acceptance:** the report identifies where the method helps, fails or trades energy for time; uncertainty claims match actual random sources and sample units.

Review references: E5, P19–P21, P24, P26, P35, P49–P50, P53–P54, P63–P64.

### Task 8 — Evaluate Unreal execution only if retaining that claim (E6, conditional)

**Edit:** `StackelbergEVRuntimeManager.cpp`, plan import and observation export.

- [ ] Respect each plan's battery capacity and initial state. `UpdateVehicles()` currently computes SOC from hardcoded 85% and 65 kWh, and movement energy from 0.16 kWh/km; align these with declared task/model inputs.
- [ ] Record charging events and the resulting battery transitions; independently record actual arrivals, waits, connector use, conflicts and SOC over time.
- [ ] Join plan and observation by task/vehicle/leg ID. Export `plan_execution_errors.csv` with arrival, queue, SOC and service differences.
- [ ] If evaluating execution robustness, introduce declared arrival/demand/delay disturbances and measure service loss. Do not infer online capability from an offline replay.
- [ ] If movement remains prescribed interpolation along the plan, label it replay/plan-consistency checking. Use an independently responding execution model or external observations for stronger validation claims.

**Acceptance:** either supply independent execution measurements with error/impact results, or narrow the manuscript to a three-dimensional replay demonstration. Building a new online controller is not required by the review.

Review references: E6, P07, P30, P56.

### Task 9 — Regenerate experiment tables and figures

**Edit:** `simulation_optimization_analysis.py`, `picture_radar.py`, `pricture_index.py`, then the manuscript's experimental sections.

- [ ] Create a metric dictionary with formula, unit, aggregation, time horizon and source column. Resolve the actual meanings of legacy values such as 3.43 and 554.97 rather than inferring from magnitude.
- [ ] Replace arbitrary target bands and “156.59% system efficiency” with direct service, physical, economic and environmental results. If retaining a composite score, disclose its weights/normalization and label it a custom score.
- [ ] Fill the original ablation and sensitivity tables with traceable original-model results, or remove unsupported claims. Do not paste synthetic values into the original-city tables.
- [ ] Plot the full accounting horizon with calendar-clock mapping and correct kW/kWh units. Use consistent load statistics, unrounded source data and stated percentage formulas.
- [ ] Report convergence/runtime and numerical status separately from performance. Rewrite conclusions around supported outcomes and limitations.
- [ ] Update stale supplementary/plugin documentation, including already-fixed parser issues and deterministic Wardrop conditions incorrectly presented as finite-theta Logit equilibrium.

**Acceptance:** every numerical claim maps to a run ID, input manifest and raw output; the figures and tables agree; savings are not created by dropping service, draining batteries, moving energy outside the window or mixing transfers with resource costs.

Review references: P01–P02, P11–P12, P18, P57–P69, P72.

## 3. Minimum deliverable and immediate next action

The minimum defensible package is: frozen original-scenario inputs → correct physical model and small references → four fixed-price arms → service/energy/carbon audit → a few justified robustness cases → reproducible raw metrics and revised tables. Add E2 when claiming endogenous pricing benefits; add E6 when claiming independent execution validation.

**Start with Task 1:** inspect one existing input batch for explicit parking windows, deadlines and terminal energy requirements, and produce a missing-field report. Task 2 depends on these definitions. Do not start another large experiment sweep before this gate passes.

Existing synthetic commands, if reproducing that separate suite, are:

```bash
.venv/bin/python supplementary_experiments/run_experiments.py
.venv/bin/python supplementary_experiments/verify_results.py
.venv/bin/python -m unittest discover -s supplementary_experiments -p 'test_experiments.py' -v
.venv/bin/python supplementary_experiments/plot_results.py
```

These regenerate synthetic artifacts. The proposed original-scenario experiment runner and output files above still need implementation; they are not executable commands available today.
