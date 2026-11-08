from __future__ import annotations

import argparse
import csv
import heapq
import math
import re
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED_PREFIXES = ("datalist", "road", "charging", "system", "behavior")
VEHICLE_ENERGY_KWH_KM = {
    "Sedan": 0.135,
    "SUV": 0.170,
    "Hatch": 0.120,
    "MiniBus": 0.260,
}


@dataclass(frozen=True)
class Edge:
    start: tuple[int, int]
    end: tuple[int, int]
    distance_km: float
    free_time_h: float
    capacity: float
    energy_kwh: float


@dataclass
class PathState:
    od_id: str
    path_id: str
    nodes: list[tuple[int, int]]
    demand: float
    flow: float = 0.0
    travel_time_h: float = 0.0
    energy_kwh: float = 0.0
    carbon_ton: float = 0.0
    generalized_cost: float = 0.0


@dataclass(frozen=True)
class ModelConfig:
    beta_t: float = 52.5
    energy_weight: float = 1.0
    carbon_factor_kg_kwh: float = 0.5703
    k_paths: int = 5
    mnl_theta: float = 1.0
    tolerance: float = 1e-3
    max_iterations: int = 200
    bpr_alpha: float = 0.15
    bpr_power: float = 4.0
    grid_cm: float = 500.0
    default_capacity: float = 12.0
    leader_carbon_weight: float = 0.05


def parse_args() -> argparse.Namespace:
    project_dir = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Audited finite-day route/charging scheduling. Historical MNL helpers are retained as separate diagnostics, not a coupled-equilibrium claim.")
    parser.add_argument('--task-contract', type=Path, default=Path(__file__).resolve().parents[4] / 'experiments/scientific/canonical_scenario.json')
    parser.add_argument('--time-limit', type=float, default=120.)
    parser.add_argument("--samples-dir", type=Path, default=project_dir / "Saved" / "EVTrafficSamples")
    parser.add_argument("--stamp", help="Input run timestamp; defaults to the latest complete run")
    parser.add_argument("--output-dir", type=Path, default=project_dir / "Saved" / "StackelbergEVOptimization")
    parser.add_argument("--beta-t", type=float, default=52.5)
    parser.add_argument("--energy-weight", type=float, default=1.0)
    parser.add_argument("--carbon-price", type=float, default=45.0)
    parser.add_argument("--carbon-factor", type=float, default=0.5703)
    parser.add_argument("--k-paths", type=int, default=5)
    parser.add_argument("--mnl-theta", type=float, default=1.0)
    parser.add_argument("--max-iterations", type=int, default=200)
    parser.add_argument("--tolerance", type=float, default=1e-3)
    parser.add_argument("--leader-iterations", type=int, default=4)
    return parser.parse_args()


def discover_stamps(directory: Path) -> list[str]:
    groups = [
        {path.stem.removeprefix(prefix + "_") for path in directory.glob(prefix + "_*.csv")}
        for prefix in REQUIRED_PREFIXES
    ]
    stamps = sorted(set.intersection(*groups)) if groups else []
    if not stamps:
        raise FileNotFoundError(f"No complete simulation run found in {directory}")
    return stamps


def load_run(directory: Path, stamp: str) -> dict[str, pd.DataFrame]:
    return {prefix: pd.read_csv(directory / f"{prefix}_{stamp}.csv") for prefix in REQUIRED_PREFIXES}


def quantize(x: float, y: float, grid_cm: float) -> tuple[int, int]:
    return round(x / grid_cm), round(y / grid_cm)


def world_point(node: tuple[int, int], grid_cm: float, z_cm: float = 42.0) -> tuple[float, float, float]:
    return node[0] * grid_cm, node[1] * grid_cm, z_cm


def parse_od_point(text: str) -> tuple[float, float]:
    """Accept CSV x,y,z and Unreal FVector X=... Y=... Z=... strings."""
    values = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", str(text))
    if len(values) not in (2, 3):
        raise ValueError(f"Invalid OD point: {text!r}")
    point = tuple(map(float, values[:2]))
    if not all(math.isfinite(v) for v in point):
        raise ValueError(f"Nonfinite OD point: {text!r}")
    return point


