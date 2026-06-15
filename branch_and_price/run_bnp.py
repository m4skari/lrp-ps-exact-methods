"""Paper-based Dantzig-Wolfe decomposition and exact column master.

For the experiment sizes used here, all nondominated pattern and route columns
can be completed explicitly. Column generation reproduces the paper's LP
procedure; HiGHS then performs branch-and-bound on the complete integer master.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csc_matrix


def _bits(mask: int, n: int) -> list[int]:
    return [i for i in range(n) if mask & (1 << i)]


def enumerate_patterns(instance: Dict) -> list[Dict]:
    n, m = instance["n_customers"], instance["n_stations"]
    q, dist = instance["demands"], instance["dist"]
    patterns = []
    for l in range(m):
        station_node = n + 1 + l
        eligible_mask = 0
        for i in range(n):
            if dist[i + 1, station_node] <= instance["r_l"][l] + 1e-9:
                eligible_mask |= 1 << i
        sub = eligible_mask
        while sub:
            customers = _bits(sub, n)
            load = float(q[customers].sum())
            if load <= instance["Q_l"][l] + 1e-9:
                patterns.append(
                    {
                        "station": l,
                        "mask": sub,
                        "customers": customers,
                        "cost": float(instance["a_l"][l] * load),
                    }
                )
            sub = (sub - 1) & eligible_mask
    return patterns


def enumerate_routes(instance: Dict) -> list[Dict]:
    """One shortest feasible elementary route for every customer subset."""
    n = instance["n_customers"]
    q = instance["demands"]
    dist = instance["dist"]
    capacity = float(instance.get("Q_e", instance["Q_c"]))
    max_distance = float(instance["B"] / instance["h"])
    size = 1 << n
    loads = np.zeros(size)
    for mask in range(1, size):
        bit = mask & -mask
        i = bit.bit_length() - 1
        loads[mask] = loads[mask ^ bit] + q[i]

    dp: dict[tuple[int, int], float] = {}
    parent: dict[tuple[int, int], int] = {}
    for i in range(n):
        if q[i] <= capacity:
            dp[(1 << i, i)] = float(dist[0, i + 1])
            parent[(1 << i, i)] = -1

    routes = []
    for mask in range(1, size):
        if loads[mask] > capacity + 1e-9:
            continue
        members = _bits(mask, n)
        if len(members) > 1:
            for last in members:
                previous_mask = mask ^ (1 << last)
                best = float("inf")
                best_prev = -1
                for prev in _bits(previous_mask, n):
                    value = dp.get((previous_mask, prev), float("inf")) + dist[prev + 1, last + 1]
                    if value < best:
                        best, best_prev = float(value), prev
                if best_prev >= 0:
                    dp[(mask, last)] = best
                    parent[(mask, last)] = best_prev

        best_total = float("inf")
        best_last = -1
        for last in members:
            total = dp.get((mask, last), float("inf")) + dist[last + 1, 0]
            if total < best_total:
                best_total, best_last = float(total), last
        if best_last < 0 or best_total > max_distance + 1e-9:
            continue

        order = []
        current_mask, last = mask, best_last
        while last >= 0:
            order.append(last)
            prev = parent[(current_mask, last)]
            current_mask ^= 1 << last
            last = prev
        order.reverse()
        routes.append(
            {
                "mask": mask,
                "customers": members,
                "route": [0] + [i + 1 for i in order] + [0],
                "distance": best_total,
                "cost": float(instance["c_e"] + best_total),
            }
        )
    return routes


def _fixed_station_costs(instance: Dict) -> np.ndarray:
    n = instance["n_customers"]
    return np.array(
        [
            instance["f_l"][l]
            + instance["phi"]
            * (instance["dist"][0, n + 1 + l] + instance["dist"][n + 1 + l, 0])
            for l in range(instance["n_stations"])
        ],
        dtype=float,
    )


def _solve_restricted_lp(instance: Dict, patterns: list[Dict], routes: list[Dict]):
    n, m = instance["n_customers"], instance["n_stations"]
    nv = m + len(patterns) + len(routes) + 1
    c = np.zeros(nv)
    c[:m] = _fixed_station_costs(instance)
    c[m : m + len(patterns)] = [p["cost"] for p in patterns]
    c[m + len(patterns) : -1] = [r["cost"] for r in routes]
    rows = n + m + 1
    aeq = np.zeros((rows, nv))
    beq = np.zeros(rows)
    beq[:n] = 1.0
    for k, p in enumerate(patterns):
        col = m + k
        for i in p["customers"]:
            aeq[i, col] = 1.0
        aeq[n + p["station"], col] = 1.0
    for l in range(m):
        aeq[n + l, l] = -1.0
    route_start = m + len(patterns)
    for k, route in enumerate(routes):
        col = route_start + k
        for i in route["customers"]:
            aeq[i, col] = 1.0
        aeq[-1, col] = 1.0
    aeq[-1, -1] = -1.0
    bounds = [(0.0, 1.0)] * (nv - 1) + [(0.0, float(instance.get("N_e", n)))]
    result = linprog(c, A_eq=aeq, b_eq=beq, bounds=bounds, method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    dual = result.eqlin.marginals
    return result, dual[:n], dual[n : n + m], dual[-1]


def column_generation(
    instance: Dict,
    all_patterns: list[Dict],
    all_routes: list[Dict],
    max_iter: int = 200,
    deadline: float | None = None,
):
    n, m = instance["n_customers"], instance["n_stations"]
    patterns: list[Dict] = []
    # With an explicit fleet-size cap, singleton routes alone can make the
    # initial RMP infeasible. For these small computational experiments we keep
    # the full feasible route pool available at the root and still price station
    # patterns by reduced cost. The integer master below uses the same route pool.
    routes = list(all_routes)
    selected_patterns: set[tuple[int, int]] = set()
    selected_routes = {r["mask"] for r in routes}
    history = []
    final_lp = None

    for iteration in range(max_iter):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        final_lp, mu, tau, eta = _solve_restricted_lp(instance, patterns, routes)
        best_pattern_rc = 0.0
        additions = []
        for l in range(m):
            candidates = [
                (p["cost"] - sum(mu[i] for i in p["customers"]) - tau[l], p)
                for p in all_patterns
                if p["station"] == l and (l, p["mask"]) not in selected_patterns
            ]
            if candidates:
                rc, pattern = min(candidates, key=lambda item: item[0])
                best_pattern_rc += min(0.0, rc)
                if rc < -1e-7:
                    additions.append(pattern)
        route_candidates = [
            (r["cost"] - sum(mu[i] for i in r["customers"]) - eta, r)
            for r in all_routes
            if r["mask"] not in selected_routes
        ]
        best_route_rc = 0.0
        route_addition = None
        if route_candidates:
            best_route_rc, route_addition = min(route_candidates, key=lambda item: item[0])
            best_route_rc = min(0.0, best_route_rc)
        history.append(
            {
                "iteration": iteration,
                "lp_objective": float(final_lp.fun),
                "lower_bound": float(final_lp.fun + best_pattern_rc + best_route_rc),
                "patterns": len(patterns),
                "routes": len(routes),
            }
        )
        if not additions and best_route_rc >= -1e-7:
            break
        for pattern in additions:
            patterns.append(pattern)
            selected_patterns.add((pattern["station"], pattern["mask"]))
        if route_addition is not None and best_route_rc < -1e-7:
            routes.append(route_addition)
            selected_routes.add(route_addition["mask"])
    return patterns, routes, history, final_lp


def _solve_complete_master(
    instance: Dict, patterns: list[Dict], routes: list[Dict], time_limit: float
):
    n, m = instance["n_customers"], instance["n_stations"]
    nv = m + len(patterns) + len(routes)
    c = np.r_[
        _fixed_station_costs(instance),
        np.array([p["cost"] for p in patterns]),
        np.array([r["cost"] for r in routes]),
    ]
    rows = n + m + 1
    matrix = np.zeros((rows, nv), dtype=np.int8)
    lower = np.r_[np.ones(n), np.zeros(m), -np.inf]
    upper = np.r_[np.ones(n), np.zeros(m), float(instance.get("N_e", n))]
    for l in range(m):
        matrix[n + l, l] = -1
    for k, p in enumerate(patterns):
        col = m + k
        matrix[p["customers"], col] = 1
        matrix[n + p["station"], col] = 1
    route_start = m + len(patterns)
    for k, route in enumerate(routes):
        col = route_start + k
        matrix[route["customers"], col] = 1
        matrix[-1, col] = 1
    constraint = LinearConstraint(csc_matrix(matrix), lower, upper)
    return milp(
        c=c,
        integrality=np.ones(nv),
        bounds=Bounds(np.zeros(nv), np.ones(nv)),
        constraints=constraint,
        options={"time_limit": max(1.0, time_limit), "mip_rel_gap": 0.0},
    )


def branch_and_price(instance: Dict, time_limit: float = 300) -> Dict:
    started = time.perf_counter()
    deadline = started + time_limit
    all_patterns = enumerate_patterns(instance)
    all_routes = enumerate_routes(instance)
    generated_patterns, generated_routes, history, lp = column_generation(
        instance, all_patterns, all_routes, deadline=deadline
    )
    remaining = max(1.0, deadline - time.perf_counter())
    mip = _solve_complete_master(instance, all_patterns, all_routes, remaining)
    runtime = time.perf_counter() - started
    solution = {}
    if mip.x is not None:
        m = instance["n_stations"]
        p_start = m
        r_start = m + len(all_patterns)
        chosen_patterns = [p for k, p in enumerate(all_patterns) if mip.x[p_start + k] > 0.5]
        chosen_routes = [r for k, r in enumerate(all_routes) if mip.x[r_start + k] > 0.5]
        solution = {
            "opened_stations": [l for l in range(m) if mip.x[l] > 0.5],
            "station_assignments": {p["station"]: p["customers"] for p in chosen_patterns},
            "routes": [r["route"] for r in chosen_routes],
            "direct_customers": sorted(i for r in chosen_routes for i in r["customers"]),
        }
    return {
        "method": "paper_branch_price",
        "status": "Optimal" if mip.success else (mip.message or "not solved"),
        "objective": float(mip.fun) if mip.fun is not None else None,
        "runtime": runtime,
        "solution": solution,
        "history": history,
        "lp_bound": float(lp.fun) if lp is not None else None,
        "generated_patterns": len(generated_patterns),
        "generated_routes": len(generated_routes),
        "all_patterns": len(all_patterns),
        "all_routes": len(all_routes),
    }


def plot_convergence(result: Dict, output_path: str | Path) -> None:
    history = result.get("history", [])
    if not history:
        return
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    x = [item["iteration"] for item in history]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(x, [item["lp_objective"] for item in history], marker="o", label="Restricted master LP")
    ax.plot(x, [item["lower_bound"] for item in history], marker="s", label="Valid lower bound")
    ax.set(xlabel="Column-generation iteration", ylabel="Objective", title="Paper method convergence")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
