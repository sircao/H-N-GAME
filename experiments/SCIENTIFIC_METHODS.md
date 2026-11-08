# Scientific scope, hypotheses and interpretation

This revision adopts the review's **Route A: coordinated scheduling and mechanism analysis**. The evaluated object is a finite-day centralized route/charging scheduler on the stored Game simulation map. Historical MNL functions remain diagnostic helpers; they are not the new solver's equilibrium constraints. The default optimizer entry point and scientific Unreal mode use the same explicit multi-trip physical contract.

The revision retires the unsupported macro zero-sum principle, unconditional strict-improvement theorem, full coupled Stackelberg-equilibrium claim, universal emissions reduction, city-wide “life efficiency”, and 156.59% efficiency interpretation. These are not repaired by producing favorable simulation numbers.

## Experimental contract

The source contains 800 vehicle actors, 127 charger cabinets and a road graph with 5,829 nodes and 12,828 directed links under the original generator's bidirectional convention. Source actor departure/arrival tags and the configured turnaround/minimum/maximum-leg rules define **6,084 complete trips**, with no continuing undeclared trips beyond that finite set.

Parking occurs at actual cabinet locations. Required travel includes cabinet access, source OD waypoints and return/access to the next parking cabinet. Straight-line cabinet driveways, road speed/width scaling, the 10% battery reserve, charging efficiency 0.9, fixed/time-of-use tariffs and the requirement to end with the initial battery inventory are explicit simulation parameters in `scientific_protocol.json`. They are not field measurements or independently calibrated quantities. Initial placement at a cabinet is part of this revised contract, not a claim that it was the vehicle's position in a historical sampled CSV.

All related charging is inside 00:00–24:00. Every arm receives the same complete future task information. The greedy baseline uses full-day energy needs but an earliest-feasible rule; the charge-only arm supplies the stronger fixed-route offline optimization comparison. A comparison with that arm separates routing value from merely replacing a heuristic with an optimizer.

The exact candidate-generation implementation uses main-leg link costs `travel_time + w * distance_km` for fixed weights `w = 0, 0.02, 0.05, 0.2, 100`, with common shortest-time station approaches/exits and exact duplicate removal. The protocol's shorthand “shortest-energy” means the distance-dominated candidate; it is not a guarantee of a globally energy-minimal full route or an exhaustive K-shortest-path set. All optimality claims are restricted to these explicitly exported finite candidates.

Road-link capacity, endogenous traffic feedback and collision avoidance are outside this static route-cost scheduling model. No congestion-relief, traffic-safety or network-equilibrium conclusion is drawn from its solutions.

## Mathematical problem and units

For each trip j of vehicle i, select exactly one feasible candidate route r with binary `x[i,j,r]`. For each quarter-hour parking slot, grid energy `q[i,t]` is continuous in kWh and connector occupancy `y[i,t]` is binary. Charging is allowed only at the physically declared parking site and outside the trip's reserved departure–deadline interval.

Battery inventory follows:

`B[i,k+1] = B[i,k] + eta[i] * q[i,k] - E[i,k]`.

Inventory is bounded by the reserve and battery capacity throughout the finite event sequence. Initial and terminal inventories are equal for every vehicle. Single-car/connector power, station power and connector occupancy are explicit constraints. Trips may not be dropped. An infeasible input remains infeasible; a timeout is not recoded as infeasibility.

The optimized **user objective**, in CNY, is:

`beta * sum(travel_hours) + sum(retail_price[t] * grid_kWh[t]) + tau * gamma * sum(grid_kWh) / 1000`.

Here beta is CNY/hour, retail/wholesale prices are CNY/kWh, gamma is kg CO2/kWh, and tau is CNY/tonne. There is no second arbitrary traction-energy fee in the same objective. The main energy model is distance times the source vehicle-type consumption rate; a 1 kW auxiliary-energy alternative checks sensitivity.