def proportional_paths(paths: list[PathState], count: int) -> list[PathState]:
    weights = np.array([p.flow for p in paths], dtype=float)
    if not len(paths) or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("Cannot allocate vehicles without positive equilibrium flow")
    quotas = weights / weights.sum() * count
    counts = np.floor(quotas).astype(int)
    for i in np.argsort(-(quotas - counts), kind="stable")[:count - counts.sum()]:
        counts[i] += 1
    return [p for p, n in zip(paths, counts) for _ in range(n)]


def build_empirical_network(
    vehicle: pd.DataFrame, config: ModelConfig
) -> tuple[dict[tuple[int, int], dict[tuple[int, int], Edge]], dict[str, list[str]], dict[str, tuple[tuple[int, int], tuple[int, int]]]]:
    required = {"vehicle_id", "elapsed_sec", "lon", "lat", "od_origin", "od_destination", "vehicle_type"}
    missing = required - set(vehicle.columns)
    if missing:
        raise ValueError(f"datalist is missing columns: {sorted(missing)}")

    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]] = defaultdict(dict)
    od_vehicles: dict[str, list[str]] = defaultdict(list)
    od_nodes: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {}
    energy_samples: dict[tuple[tuple[int, int], tuple[int, int]], list[float]] = defaultdict(list)
    speed_samples: dict[tuple[tuple[int, int], tuple[int, int]], list[float]] = defaultdict(list)

    ordered = vehicle.sort_values(["vehicle_id", "elapsed_sec"])
    for vehicle_id, group in ordered.groupby("vehicle_id", sort=False):
        vehicle_type = str(group["vehicle_type"].iloc[0])
        rate = VEHICLE_ENERGY_KWH_KM.get(vehicle_type, 0.16)
        origin_text = str(group["od_origin"].iloc[0])
        destination_text = str(group["od_destination"].iloc[0])
        od_id = f"{origin_text}->{destination_text}"
        od_vehicles[od_id].append(str(vehicle_id))

        origin_values = parse_od_point(origin_text)
        destination_values = parse_od_point(destination_text)
        origin = quantize(origin_values[0], origin_values[1], config.grid_cm)
        destination = quantize(destination_values[0], destination_values[1], config.grid_cm)
        od_nodes[od_id] = (origin, destination)

        previous = None
        for row in group.itertuples(index=False):
            node = quantize(float(row.lon), float(row.lat), config.grid_cm)
            if previous is not None and node != previous:
                for start, end in ((previous, node), (node, previous)):
                    distance_km = math.dist(start, end) * config.grid_cm / 100000.0
                    edge_key = (start, end)
                    energy_samples[edge_key].append(distance_km * rate)
                    speed_kmh = max(float(getattr(row, "speed", 0.0)) * 0.036, 5.0)
                    speed_samples[edge_key].append(speed_kmh)
            previous = node

    for (start, end), energies in energy_samples.items():
        distance_km = math.dist(start, end) * config.grid_cm / 100000.0
        speed_kmh = float(np.median(speed_samples[(start, end)]))
        graph[start][end] = Edge(
            start=start,
            end=end,
            distance_km=distance_km,
            free_time_h=distance_km / max(speed_kmh, 5.0),
            capacity=config.default_capacity,
            energy_kwh=float(np.mean(energies)),
        )

    nodes = list(graph)
    if not nodes:
        raise ValueError("No traversed network edges could be reconstructed")
    for od_id, (origin, destination) in list(od_nodes.items()):
        nearest_origin = min(nodes, key=lambda node: math.dist(node, origin))
        nearest_destination = min(nodes, key=lambda node: math.dist(node, destination))
        od_nodes[od_id] = (nearest_origin, nearest_destination)
    return graph, dict(od_vehicles), od_nodes


def shortest_path(
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    origin: tuple[int, int],
    destination: tuple[int, int],
    edge_cost: dict[tuple[tuple[int, int], tuple[int, int]], float],
    banned_edges: set[tuple[tuple[int, int], tuple[int, int]]] | None = None,
    banned_nodes: set[tuple[int, int]] | None = None,
) -> tuple[float, list[tuple[int, int]]] | None:
    banned_edges = banned_edges or set()
    banned_nodes = banned_nodes or set()
    queue = [(0.0, origin, [origin])]
    best = {origin: 0.0}
    while queue:
        cost, node, path = heapq.heappop(queue)
        if node == destination:
            return cost, path
        if cost > best.get(node, math.inf):
            continue
        for next_node in graph.get(node, {}):
            if next_node in banned_nodes or (node, next_node) in banned_edges:
                continue
            next_cost = cost + edge_cost[(node, next_node)]
            if next_cost < best.get(next_node, math.inf):
                best[next_node] = next_cost
                heapq.heappush(queue, (next_cost, next_node, path + [next_node]))
    return None


