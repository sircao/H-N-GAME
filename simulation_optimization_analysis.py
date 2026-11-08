from __future__ import annotations

import argparse
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


TARGETS = {
    "路径流量": (5.0, 15.0, "fp", "时间-能耗均衡"),
    "充电时段": (30.0, 50.0, "ti", "充电成本最小"),
    "充电负荷": (60.0, 90.0, "ti", "削峰填谷"),
    "分时电价": (10.0, 30.0, "p(t)", "收益-碳排权衡"),
    "碳价": (5.0, 15.0, "tau", "碳排最小化"),
    "系统总效率": (10.0, 20.0, "fp, ti, p(t), tau", "多目标"),
}

FILE_NAMES = {
    "vehicle": "vehicle.csv",
    "road": "road.csv",
    "charging": "charging.csv",
    "system": "system.csv",
}

RUN_FILE_PREFIXES = {
    "vehicle": "datalist",
    "road": "road",
    "charging": "charging",
    "system": "system",
    "behavior": "behavior",
}

DEFAULT_SAMPLES_DIR = Path(__file__).resolve().parent / "unreal-map-master" / "Saved" / "EVTrafficSamples"

PLOT_LABELS = {
    "路径流量": "Route flow",
    "充电时段": "Charging schedule",
    "充电负荷": "Charging load",
    "分时电价": "Time-of-use price",
    "碳价": "Carbon price",
    "系统总效率": "System efficiency",
}


@dataclass
class ScenarioMetrics:
    average_trip_hours: float
    route_entropy: float
    energy_intensity_kwh_km: float
    route_objective: float
    charging_energy_kwh: float
    charging_cost: float
    peak_valley_kw: float
    load_factor: float
    tou_carbon_value: float
    carbon_emissions_kg: float
    carbon_cost: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="量化并可视化交通能源仿真优化前后的六类指标。"
    )
    parser.add_argument("--samples-dir", type=Path, default=DEFAULT_SAMPLES_DIR,
                        help="EVTrafficSamples 目录；默认自动选择最早和最新完整批次")
    parser.add_argument("--before-stamp", help="指定优化前批次时间戳，如 20260913_155616")
    parser.add_argument("--after-stamp", help="指定优化后批次时间戳，如 20260913_155911")
    parser.add_argument("--before-dir", type=Path, help="旧格式优化前 CSV 目录")
    parser.add_argument("--after-dir", type=Path, help="旧格式优化后 CSV 目录")
    parser.add_argument("--output-dir", type=Path, default=Path("analysis_output"))
    parser.add_argument("--carbon-factor", type=float, default=0.5703,
                        help="电网排放因子，kg CO2/kWh，默认 0.5703")
    parser.add_argument("--carbon-price", type=float, default=45.0,
                        help="碳价，元/吨，CSV 中存在 carbon_price 时优先使用")
    parser.add_argument("--demo", action="store_true", help="使用内置示例数据验证流程")
    args = parser.parse_args()
    if (args.before_dir is None) != (args.after_dir is None):
        parser.error("--before-dir 和 --after-dir 必须同时提供")
    if (args.before_stamp is None) != (args.after_stamp is None):
        parser.error("--before-stamp 和 --after-stamp 必须同时提供")
    return args