Emissions are `gamma * grid_kWh`; traction energy is not counted a second time. Reported resource cost is time cost plus wholesale electricity, not a complete monetization of social welfare or environmental damage. Retail payment is operator revenue; operator profit is retail revenue minus wholesale cost. Carbon payments are separate policy transfers and are included separately in the user objective.

The current external carbon price is 40 CNY/tonne, consistent with the source configuration's policy input. The historical manuscript's optimized 422 baseline and claimed 60-CNY threshold are withdrawn, not used as evidence or as tuning targets for the new scan.

## Design and hypotheses

- **E1:** baseline, route-only rule, charge-only offline optimization and joint offline optimization, at identical fixed tariffs and physical/service boundaries. No assumption that every physical metric improves.
- **E2:** finite bounded retail candidates, each with complete rescheduling at identical wholesale cost and physical conditions. Highest tested operating profit is a candidate-search result, not continuous-price Stackelberg optimality.
- **E3:** independently recompute trip service, spatial continuity, battery/terminal inventory, losses, connector/power use, load integrals and physical/economic metrics from exported events.
- **E4:** independent exhaustive small references with integral-energy transport cases; zero capacity, battery limits, no charging/route opportunity, equal-energy fixed-carbon invariance, terminal-inventory changes, corruption detection and timeout classification. Fixed-route and joint MILP bounds/gaps are also recorded.
- **E5:** deterministic capacity/window/candidate-set/travel-time/tariff/energy-model changes and ten paired SOC/departure perturbations. Uniform travel-time inflation is an imposed sensitivity, not endogenous traffic congestion. Bootstrap intervals describe the specified input generator only; deterministic cases are not statistical replicates.
- **E6:** compiled Unreal execution of the exact finite event contract, independent telemetry comparison and declared execution stress tests. This checks software/accounting consistency and exposes sensitivity. Prescribed actor motion is replay; it is not independent behavioral or city-traffic validation.

Expanded candidate sets can only weakly improve the *same optimized objective* when the original solution remains feasible. They do not imply strict improvement, lower peaks, less energy, or improved costs for every user. A fixed carbon factor makes equal grid energy produce equal emissions under time shifts. Uniform carbon charges do not alter equal-energy alternatives' relative costs. These are analytical controls, not hypotheses that can be overridden by a favorable plot.

Solver status, the dual bound and mixed-integer gap follow the documented [SciPy MILP interface](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html). Optimality is limited to the declared finite candidate set and time discretization; it does not certify the realism of those inputs.

## Closest studies and claim boundaries

This is an abstract-level methodological comparison, not a numerical reproduction or a claim of outperforming these algorithms.

|Primary source|Relevant mechanism|Difference from the evaluated Game revision|
|---|---|---|
|[Zeng et al., conic relaxation for charging pricing with traffic equilibrium](https://ieeexplore.ieee.org/document/10305184/), TSG 15(3), 3080–3097, 2024|Bilevel pricing and traffic-equilibrium constraints; relaxation exactness is conditional|Game evaluates centralized finite-day scheduling and candidate prices; it claims neither that relaxation nor an equilibrium solver contribution|
|[Flexibility potential of EV charging: trip-chain SDUE](https://www.sciencedirect.com/science/article/pii/S2666792425000344), Advances in Applied Energy 19, 100240, 2025|Trip-chain demand, stochastic dynamic route/station choice, temporal parking flexibility|Game's fixed parking-site contract and declared route times do not model stochastic dynamic network equilibrium|
|[Zhang et al., stochastic dynamic pricing with heterogeneous behavior](https://arxiv.org/abs/2601.13571), 2026 preprint|Bilevel pricing, heterogeneous MNL responses, rolling-horizon computation; network-equilibrium constraints are avoided|Game uses centralized physical dispatch and offline finite-candidate pricing, with no calibrated behavioral or online deployment claim|

The defensible contribution is a reproducible physical/event pipeline and a bounded mechanism study, including null/adverse results and integration checks. A separate claim of new equilibrium theory or algorithmic superiority would require a new mathematical specification, applicable proofs and comparable implementations; those claims are withdrawn here.
