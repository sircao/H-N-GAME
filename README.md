# EV route–charging scheduling and Unreal execution

Finite-day electric-vehicle route and charging scheduling, physical/economic auditing, Unreal runtime integration, and reproducible paper figures.

## Contents

- `experiments/`: scenario construction, optimization, independent audits and reference tests.
- `supplementary_experiments/`: controlled synthetic experiments.
- `unreal-map-master/Plugins/StackelbergEVOptimization/`: project-specific C++ runtime and Python optimizer.
- `unreal-map-master/Content/Python/` and `Content/Maps/EVSmallCity.umap`: scene scripts and project map.
- `data/08_publication_figures/*.py`: plotting and per-figure data-export source code. Numeric inputs and generated figures are private.

This project evaluates finite simulated scheduling contracts, not empirical city validity or a complete coupled Stackelberg equilibrium. See `experiments/SCIENTIFIC_METHODS.md` for assumptions and limitations.

## Python workflow

Use Python 3.11 and install `experiments/requirements.txt` in a virtual environment. Run from the repository root:

```bash
python -m pip install -r experiments/requirements.txt
python -m unittest discover -s experiments -p 'test_*.py' -v
python experiments/run_scientific.py
python experiments/audit_scientific_runs.py
python data/08_publication_figures/plot_paper_figures.py
python data/08_publication_figures/export_plot_data.py
```

Figure generation also requires matplotlib, numpy and Pillow. Running the optimizer replaces generated results; keep the frozen `data/` copy for comparison. Logs and original machine paths are historical provenance, not portable configuration. The original full-project delivery verifier and packaging scripts refer to original development artifacts and are not release-install commands.

## Unreal dependencies and attribution

Unreal Engine binaries are intentionally excluded. Install Unreal Engine 4.27 separately. This research extends [Unreal-MAP by binary-husky](https://github.com/binary-husky/unreal-map). Obtain the upstream project and its required plugins/assets separately, then overlay this repository's `unreal-map-master/` files. Required upstream modules include UHMP, Jsonx, JsonxUtilities, XtensorAPI and StreetMap. This repository does not claim authorship of upstream code or assets.

The scene script references `/Game/ConceptCar/Car/SM_AutomotiveTP_Car`; obtain that resource under its applicable license or replace it with an appropriately licensed mesh. Other upstream resources referenced by the map must be restored from the upstream project. No third-party redistribution permission is inferred.

The saved `.uproject` EngineAssociation may need to be reassigned to your local UE4.27 installation. See `experiments/SCIENTIFIC_README.md` for build/execution procedures. The original launcher contains Linux development paths; configure paths for your installation before use.

## License status

A license for the author's original code/data has not yet been selected. No license is granted here for third-party engine components, upstream code, maps or visual assets. Public source availability alone is not an open-source license; select an explicit code/data license before describing this release as fully open source.

## Research data access

Frozen experimental inputs, results, ledgers, telemetry, paper tables and generated figures are intentionally excluded from this public code repository. They are stored in the access-controlled private repository `sircao/H-N-GAME-data`. A GitHub collaborator grant from the owner is required to access it.

Authorized users should clone that private repository separately and copy its `data/`, `experiments/scientific/`, `experiments/visualizations/` and `supplementary_experiments/results/` artifacts into the matching paths here. The Python optimizer/tests may generate new synthetic outputs without private data; reproducing the frozen study and plotting its figures requires authorized input access. Unreal map source and scene-generator code remain public.

Public history was replaced to remove previously committed research data. Existing clones must be cloned again; do not push the old history back into this repository.