def path_cost(nodes: list[tuple[int, int]], edge_cost: dict[tuple[tuple[int, int], tuple[int, int]], float]) -> float:
    return sum(edge_cost[(nodes[index - 1], nodes[index])] for index in range(1, len(nodes)))


def k_shortest_paths(
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    origin: tuple[int, int],
    destination: tuple[int, int],
    edge_cost: dict[tuple[tuple[int, int], tuple[int, int]], float],
    count: int,
) -> list[list[tuple[int, int]]]:
    first = shortest_path(graph, origin, destination, edge_cost)
    if first is None:
        return []
    accepted = [first[1]]
    candidates: list[tuple[float, list[tuple[int, int]]]] = []
    candidate_keys: set[tuple[tuple[int, int], ...]] = set()
    for _ in range(1, count):
        previous = accepted[-1]
        for spur_index in range(len(previous) - 1):
            root = previous[: spur_index + 1]
            banned_edges = set()
            for path in accepted:
                if len(path) > spur_index and path[: spur_index + 1] == root:
                    banned_edges.add((path[spur_index], path[spur_index + 1]))
            spur = shortest_path(
                graph,
                root[-1],
                destination,
                edge_cost,
                banned_edges=banned_edges,
                banned_nodes=set(root[:-1]),
            )
            if spur is None:
                continue
            candidate = root[:-1] + spur[1]
            key = tuple(candidate)
            if key in candidate_keys or any(candidate == path for path in accepted):
                continue
            heapq.heappush(candidates, (path_cost(candidate, edge_cost), candidate))
            candidate_keys.add(key)
        if not candidates:
            break
        accepted.append(heapq.heappop(candidates)[1])
    return accepted


def build_path_set(
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    od_vehicles: dict[str, list[str]],
    od_nodes: dict[str, tuple[tuple[int, int], tuple[int, int]]],
    config: ModelConfig,
) -> list[PathState]:
    edge_cost = {(start, end): edge.free_time_h for start, links in graph.items() for end, edge in links.items()}
    paths = []
    for od_index, (od_id, vehicles) in enumerate(od_vehicles.items()):
        origin, destination = od_nodes[od_id]
        if origin == destination:
            neighbors = sorted(graph.get(origin, {}), key=lambda node: edge_cost[(origin, node)])
            candidates = [
                [origin, neighbor, origin]
                for neighbor in neighbors[:config.k_paths]
                if origin in graph.get(neighbor, {})
            ]
        else:
            candidates = k_shortest_paths(graph, origin, destination, edge_cost, config.k_paths)
        if not candidates:
            raise ValueError(f"No candidate path for OD {od_id}")
        for path_index, nodes in enumerate(candidates):
            paths.append(PathState(od_id, f"OD{od_index:04d}_P{path_index:02d}", nodes, float(len(vehicles))))
    if not paths:
        raise ValueError("No candidate path connects the observed OD pairs")
    return paths


