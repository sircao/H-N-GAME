(1)cd '/media/cchio/new_disk/【2】IMSLAB/Game'
(2).venv/bin/python \
  unreal-map-master/Plugins/StackelbergEVOptimization/Python/set_run_mode.py \
  Baseline
(3)bash unreal-map-master/run_ue_editor_safe.sh

output.log  
exec(open(r"/media/cchio/new_disk/【2】IMSLAB/Game/unreal-map-master/Content/Python/design_ev_day_traffic.py", "r", encoding="utf-8").read())
修改静态参数

(4) play

(5).venv/bin/python unreal-map-master/Plugins/StackelbergEVOptimization/Python/nested_game_optimizer.py \
  --samples-dir unreal-map-master/Saved/EVTrafficSamples \
  --stamp 刚才Baseline时间戳 \
  --output-dir unreal-map-master/Saved/StackelbergEVOptimization
生成plan.csv

(6)确认unreal-map-master/Saved/StackelbergEVOptimization/optimized_plan.csv存在
(7).venv/bin/python \
  unreal-map-master/Plugins/StackelbergEVOptimization/Python/set_run_mode.py \
  Optimized
(8)bash unreal-map-master/run_ue_editor_safe.sh
(9)play
(10).venv/bin/python simulation_optimization_analysis.py \
  --before-stamp 20260915_101500 \
  --after-stamp 20260915_103000
(11).venv/bin/python \
  unreal-map-master/Plugins/StackelbergEVOptimization/Python/set_run_mode.py \
  Baseline