def require_columns(frame: pd.DataFrame, columns: set[str], source: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{source} 缺少字段: {', '.join(missing)}")


def read_scenario(directory: Path) -> dict[str, pd.DataFrame]:
    frames = {}
    for layer, file_name in FILE_NAMES.items():
        path = directory / file_name
        if not path.exists():
            raise FileNotFoundError(f"缺少 {path}；每个场景目录需包含 {list(FILE_NAMES.values())}")
        frames[layer] = pd.read_csv(path)
    return frames


def discover_run_stamps(directory: Path) -> list[str]:
    stamp_sets = []
    for prefix in RUN_FILE_PREFIXES.values():
        stamp_sets.append({path.stem.removeprefix(f"{prefix}_") for path in directory.glob(f"{prefix}_*.csv")})
    complete_stamps = sorted(set.intersection(*stamp_sets)) if stamp_sets else []
    if len(complete_stamps) < 2:
        raise ValueError(f"{directory} 至少需要两个包含五类 CSV 的完整时间戳批次")
    return complete_stamps


def read_timestamped_run(directory: Path, stamp: str) -> dict[str, pd.DataFrame]:
    frames = {}
    for layer, prefix in RUN_FILE_PREFIXES.items():
        path = directory / f"{prefix}_{stamp}.csv"
        if not path.exists():
            raise FileNotFoundError(f"批次 {stamp} 缺少 {path.name}")
        frames[layer] = pd.read_csv(path)
    return frames


def timestamp_column(frame: pd.DataFrame) -> str:
    for column in ("timestamp", "timestamp_utc"):
        if column in frame.columns:
            return column
    raise ValueError("CSV 缺少 timestamp 或 timestamp_utc 字段")


def simulation_hour_bounds(frames: dict[str, pd.DataFrame]) -> tuple[float, float]:
    vehicle = frames["vehicle"]
    if "sim_hour" not in vehicle.columns:
        return 0.0, float(elapsed_hours(vehicle[timestamp_column(vehicle)]).max())
    hours = pd.to_numeric(vehicle["sim_hour"], errors="raise")
    return float(hours.min()), float(hours.max())


def clip_to_simulation_hours(
    frames: dict[str, pd.DataFrame], start_hour: float, end_hour: float
) -> dict[str, pd.DataFrame]:
    vehicle = frames["vehicle"].copy()
    if "sim_hour" not in vehicle.columns:
        return frames
    vehicle["sim_hour"] = pd.to_numeric(vehicle["sim_hour"], errors="raise")
    time_key = timestamp_column(vehicle)
    hour_lookup = vehicle.groupby(time_key, as_index=False)["sim_hour"].mean()
    clipped = {}
    for layer, frame in frames.items():
        current = frame.copy()
        current_key = timestamp_column(current)
        if "sim_hour" not in current.columns:
            current = current.merge(
                hour_lookup.rename(columns={time_key: current_key}), on=current_key, how="left"
            )
        clipped[layer] = current[current["sim_hour"].between(start_hour, end_hour)].copy()
        if clipped[layer].empty:
            raise ValueError(f"{layer} 在共同仿真时段 {start_hour:.4f}-{end_hour:.4f} 内没有数据")
    return clipped


def elapsed_hours(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return (numeric - numeric.min()) / 3600.0
    timestamps = pd.to_datetime(values, errors="raise")
    return (timestamps - timestamps.min()).dt.total_seconds() / 3600.0


def aggregate_load(system: pd.DataFrame) -> pd.DataFrame:
    require_columns(system, {"total_charging_load_kW"}, "system.csv")
    time_key = "sim_hour" if "sim_hour" in system.columns else timestamp_column(system)
    load = system[[time_key, "total_charging_load_kW"]].copy()
    load["hour"] = (
        pd.to_numeric(load[time_key], errors="raise")
        if time_key == "sim_hour"
        else elapsed_hours(load[time_key])
    )
    load["load_kw"] = pd.to_numeric(load["total_charging_load_kW"], errors="raise")
    return load.groupby("hour", as_index=False)["load_kw"].mean().sort_values("hour")


def interval_hours(hours: pd.Series) -> pd.Series:
    intervals = hours.shift(-1) - hours
    positive = intervals[intervals > 0]
    fallback = float(positive.median()) if not positive.empty else 0.0
    return intervals.where(intervals > 0, fallback).fillna(fallback)


def route_entropy(route_ids: pd.Series) -> float:
    shares = route_ids.dropna().value_counts(normalize=True)
    if len(shares) <= 1:
        return 0.0
    entropy = -(shares * np.log(shares)).sum()
    return float(entropy / math.log(len(shares)))


def calculate_metrics(
    frames: dict[str, pd.DataFrame], carbon_factor: float, default_carbon_price: float
) -> ScenarioMetrics:
    vehicle = frames["vehicle"].copy()
    system = frames["system"].copy()
    charging = frames["charging"].copy()
    require_columns(vehicle, {"vehicle_id", "route_id"}, "vehicle.csv")
    timestamp_column(vehicle)
    require_columns(
        system,
        {"total_energy_kWh", "total_charging_load_kW", "total_distance_km", "electricity_price"},
        "system.csv",
    )
    timestamp_column(system)

    vehicle_time = "sim_hour" if "sim_hour" in vehicle.columns else timestamp_column(vehicle)
    vehicle["hour"] = (
        pd.to_numeric(vehicle[vehicle_time], errors="raise")
        if vehicle_time == "sim_hour"
        else elapsed_hours(vehicle[vehicle_time])
    )
    trip_hours = vehicle.groupby("vehicle_id")["hour"].agg(lambda values: values.max() - values.min())
    average_trip_hours = float(trip_hours.mean())
    entropy = route_entropy(vehicle.groupby("vehicle_id")["route_id"].first())

    energy_values = pd.to_numeric(system["total_energy_kWh"], errors="raise")
    distance_values = pd.to_numeric(system["total_distance_km"], errors="raise")
    total_energy = float(energy_values.max() - energy_values.min())
    total_distance = float(distance_values.max() - distance_values.min())
    energy_intensity = total_energy / max(total_distance, 1e-12)
    route_objective = average_trip_hours * energy_intensity * (2.0 - entropy)

    load = aggregate_load(system)
    intervals = interval_hours(load["hour"])
    charging_energy = float((load["load_kw"] * intervals).sum())
    system_time = "sim_hour" if "sim_hour" in system.columns else timestamp_column(system)
    price_by_hour = system[[system_time, "electricity_price"]].copy()
    price_by_hour["hour"] = (
        pd.to_numeric(price_by_hour[system_time], errors="raise")
        if system_time == "sim_hour"
        else elapsed_hours(price_by_hour[system_time])
    )
    price_by_hour["price"] = pd.to_numeric(price_by_hour["electricity_price"], errors="raise")
    price_by_hour = price_by_hour.groupby("hour", as_index=False)["price"].mean()
    priced_load = load.merge(price_by_hour, on="hour", how="left")
    charging_cost = float((priced_load["load_kw"] * interval_hours(priced_load["hour"]) * priced_load["price"]).sum())

    peak_valley = float(load["load_kw"].max() - load["load_kw"].min())
    load_factor = float(load["load_kw"].mean() / max(load["load_kw"].max(), 1e-12))
    emissions = charging_energy * carbon_factor
    tou_carbon_value = charging_cost / max(emissions, 1e-12)

    behavior = frames.get("behavior", pd.DataFrame())
    if "carbon_price" in behavior.columns and behavior["carbon_price"].notna().any():
        carbon_price = float(pd.to_numeric(behavior["carbon_price"], errors="coerce").dropna().mean())
    elif "carbon_price" in charging.columns and charging["carbon_price"].notna().any():
        carbon_price = float(pd.to_numeric(charging["carbon_price"], errors="coerce").dropna().mean())
    else:
        carbon_price = default_carbon_price
    carbon_cost = emissions / 1000.0 * carbon_price

    return ScenarioMetrics(
        average_trip_hours=average_trip_hours,
        route_entropy=entropy,
        energy_intensity_kwh_km=energy_intensity,
        route_objective=route_objective,
        charging_energy_kwh=charging_energy,
        charging_cost=charging_cost,
        peak_valley_kw=peak_valley,
        load_factor=load_factor,
        tou_carbon_value=tou_carbon_value,
        carbon_emissions_kg=emissions,
        carbon_cost=carbon_cost,
    )


def safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if abs(denominator) > 1e-12 else 1.0


def build_summary(before: ScenarioMetrics, after: ScenarioMetrics) -> pd.DataFrame:
    rows = [
        ("路径流量", before.route_objective, after.route_objective, "min"),
        ("充电时段", before.charging_cost, after.charging_cost, "min"),
        ("充电负荷", before.peak_valley_kw, after.peak_valley_kw, "min"),
        ("分时电价", before.tou_carbon_value, after.tou_carbon_value, "max"),
        ("碳价", before.carbon_emissions_kg, after.carbon_emissions_kg, "min"),
    ]
    benefit_ratios = [
        safe_ratio(before.route_objective, after.route_objective),
        safe_ratio(before.charging_cost, after.charging_cost),
        safe_ratio(before.peak_valley_kw, after.peak_valley_kw),
        safe_ratio(after.tou_carbon_value, before.tou_carbon_value),
        safe_ratio(before.carbon_emissions_kg, after.carbon_emissions_kg),
    ]
    system_score = float(np.prod(np.maximum(benefit_ratios, 1e-12)) ** (1.0 / len(benefit_ratios)))
    rows.append(("系统总效率", 1.0, system_score, "max"))

    records = []
    for name, before_value, after_value, direction in rows:
        if direction == "min":
            improvement = (1.0 - safe_ratio(after_value, before_value)) * 100.0
        else:
            improvement = (safe_ratio(after_value, before_value) - 1.0) * 100.0
        lower, upper, variables, objective = TARGETS[name]
        status = "达标" if lower <= improvement <= upper else ("低于目标" if improvement < lower else "高于目标")
        records.append({
            "优化对象": name,
            "目标": objective,
            "决策变量": variables,
            "优化前": before_value,
            "优化后": after_value,
            "改善率_%": improvement,
            "目标下限_%": lower,
            "目标上限_%": upper,
            "目标判定": status,
        })
    return pd.DataFrame(records)


def detailed_metrics(before: ScenarioMetrics, after: ScenarioMetrics) -> pd.DataFrame:
    names = {
        "average_trip_hours": "平均行程时间_h",
        "route_entropy": "路径流量均衡度",
        "energy_intensity_kwh_km": "单位里程能耗_kWh_km",
        "route_objective": "时间能耗综合目标",
        "charging_energy_kwh": "充电量_kWh",
        "charging_cost": "充电成本_元",
        "peak_valley_kw": "负荷峰谷差_kW",
        "load_factor": "负荷率",
        "tou_carbon_value": "收益碳排比_元_kgCO2",
        "carbon_emissions_kg": "碳排放_kgCO2",
        "carbon_cost": "碳成本_元",
    }
    return pd.DataFrame([
        {"指标": label, "优化前": getattr(before, field), "优化后": getattr(after, field)}
        for field, label in names.items()
    ])


def plot_results(
    summary: pd.DataFrame,
    before_load: pd.DataFrame,
    after_load: pd.DataFrame,
    output_dir: Path,
) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axes = plt.subplots(1, 2, figsize=(15, 6), constrained_layout=True)

    positions = np.arange(len(summary))
    improvements = summary["改善率_%"].to_numpy()
    colors = ["#157A6E" if status == "达标" else "#D97706" for status in summary["目标判定"]]
    axes[0].barh(positions, improvements, color=colors)
    for index, row in summary.iterrows():
        axes[0].plot([row["目标下限_%"], row["目标上限_%"]], [index, index], color="#222222", linewidth=4)
        axes[0].text(improvements[index], index, f" {improvements[index]:.1f}%", va="center")
    plot_labels = summary["优化对象"].map(PLOT_LABELS)
    axes[0].set_yticks(positions, plot_labels)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("Improvement (%)")
    axes[0].set_title("Optimization performance and target ranges")

    axes[1].plot(before_load["hour"], before_load["load_kw"], label="Before", color="#C2410C", linewidth=2)
    axes[1].plot(after_load["hour"], after_load["load_kw"], label="After", color="#157A6E", linewidth=2)
    axes[1].fill_between(after_load["hour"], after_load["load_kw"], alpha=0.16, color="#157A6E")
    axes[1].set_xlabel("Elapsed time (h)")
    axes[1].set_ylabel("Charging load (kW)")
    axes[1].set_title("Charging load profile")
    axes[1].legend(frameon=False)
    figure.savefig(output_dir / "optimization_dashboard.png", dpi=180)
    plt.close(figure)

    radar_labels = plot_labels.tolist()
    values = np.maximum(summary["改善率_%"].to_numpy(), 0.0)
    targets = summary["目标下限_%"].to_numpy()
    angles = np.linspace(0, 2 * np.pi, len(radar_labels), endpoint=False)
    values = np.r_[values, values[0]]
    targets = np.r_[targets, targets[0]]
    angles = np.r_[angles, angles[0]]
    figure, axis = plt.subplots(figsize=(8, 8), subplot_kw={"polar": True})
    axis.plot(angles, values, color="#157A6E", linewidth=2, label="Actual improvement")
    axis.fill(angles, values, color="#157A6E", alpha=0.22)
    axis.plot(angles, targets, color="#D97706", linestyle="--", label="Target lower bound")
    axis.set_xticks(angles[:-1], radar_labels)
    axis.set_title("Multi-objective optimization profile", pad=24)
    axis.legend(loc="upper right", bbox_to_anchor=(1.28, 1.12), frameon=False)
    figure.savefig(output_dir / "multi_objective_radar.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


def demo_scenario(optimized: bool) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    hours = np.arange(0.0, 24.0, 0.25)
    timestamps = hours * 3600
    base_load = 260 + 180 * np.exp(-((hours - 19) / 2.3) ** 2) + 70 * np.sin(hours * np.pi / 12) ** 2
    load = 335 + 30 * np.sin(hours * np.pi / 12) ** 2 if optimized else base_load
    price = np.where((hours >= 17) & (hours < 22), 1.25, np.where(hours < 7, 0.35, 0.72))
    if optimized:
        price = np.where((hours >= 17) & (hours < 22), 1.08, np.where(hours < 7, 0.30, 0.68))
    step_hours = 0.25
    cumulative_energy = np.cumsum((1500 if optimized else 1660) * step_hours * np.ones_like(hours))
    cumulative_distance = np.cumsum((8200 if optimized else 8000) * step_hours * np.ones_like(hours))
    system = pd.DataFrame({
        "timestamp": timestamps,
        "total_energy_kWh": cumulative_energy,
        "total_charging_load_kW": load,
        "total_distance_km": cumulative_distance,
        "electricity_price": price,
    })

    vehicle_rows = []
    for vehicle_id in range(120):
        duration = rng.uniform(0.55, 1.15) * (0.91 if optimized else 1.0)
        route = vehicle_id % 3 if optimized else (0 if vehicle_id < 82 else vehicle_id % 3)
        vehicle_rows.extend([
            {"vehicle_id": vehicle_id, "timestamp": 0.0, "route_id": route},
            {"vehicle_id": vehicle_id, "timestamp": duration * 3600, "route_id": route},
        ])
    vehicle = pd.DataFrame(vehicle_rows)
    road = pd.DataFrame({"timestamp": timestamps, "road_segment_id": 1, "vehicle_count": 120})
    charging = pd.DataFrame({"timestamp": timestamps, "charging_station_id": 1, "carbon_price": 52.0 if optimized else 45.0})
    return {"vehicle": vehicle, "road": road, "charging": charging, "system": system}


def main() -> None:
    args = parse_args()
    selection = {"数据来源": "内置演示", "优化前批次": "demo_before", "优化后批次": "demo_after"}
    if args.demo:
        before_frames = demo_scenario(False)
        after_frames = demo_scenario(True)
    elif args.before_dir is not None:
        before_frames = read_scenario(args.before_dir)
        after_frames = read_scenario(args.after_dir)
        selection = {"数据来源": "显式目录", "优化前批次": str(args.before_dir), "优化后批次": str(args.after_dir)}
    else:
        stamps = discover_run_stamps(args.samples_dir)
        before_stamp = args.before_stamp or stamps[0]
        after_stamp = args.after_stamp or stamps[-1]
        before_frames = read_timestamped_run(args.samples_dir, before_stamp)
        after_frames = read_timestamped_run(args.samples_dir, after_stamp)
        selection = {"数据来源": str(args.samples_dir), "优化前批次": before_stamp, "优化后批次": after_stamp}

        before_bounds = simulation_hour_bounds(before_frames)
        after_bounds = simulation_hour_bounds(after_frames)
        common_start = max(before_bounds[0], after_bounds[0])
        common_end = min(before_bounds[1], after_bounds[1])
        if common_start >= common_end:
            raise ValueError("所选批次没有共同的 sim_hour 区间，无法公平比较")
        before_frames = clip_to_simulation_hours(before_frames, common_start, common_end)
        after_frames = clip_to_simulation_hours(after_frames, common_start, common_end)
        selection.update({"共同起始_sim_hour": common_start, "共同结束_sim_hour": common_end})

        behavior_columns = ["beta_T", "lambda", "carbon_price", "route_choice_model", "charging_decision_rule"]
        before_behavior = before_frames["behavior"][behavior_columns].drop_duplicates().reset_index(drop=True)
        after_behavior = after_frames["behavior"][behavior_columns].drop_duplicates().reset_index(drop=True)
        if before_behavior.equals(after_behavior):
            warnings.warn("所选两个批次的行为与优化参数完全相同；结果表示重复运行差异，不代表优化效果。")

    before = calculate_metrics(before_frames, args.carbon_factor, args.carbon_price)
    after = calculate_metrics(after_frames, args.carbon_factor, args.carbon_price)
    summary = build_summary(before, after)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([selection]).to_csv(
        args.output_dir / "run_selection.csv", index=False, encoding="utf-8-sig"
    )
    summary.to_csv(args.output_dir / "optimization_summary.csv", index=False, encoding="utf-8-sig")
    detailed_metrics(before, after).to_csv(
        args.output_dir / "detailed_metrics.csv", index=False, encoding="utf-8-sig"
    )
    plot_results(summary, aggregate_load(before_frames["system"]), aggregate_load(after_frames["system"]), args.output_dir)

    print(summary.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
    print(f"\n结果已写入: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()