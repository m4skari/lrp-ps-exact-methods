"""LP relaxation strengthened with minimal cover inequalities (MCI)."""

from __future__ import annotations

import itertools
import time
from typing import Dict

import numpy as np
import pulp

from compact_model.compact_mip import build_compact_model, _extract_solution, _solver


def minimal_cover_inequalities(instance: Dict, eligible: set[tuple[int, int]]) -> list[tuple[int, tuple[int, ...]]]:
    """Generate minimal covers for station-capacity knapsack constraints.

    For a station l, a cover C satisfies sum(q_i for i in C) > Q_l. It is
    minimal if removing any one customer makes it feasible. For binary z and v,
    the strengthened fixed-charge cover inequality is:

        sum_{i in C} z_il <= (|C| - 1) v_l

    This cuts fractional LP solutions while preserving every integer feasible
    LRP-PS solution.
    """
    n = instance["n_customers"]
    q = instance["demands"]
    covers: list[tuple[int, tuple[int, ...]]] = []
    for l in range(instance["n_stations"]):
        candidates = [i for i in range(n) if (i, l) in eligible]
        capacity = instance["Q_l"][l]
        for size in range(2, len(candidates) + 1):
            for subset in itertools.combinations(candidates, size):
                total = float(q[list(subset)].sum())
                if total <= capacity + 1e-9:
                    continue
                if all(total - q[i] <= capacity + 1e-9 for i in subset):
                    covers.append((l, tuple(subset)))
    return covers


def solve_lp_relaxation_mci(
    instance: Dict,
    time_limit: float = 300,
    solver_name: str = "gurobi",
    msg: bool = False,
) -> Dict:
    model, variables = build_compact_model(instance, preprocess=True, relax=True)
    eligible = set(variables["z"].keys())
    covers = minimal_cover_inequalities(instance, eligible)
    for idx, (l, subset) in enumerate(covers):
        model += (
            pulp.lpSum(variables["z"][(i, l)] for i in subset)
            <= (len(subset) - 1) * variables["v"][l],
            f"mci_station_{l}_{idx}",
        )

    started = time.perf_counter()
    try:
        model.solve(_solver(solver_name, time_limit, msg))
        runtime = time.perf_counter() - started
        status = pulp.LpStatus.get(model.status, str(model.status))
        objective = pulp.value(model.objective) if model.status > 0 else None
        solution = _fractional_solution(instance, variables) if objective is not None else {}
        return {
            "method": "lp_relaxation_mci",
            "status": status,
            "objective": objective,
            "runtime": runtime,
            "solution": solution,
            "n_variables": len(model.variables()),
            "n_constraints": len(model.constraints),
            "mci_count": len(covers),
            "preprocessing": variables["preprocessing"],
        }
    except Exception as exc:
        return {
            "method": "lp_relaxation_mci",
            "status": "error",
            "objective": None,
            "runtime": time.perf_counter() - started,
            "solution": {},
            "error": str(exc),
            "n_variables": len(model.variables()),
            "n_constraints": len(model.constraints),
            "mci_count": len(covers),
            "preprocessing": variables["preprocessing"],
        }


def _fractional_solution(instance: Dict, variables: Dict) -> Dict:
    n = instance["n_customers"]
    m = instance["n_stations"]
    z_values = {
        f"{i}_{l}": float(pulp.value(var) or 0.0)
        for (i, l), var in variables["z"].items()
        if abs(pulp.value(var) or 0.0) > 1e-8
    }
    w_values = {
        str(i): float(pulp.value(variables["w"][i]) or 0.0)
        for i in range(n)
        if abs(pulp.value(variables["w"][i]) or 0.0) > 1e-8
    }
    v_values = {
        str(l): float(pulp.value(variables["v"][l]) or 0.0)
        for l in range(m)
        if abs(pulp.value(variables["v"][l]) or 0.0) > 1e-8
    }
    return {"v": v_values, "z": z_values, "w": w_values}


def solution_service_metrics(instance: Dict, result: Dict) -> Dict:
    """Demand split and large-GV station replenishment accounting."""
    q = instance["demands"]
    n = instance["n_customers"]
    total_demand = float(q.sum())
    solution = result.get("solution", {})

    if "station_assignments" in solution:
        station_customers = {
            int(l): [int(i) for i in customers]
            for l, customers in solution.get("station_assignments", {}).items()
        }
        facility_demand = float(sum(q[customers].sum() for customers in station_customers.values() if customers))
        small_gv_customers = [int(i) for i in solution.get("direct_customers", [])]
        small_gv_demand = float(q[small_gv_customers].sum()) if small_gv_customers else 0.0
        opened = sorted(station_customers)
    elif "z" in solution:
        facility_demand = 0.0
        per_station = {l: 0.0 for l in range(instance["n_stations"])}
        for key, value in solution["z"].items():
            i, l = (int(part) for part in key.split("_"))
            amount = float(value) * q[i]
            facility_demand += amount
            per_station[l] += amount
        small_gv_demand = sum(float(solution["w"].get(str(i), 0.0)) * q[i] for i in range(n))
        opened = [l for l, amount in per_station.items() if amount > 1e-8]
    else:
        facility_demand = 0.0
        small_gv_demand = 0.0
        opened = []

    full_large_gv_cost = 0.0
    charged_large_gv_cost = 0.0
    for l in opened:
        station_node = n + 1 + l
        round_trip = float(instance["dist"][0, station_node] + instance["dist"][station_node, 0])
        full_large_gv_cost += round_trip
        charged_large_gv_cost += instance["phi"] * round_trip

    return {
        "total_demand": total_demand,
        "facility_demand": facility_demand,
        "small_gv_demand": small_gv_demand,
        "facility_share": facility_demand / total_demand if total_demand else 0.0,
        "small_gv_share": small_gv_demand / total_demand if total_demand else 0.0,
        "opened_stations": len(opened),
        "small_gv_routes": len(solution.get("routes", [])),
        "max_small_gvs": int(instance.get("N_e", n)),
        "large_gv_full_roundtrip_cost": full_large_gv_cost,
        "large_gv_charged_cost_phi": charged_large_gv_cost,
        "large_gv_travel_saving": full_large_gv_cost - charged_large_gv_cost,
        "phi": float(instance["phi"]),
    }
