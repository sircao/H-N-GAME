# Current scientific experiment workflow

The authoritative revision is the full finite-day study in `scientific/final_results/`. Start with `scientific/final_results/SCIENTIFIC_RESULTS.md` and `SCIENTIFIC_METHODS.md`.

This workflow addresses the review's Route A. It does not claim a new coupled-equilibrium solver, empirical city validation, universal benefits or an online controller. Those unsupported claims are withdrawn.

## Source and model

- `export_unreal_scene.py` reads the actual EVSmallCity actors/tags, charger cabinets and generator road topology in Unreal without regenerating/saving the map.
- `build_scientific_scenario.py` defines all finite daily trips, physical station access and parking intervals under `scientific_protocol.json`.
- `scientific_model.py` implements linked battery inventories, all trips, route decisions, quarter-hour charging, connector occupancy and station/car power limits.
- `scientific_audit.py` independently checks every exported physical/economic result; `audit_scene_contract.py` checks the source actor identities, waypoint order and finite trip counts.
- The original plugin optimizer entry point now calls this model and audit; its incomplete historical coupling entry point is disabled.
- `ScientificEVRuntimeManager` executes the finite events, uses the actual battery contract and double-precision clocks/energy, and exports telemetry. Scientific mode does not select the legacy replay manager.

Explicit new simulation inputs include terminal inventory, reserve, charging efficiency, parking-at-cabinet rules, cabinet driveway geometry and tariffs. The source map's bidirectional-road convention is retained. These choices are disclosed, not described as field observations.

## Reproduction

Run from the Game root. Dependencies are in `experiments/requirements.txt`.

1. Export the scene with the engine's embedded Python. `export_unreal_scene.py` is designed for `UE4Editor ... -run=pythonscript -script=/absolute/path/to/experiments/export_unreal_scene.py -unattended -nullrhi -nosound`. Set the Python standard-library path as in `start_game.sh`.
2. Build and verify the canonical contract:

```bash
.venv/bin/python experiments/build_scientific_scenario.py
.venv/bin/python experiments/audit_scene_contract.py
.venv/bin/python -m unittest discover -s experiments -p 'test_*.py' -v
```

3. Run and independently re-audit all comparisons:

```bash
.venv/bin/python experiments/run_scientific.py
.venv/bin/python experiments/audit_scientific_runs.py
```

4. Build changed runtime source with the project UE4.27 toolchain:

```bash
UE_USE_SYSTEM_MONO=1 UnrealEngine-4.27/Engine/Build/BatchFiles/Linux/Build.sh \
  UHMPEditor Linux Development unreal-map-master/UHMP.uproject \
  -WaitMutex -NoHotReloadFromIDE -Module=StackelbergEVOptimization
```

5. Execute and inspect the compiled runtime. The 64 Hz rate matches the original HMP bridge's binary-exact timestep requirement:

```bash
bash start_game.sh -game -nullrhi -nosound -unattended \
  -UseFixedTimeStep -FPS=64 -EVScientificSeconds=24 -EVScientificAutoExit
.venv/bin/python experiments/audit_unreal_execution.py \
  experiments/scientific/final_results/E1_reference_joint
.venv/bin/python experiments/stress_execution.py \
  experiments/scientific/final_results/E1_reference_joint
```

6. Optional, explicitly post-hoc peak ambiguity diagnostic and final report:

```bash
.venv/bin/python experiments/diagnose_peak_ties.py \
  experiments/scientific/final_results/E1_reference_joint
.venv/bin/python experiments/report_scientific.py
```

`bash start_game.sh -log` opens the actual scene in the editor with the corrected scientific plan selected for Play. `--historical-baseline` deliberately selects the old controller for historical inspection; that controller's old CSVs are not the revised experiment evidence.

## Audit interpretation

The primary objective is user time/electricity/carbon-payment cost. Resource cost, carbon mass and peak load are separate outcomes. Peak load is not uniquely defined by a cost-only optimum; the post-hoc diagnostic adds an explicit cost bound and a secondary peak objective to demonstrate this ambiguity. It does not replace the primary results.

The independent no-disturbance execution control must close the inventory. Artificial travel/energy disturbances are reported separately, including deadline/storage failures. Their distributions are assumed scenarios, not estimated real-world distributions. Prescribed Unreal motion is software replay/consistency evidence.

All full-study feasible settings serve every declared trip and end with the same initial battery inventory. Infeasible cases and time limits have distinct statuses; failed settings are not recorded as zero-cost outcomes. Confidence intervals refer only to the declared paired perturbation generator.

## Older artifacts

`results/` and `synthetic_results/` directly under `experiments/` are the earlier controlled-study artifacts. `scientific/results/` is a superseded diagnostic matrix generated before the exact-OD waypoint-order correction. The final, source-audited matrix is exclusively `scientific/final_results/`. Failed first-runtime diagnostics are preserved under `scientific/diagnostics/`; their thresholds were not relaxed to obtain a pass.