def solve_follower_equilibrium(
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    template_paths: list[PathState],
    config: ModelConfig,
    carbon_price: float,
    charging_price: float,
    initial_flows: dict[str, float] | None = None,
) -> tuple[list[PathState], dict[str, float], int, float]:
    paths = [PathState(path.od_id, path.path_id, list(path.nodes), path.demand) for path in template_paths]
    by_od: dict[str, list[PathState]] = defaultdict(list)
    for path in paths:
        by_od[path.od_id].append(path)
        path.flow = path.demand / max(sum(item.od_id == path.od_id for item in paths), 1)

    if initial_flows is not None:
        for od_paths in by_od.values():
            values = [initial_flows[p.path_id] for p in od_paths]
            if any(not math.isfinite(v) or v < 0 for v in values) or not math.isclose(sum(values), od_paths[0].demand):
                raise ValueError("Initial flows must conserve each OD demand")
            for p, v in zip(od_paths, values):
                p.flow = v
    if config.max_iterations < 1:
        raise ValueError("max_iterations must be positive")

    def evaluate():
        edge_flows: dict[tuple[tuple[int, int], tuple[int, int]], float] = defaultdict(float)
        for path in paths:
            for index in range(1, len(path.nodes)):
                edge_flows[(path.nodes[index - 1], path.nodes[index])] += path.flow

        auxiliary = {}
        for od_id, od_paths in by_od.items():
            costs = []
            for path in od_paths:
                travel_time = 0.0
                energy = 0.0
                for index in range(1, len(path.nodes)):
                    key = (path.nodes[index - 1], path.nodes[index])
                    edge = graph[key[0]][key[1]]
                    ratio = edge_flows[key] / max(edge.capacity, 1e-9)
                    travel_time += edge.free_time_h * (1.0 + config.bpr_alpha * ratio ** config.bpr_power)
                    energy += edge.energy_kwh
                carbon_ton = energy * config.carbon_factor_kg_kwh / 1000.0
                path.travel_time_h = travel_time
                path.energy_kwh = energy
                path.carbon_ton = carbon_ton
                path.generalized_cost = (
                    config.beta_t * travel_time
                    + config.energy_weight * energy
                    + charging_price * energy
                    + carbon_price * carbon_ton
                )
                costs.append(path.generalized_cost)
            shifted = np.asarray(costs) - min(costs)
            probabilities = np.exp(-config.mnl_theta * np.clip(shifted, 0.0, 700.0))
            probabilities /= probabilities.sum()
            demand = od_paths[0].demand
            for path, probability in zip(od_paths, probabilities):
                auxiliary[path.path_id] = demand * float(probability)

        return auxiliary

    gap = math.inf
    for iteration in range(1, config.max_iterations + 1):
        auxiliary = evaluate()
        gap = max(abs(auxiliary[p.path_id] - p.flow) for p in paths)
        if gap <= config.tolerance:
            break
        step = 1.0 / iteration
        for path in paths:
            path.flow += step * (auxiliary[path.path_id] - path.flow)
    auxiliary = evaluate()
    gap = max(abs(auxiliary[p.path_id] - p.flow) for p in paths)

    minimum_costs = {od_id: min(path.generalized_cost for path in od_paths) for od_id, od_paths in by_od.items()}
    return paths, minimum_costs, iteration, gap


