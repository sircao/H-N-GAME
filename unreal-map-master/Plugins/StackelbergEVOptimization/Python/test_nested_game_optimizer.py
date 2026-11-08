from __future__ import annotations

import unittest
import math
import numpy as np
import pandas as pd
from dataclasses import replace

import nested_game_optimizer as OPTIMIZER


class NestedGameOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        edge = OPTIMIZER.Edge
        self.graph = {
            (0, 0): {
                (1, 0): edge((0, 0), (1, 0), 1.0, 0.10, 20.0, 0.15),
                (0, 1): edge((0, 0), (0, 1), 1.1, 0.08, 20.0, 0.17),
            },
            (1, 0): {(2, 0): edge((1, 0), (2, 0), 1.0, 0.10, 20.0, 0.15)},
            (0, 1): {(2, 0): edge((0, 1), (2, 0), 1.1, 0.08, 20.0, 0.17)},
            (2, 0): {},
        }

    def test_k_shortest_paths_are_distinct(self) -> None:
        costs = {(start, end): item.free_time_h for start, edges in self.graph.items() for end, item in edges.items()}
        paths = OPTIMIZER.k_shortest_paths(self.graph, (0, 0), (2, 0), costs, 2)
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])

    def test_mnl_wardrop_conserves_od_demand(self) -> None:
        paths = [
            OPTIMIZER.PathState("od", "p0", [(0, 0), (1, 0), (2, 0)], 10.0),
            OPTIMIZER.PathState("od", "p1", [(0, 0), (0, 1), (2, 0)], 10.0),
        ]
        solved, minimum_costs, _, gap = OPTIMIZER.solve_follower_equilibrium(
            self.graph, paths, OPTIMIZER.ModelConfig(max_iterations=100), 45.0, 0.7
        )
        self.assertAlmostEqual(sum(path.flow for path in solved), 10.0, places=6)
        self.assertIn("od", minimum_costs)
        self.assertLess(gap, 1e-3)

    def paths(self):
        return [OPTIMIZER.PathState("od", "p0", [(0,0),(1,0),(2,0)], 10),
                OPTIMIZER.PathState("od", "p1", [(0,0),(0,1),(2,0)], 10)]

    def test_no_congestion_analytic(self):
        config = OPTIMIZER.ModelConfig(bpr_alpha=0, tolerance=1e-10)
        solved, _, _, gap = OPTIMIZER.solve_follower_equilibrium(self.graph, self.paths(), config, 0, 0)
        costs = [52.5*.2+.3, 52.5*.16+.34]
        expected = 10/(1+math.exp(costs[0]-costs[1]))
        self.assertAlmostEqual(solved[0].flow, expected, places=10)
        self.assertLessEqual(gap, config.tolerance)

    def test_initial_states_and_independent_bisection(self):
        config = OPTIMIZER.ModelConfig(max_iterations=20000, tolerance=1e-5)
        def residual(x):
            c0 = 52.5*.2*(1+.15*(x/20)**4)+.3
            c1 = 52.5*.16*(1+.15*((10-x)/20)**4)+.34
            return x-10/(1+math.exp(c0-c1))
        lo, hi = 0., 10.
        for _ in range(80):
            mid = (lo+hi)/2
            if residual(mid)>0: hi=mid
            else: lo=mid
        for x in (0., 5., 10.):
            solved, _, _, gap = OPTIMIZER.solve_follower_equilibrium(self.graph, self.paths(), config, 0, 0, {"p0": x, "p1": 10-x})
            self.assertAlmostEqual(sum(p.flow for p in solved), 10, places=10)
            self.assertAlmostEqual(solved[0].flow, (lo+hi)/2, delta=1e-5)
            self.assertAlmostEqual(gap, abs(residual(solved[0].flow)), places=10)
            self.assertLessEqual(gap, config.tolerance)

    def test_final_costs_after_iteration_limit(self):
        solved, _, _, gap = OPTIMIZER.solve_follower_equilibrium(self.graph, self.paths(), OPTIMIZER.ModelConfig(max_iterations=1), 0, 0)
        self.assertAlmostEqual(solved[0].travel_time_h, .2*(1+.15*(solved[0].flow/20)**4))
        self.assertGreater(gap, 0)

    def test_proportional_integer_allocation(self):
        paths = self.paths()
        paths[0].flow, paths[1].flow = 9, 1
        result = OPTIMIZER.proportional_paths(paths, 10)
        self.assertEqual(sum(p.path_id == "p0" for p in result), 9)

    def test_od_formats(self):
        for text in ("1.5,-2,42", "X=1.5 Y=-2 Z=42", "(X=1.5,Y=-2,Z=42)"):
            self.assertEqual(OPTIMIZER.parse_od_point(text), (1.5,-2))
        with self.assertRaises(ValueError): OPTIMIZER.parse_od_point("invalid")

    def test_parking_and_battery_limits(self):
        requirements = pd.DataFrame([dict(vehicle_id="v", energy_need_kwh=10, capacity_kwh=50, soc=50, parking_start_hour=8.5, parking_end_hour=10)])
        load, assignments = OPTIMIZER.allocate_charging(requirements, np.ones(24), np.zeros(24))
        self.assertEqual(assignments["v"], 9)
        self.assertEqual(load.sum(), 10)
        requirements.loc[0,"parking_end_hour"] = 9
        with self.assertRaises(ValueError): OPTIMIZER.allocate_charging(requirements, np.ones(24), np.zeros(24))
        requirements.loc[0,"energy_need_kwh"] = 26
        with self.assertRaises(ValueError): OPTIMIZER.allocate_charging(requirements, np.ones(24), np.zeros(24))


if __name__ == "__main__":
    unittest.main()
