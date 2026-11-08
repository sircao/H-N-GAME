#!/usr/bin/env bash
set -euo pipefail
game_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
engine_python="$game_root/UnrealEngine-4.27/Engine/Binaries/ThirdParty/Python3/Linux/lib/python3.7"
# UE4's embedded Python must not inherit a different Python version's library.
export PYTHONPATH="$engine_python:$engine_python/lib-dynload"
if [[ "${1:-}" == "--historical-baseline" ]]; then
  shift
  exec "$game_root/UnrealEngine-4.27/Engine/Binaries/Linux/UE4Editor" \
    "$game_root/unreal-map-master/UHMP.uproject" /Game/Maps/EVSmallCity -EVOptimizationMode=Baseline "$@"
fi
scientific_plan="$game_root/experiments/scientific/final_results/E1_reference_joint/scientific_plan.csv"
if [[ ! -f "$scientific_plan" ]]; then
  echo 'Missing audited scientific plan. Run experiments/run_scientific.py first.' >&2
  exit 2
fi
exec "$game_root/UnrealEngine-4.27/Engine/Binaries/Linux/UE4Editor" \
  "$game_root/unreal-map-master/UHMP.uproject" /Game/Maps/EVSmallCity \
  -EVOptimizationMode=Scientific "-EVScientificPlan=$scientific_plan" "$@"