def charging_requirements(vehicle: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for vehicle_id, group in vehicle.sort_values("elapsed_sec").groupby("vehicle_id"):
        first = group.iloc[0]
        capacity = float(first.battery_capacity_kWh)
        initial_soc = float(first.soc)
        if not math.isfinite(capacity) or capacity <= 0 or not 0 <= initial_soc <= 100:
            raise ValueError(f"Invalid battery state for {vehicle_id}")
        # Require explicit parking windows: a departure alone cannot describe availability.
        if not {"parking_start_hour", "parking_end_hour"} <= set(group.columns):
            raise ValueError("Baseline lacks parking_start_hour/parking_end_hour; export task parking windows before optimization")
        start, end = float(first.parking_start_hour), float(first.parking_end_hour)
        if not 0 <= start <= end <= 24:
            raise ValueError(f"Invalid parking window for {vehicle_id}")
        minimum_soc = float(group.soc.min())
        if not 0 <= minimum_soc <= 100:
            raise ValueError(f"Invalid observed SOC for {vehicle_id}")
        rows.append(dict(vehicle_id=str(vehicle_id), soc=minimum_soc, initial_soc=initial_soc,
                         capacity_kwh=capacity, departure_time=float(first.departure_time),
                         parking_start_hour=start, parking_end_hour=end,
                         energy_need_kwh=max(0.0, (80.0-minimum_soc)*0.01*capacity)))
    return pd.DataFrame(rows)


def allocate_charging(requirements: pd.DataFrame, prices: np.ndarray, base_load: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    if len(prices) != 24 or len(base_load) != 24 or not np.isfinite(prices).all() or not np.isfinite(base_load).all():
        raise ValueError("Expected 24 finite hourly prices and loads")
    load = base_load.astype(float).copy()
    assignments = {}
    for row in requirements.sort_values("energy_need_kwh", ascending=False).itertuples(index=False):
        need = float(row.energy_need_kwh)
        if not math.isfinite(need) or need < 0 or need > float(row.capacity_kwh)*(1-float(row.soc)/100)+1e-9:
            raise ValueError(f"Charging violates battery bounds: {row.vehicle_id}")
        if need == 0:
            assignments[str(row.vehicle_id)] = -1
            continue
        feasible = np.array([h for h in range(24) if h >= row.parking_start_hour and h+1 <= row.parking_end_hour], dtype=int)
        if not len(feasible) or need > 60:
            raise ValueError(f"No feasible one-hour charging slot for {row.vehicle_id}")
        score = prices + 0.002 * load
        hour = int(feasible[np.argmin(score[feasible])])
        load[hour] += need
        assignments[str(row.vehicle_id)] = hour
    return load, assignments


def leader_search(
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    template_paths: list[PathState],
    requirements: pd.DataFrame,
    system: pd.DataFrame,
    config: ModelConfig,
    initial_carbon_price: float,
    iterations: int,
) -> tuple[np.ndarray, float, list[PathState], dict[str, int], dict[str, float]]:
    system_hours = pd.to_datetime(system["timestamp_utc"], errors="coerce").dt.hour
    base_load = system.groupby(system_hours)["total_charging_load_kW"].mean().reindex(range(24), fill_value=0.0).to_numpy()
    prices = np.full(24, 0.70)
    prices[:7] = 0.35
    prices[17:22] = 1.20
    carbon_price = initial_carbon_price
    best = None

    for search_iteration in range(iterations):
        price_step = 0.20 / (search_iteration + 1)
        carbon_step = 20.0 / (search_iteration + 1)
        candidates = []
        for peak_delta in (-price_step, 0.0, price_step):
            for offpeak_delta in (-price_step, 0.0, price_step):
                for carbon_delta in (-carbon_step, 0.0, carbon_step):
                    candidate_prices = prices.copy()
                    candidate_prices[:7] = np.clip(candidate_prices[:7] + offpeak_delta, 0.30, 1.50)
                    candidate_prices[17:22] = np.clip(candidate_prices[17:22] + peak_delta, 0.30, 1.50)
                    candidate_carbon = float(np.clip(carbon_price + carbon_delta, 5.0, 100.0))
                    equilibrium, _, _, _ = solve_follower_equilibrium(
                        graph, template_paths, config, candidate_carbon, float(candidate_prices.mean())
                    )
                    charging_load, assignments = allocate_charging(requirements, candidate_prices, base_load)
                    charged_energy = float(requirements["energy_need_kwh"].sum())
                    route_energy = sum(path.flow * path.energy_kwh for path in equilibrium)
                    carbon_kg = (charged_energy + route_energy) * config.carbon_factor_kg_kwh
                    revenue = float(np.sum((charging_load - base_load) * candidate_prices))
                    objective = revenue - config.leader_carbon_weight * carbon_kg
                    candidates.append((objective, candidate_prices, candidate_carbon, equilibrium, assignments, revenue, carbon_kg, charging_load))
        best = max(candidates, key=lambda candidate: candidate[0])
        _, prices, carbon_price, _, _, _, _, _ = best

    assert best is not None
    objective, prices, carbon_price, equilibrium, assignments, revenue, carbon_kg, charging_load = best
    metrics = {
        "leader_objective": objective,
        "revenue_yuan": revenue,
        "carbon_kg": carbon_kg,
        "carbon_price_yuan_ton": carbon_price,
    }
    metrics.update({f"load_hour_{hour:02d}_kw": float(charging_load[hour]) for hour in range(24)})
    return prices, carbon_price, equilibrium, assignments, metrics


def path_rows(paths: Iterable[PathState]) -> list[dict[str, object]]:
    rows = []
    for path in paths:
        rows.append({
            "od_id": path.od_id,
            "path_id": path.path_id,
            "equilibrium_flow": path.flow,
            "generalized_cost": path.generalized_cost,
            "travel_time_h": path.travel_time_h,
            "energy_kwh": path.energy_kwh,
            "carbon_ton": path.carbon_ton,
            "node_count": len(path.nodes),
        })
    return rows


def write_outputs(
    output_dir: Path,
    stamp: str,
    graph: dict[tuple[int, int], dict[tuple[int, int], Edge]],
    paths: list[PathState],
    minimum_costs: dict[str, float],
    od_vehicles: dict[str, list[str]],
    requirements: pd.DataFrame,
    assignments: dict[str, int],
    prices: np.ndarray,
    carbon_price: float,
    metrics: dict[str, float],
    config: ModelConfig,
    iterations: int,
    gap: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(path_rows(paths)).to_csv(output_dir / "equilibrium_path_flows.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"od_id": key, "minimum_generalized_cost": value} for key, value in minimum_costs.items()]).to_csv(
        output_dir / "od_minimum_costs.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([{"hour": hour, "electricity_price": price} for hour, price in enumerate(prices)]).to_csv(
        output_dir / "optimal_price_curve.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([
        {"hour": hour, "optimized_charging_load_kW": metrics[f"load_hour_{hour:02d}_kw"]}
        for hour in range(24)
    ]).to_csv(output_dir / "optimal_charging_load.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics | {"input_stamp": stamp, "wardrop_iterations": iterations, "wardrop_gap": gap, "converged": gap <= config.tolerance, "demand_residual": max(abs(sum(p.flow for p in paths if p.od_id == od) - ps[0].demand) for od in od_vehicles for ps in [[p for p in paths if p.od_id == od]] if ps)}]).to_csv(
        output_dir / "leader_summary.csv", index=False, encoding="utf-8-sig"
    )

    pareto = pd.DataFrame(path_rows(paths))[['od_id', 'path_id', 'travel_time_h', 'energy_kwh']]
    pareto["pareto_optimal"] = False
    for _, group in pareto.groupby("od_id"):
        for index, row in group.iterrows():
            dominated = ((group["travel_time_h"] <= row["travel_time_h"]) & (group["energy_kwh"] <= row["energy_kwh"]) & ((group["travel_time_h"] < row["travel_time_h"]) | (group["energy_kwh"] < row["energy_kwh"]))).any()
            pareto.loc[index, "pareto_optimal"] = not dominated
    pareto.to_csv(output_dir / "time_energy_pareto.csv", index=False, encoding="utf-8-sig")

    by_od: dict[str, list[PathState]] = defaultdict(list)
    for path in paths:
        by_od[path.od_id].append(path)
    requirement_map = requirements.set_index(requirements["vehicle_id"].astype(str))["energy_need_kwh"].to_dict()
    departure_map = requirements.set_index(requirements["vehicle_id"].astype(str))["departure_time"].to_dict()
    plan_rows = []
    for od_id, vehicle_ids in od_vehicles.items():
        candidates = sorted(by_od.get(od_id, []), key=lambda path: (-path.flow, path.generalized_cost))
        if not candidates:
            raise ValueError(f"No route for OD {od_id}")
        allocated = proportional_paths(candidates, len(vehicle_ids))
        for vehicle_id, path in zip(vehicle_ids, allocated):
            points = [world_point(node, config.grid_cm) for node in path.nodes]
            path_text = ";".join(f"{x:.1f},{y:.1f},{z:.1f}" for x, y, z in points)
            charge_hour = assignments.get(str(vehicle_id), -1)
            departure_hour = float(departure_map.get(str(vehicle_id), 6.0))
            plan_rows.append({
                "vehicle_id": str(vehicle_id).zfill(4),
                "task_id": f"{stamp}:{vehicle_id}",
                "initial_soc": float(requirements.set_index("vehicle_id").loc[str(vehicle_id), "initial_soc"]),
                "battery_capacity_kwh": float(requirements.set_index("vehicle_id").loc[str(vehicle_id), "capacity_kwh"]),
                "route_id": path.path_id,
                "path_points": path_text,
                "departure_hour": departure_hour,
                "arrival_hour": departure_hour + max(path.travel_time_h, 0.05),
                "charging_start_hour": charge_hour,
                "charging_end_hour": charge_hour + 1 if charge_hour >= 0 else -1,
                "charging_energy_kwh": float(requirement_map.get(str(vehicle_id), 0.0)),
                "carbon_price": carbon_price,
            })
    pd.DataFrame(plan_rows).to_csv(output_dir / "optimized_plan.csv", index=False, quoting=csv.QUOTE_MINIMAL)


def legacy_main() -> None:
    raise RuntimeError('Historical incomplete coupling is disabled. Use main() with the explicit finite-day physical contract.')
    args = parse_args()
    config = ModelConfig(
        beta_t=args.beta_t,
        energy_weight=args.energy_weight,
        carbon_factor_kg_kwh=args.carbon_factor,
        k_paths=max(args.k_paths, 1),
        mnl_theta=max(args.mnl_theta, 1e-6),
        tolerance=max(args.tolerance, 1e-9),
        max_iterations=max(args.max_iterations, 1),
    )
    stamps = discover_stamps(args.samples_dir)
    stamp = args.stamp or stamps[-1]
    frames = load_run(args.samples_dir, stamp)
    graph, od_vehicles, od_nodes = build_empirical_network(frames["datalist"], config)
    template_paths = build_path_set(graph, od_vehicles, od_nodes, config)
    requirements = charging_requirements(frames["datalist"])
    prices, carbon_price, paths, assignments, metrics = leader_search(
        graph,
        template_paths,
        requirements,
        frames["system"],
        config,
        args.carbon_price,
        max(args.leader_iterations, 1),
    )
    final_paths, minimum_costs, iterations, gap = solve_follower_equilibrium(
        graph, paths, config, carbon_price, float(prices.mean())
    )
    if gap > config.tolerance:
        raise RuntimeError(f"Final MNL equilibrium did not converge: iterations={iterations}, residual={gap:.9g}")
    write_outputs(
        args.output_dir,
        stamp,
        graph,
        final_paths,
        minimum_costs,
        od_vehicles,
        requirements,
        assignments,
        prices,
        carbon_price,
        metrics,
        config,
        iterations,
        gap,
    )
    print(f"Input run: {stamp}")
    print(f"Network: {len(graph)} nodes, {sum(len(edges) for edges in graph.values())} directed edges")
    print(f"OD pairs: {len(od_vehicles)}, candidate paths: {len(final_paths)}")
    print(f"Wardrop/MNL: converged={gap <= config.tolerance}, iterations={iterations}, final_residual={gap:.6g}")
    print(f"Stackelberg: carbon_price={carbon_price:.3f}, revenue={metrics['revenue_yuan']:.3f}, carbon={metrics['carbon_kg']:.3f} kg")
    print(f"Outputs: {args.output_dir.resolve()}")


def main() -> None:
    """Production entry point: a complete physical contract is mandatory.

    The old mean-price/minimum-SOC coupling is not used. It remains above only
    for historical inspection; its helpers are not equilibrium certification.
    """
    args = parse_args()
    if args.stamp:
        raise SystemExit('A sampled CSV timestamp is not a complete task contract. Export the map and build canonical_scenario.json, then pass --task-contract.')
    if not args.task_contract.exists():
        raise SystemExit('Missing physical task contract. Run experiments/export_unreal_scene.py in Unreal, then experiments/build_scientific_scenario.py.')
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'experiments'))
    from scientific_model import optimize, metrics
    from scientific_audit import check, compare_metrics
    from scientific_io import export_event_csv, save_json_gz
    spec = json.loads(args.task_contract.read_text())
    status, events = optimize(spec, time_limit=args.time_limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'scientific_solver_status.json').write_text(json.dumps(status, indent=2))
    if status['status'] != 'optimal':
        raise SystemExit('No certified plan exported: ' + status['status'])
    result = metrics(spec, events)
    audit = check(spec, events)
    compare_metrics(result, audit['metrics'])
    export_event_csv(args.output_dir / 'scientific_plan.csv', spec, events)
    save_json_gz(args.output_dir / 'scientific_events.json.gz', events)
    (args.output_dir / 'scientific_summary.json').write_text(json.dumps(dict(status=status, metrics=result,
        audit={k:v for k,v in audit.items() if k not in ('ledger','user_costs','metrics')},
        scope='Finite centralized full-day scheduling; no Stackelberg equilibrium or empirical city validation claim.'), indent=2))
    print(json.dumps(dict(status=status['status'], vehicles=audit['vehicles'], trips=audit['trips'], output=str(args.output_dir))))


if __name__ == '__main__':
    main()
