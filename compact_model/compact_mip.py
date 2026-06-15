"""Compact formulation (1)-(18) from Wang et al. (2022)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pulp


def exact_preprocessing(instance: Dict) -> Dict:
    """Return feasibility-based reductions that preserve every feasible solution."""
    n = instance["n_customers"]
    m = instance["n_stations"]
    dist = instance["dist"]
    q = instance["demands"]
    max_distance = float(instance["B"] / instance["h"])
    q_vehicle = float(instance.get("Q_e", instance["Q_c"]))

    eligible_assignments = {
        (i, l)
        for i in range(n)
        for l in range(m)
        if q[i] <= instance["Q_l"][l] + 1e-9
        and dist[i + 1, n + 1 + l] <= instance["r_l"][l] + 1e-9
    }
    direct_possible = {
        i
        for i in range(n)
        if q[i] <= q_vehicle + 1e-9
        and dist[0, i + 1] + dist[i + 1, 0] <= max_distance + 1e-9
    }
    feasible_arcs = set()
    for i in range(n + 1):
        for j in range(n + 1):
            if i == j:
                continue
            if i == 0:
                feasible = (j - 1) in direct_possible
            elif j == 0:
                feasible = (i - 1) in direct_possible
            else:
                feasible = (
                    (i - 1) in direct_possible
                    and (j - 1) in direct_possible
                    and q[i - 1] + q[j - 1] <= q_vehicle + 1e-9
                    and dist[0, i] + dist[i, j] + dist[j, 0] <= max_distance + 1e-9
                )
            if feasible:
                feasible_arcs.add((i, j))
    return {
        "eligible_assignments": eligible_assignments,
        "direct_possible": direct_possible,
        "feasible_arcs": feasible_arcs,
        "removed_assignments": n * m - len(eligible_assignments),
        "removed_arcs": n * (n + 1) - len(feasible_arcs),
    }


def build_compact_model(
    instance: Dict,
    preprocess: bool = False,
    relax: bool = False,
) -> tuple[pulp.LpProblem, Dict]:
    n = instance["n_customers"]
    m = instance["n_stations"]
    customers = range(1, n + 1)
    nodes = range(n + 1)
    dist = instance["dist"]
    q = instance["demands"]
    q_vehicle = float(instance.get("Q_e", instance["Q_c"]))

    model = pulp.LpProblem(f"LRP_PS_{instance['name']}", pulp.LpMinimize)
    binary_cat = pulp.LpContinuous if relax else pulp.LpBinary
    v = pulp.LpVariable.dicts("v", range(m), lowBound=0, upBound=1, cat=binary_cat)
    reductions = exact_preprocessing(instance) if preprocess else None
    eligible = (
        reductions["eligible_assignments"]
        if reductions is not None
        else {(i, l) for i in range(n) for l in range(m)}
    )
    direct_possible = reductions["direct_possible"] if reductions is not None else set(range(n))
    z = pulp.LpVariable.dicts("z", sorted(eligible), lowBound=0, upBound=1, cat=binary_cat)
    w = pulp.LpVariable.dicts("w", range(n), lowBound=0, upBound=1, cat=binary_cat)
    arcs = sorted(
        reductions["feasible_arcs"]
        if reductions is not None
        else {(i, j) for i in nodes for j in nodes if i != j}
    )
    x = pulp.LpVariable.dicts("x", arcs, lowBound=0, upBound=1, cat=binary_cat)
    flow = pulp.LpVariable.dicts("flow", arcs, lowBound=0)
    battery = pulp.LpVariable.dicts("battery", nodes, lowBound=0, upBound=instance["B"])

    # Large GVs are not routed to customer demand points in P1. Their only
    # contribution is the effective replenishment cost for an opened station:
    # f_l + phi * (depot -> station -> depot). The station then serves its
    # assigned customers within its coverage radius.
    fixed_station = [
        instance["f_l"][l]
        + instance["phi"] * (dist[0, n + 1 + l] + dist[n + 1 + l, 0])
        for l in range(m)
    ]
    model += (
        pulp.lpSum(fixed_station[l] * v[l] for l in range(m))
        + pulp.lpSum(instance["a_l"][l] * q[i] * z[(i, l)] for i, l in eligible)
        + pulp.lpSum((instance["c_e"] + dist[0, j]) * x[(0, j)] for j in customers if (0, j) in x)
        + pulp.lpSum(dist[i, j] * x[(i, j)] for i, j in arcs if i != 0)
    )

    # (2)-(4): delivery choice, station coverage, and station capacity.
    for i in range(n):
        model += pulp.lpSum(z[(i, l)] for l in range(m) if (i, l) in z) + w[i] == 1, f"serve_{i}"
        if i not in direct_possible:
            model += w[i] == 0, f"direct_impossible_{i}"
        for l in range(m):
            if (i, l) in z:
                station_node = n + 1 + l
                model += dist[i + 1, station_node] * z[(i, l)] <= instance["r_l"][l] * v[l]
                model += z[(i, l)] <= v[l]
    for l in range(m):
        model += pulp.lpSum(q[i] * z[(i, l)] for i in range(n) if (i, l) in z) <= instance["Q_l"][l] * v[l]

    # (5)-(10): route balance, fleet size, load capacity, and package flow.
    model += pulp.lpSum(x[(0, j)] for j in customers if (0, j) in x) == pulp.lpSum(x[(j, 0)] for j in customers if (j, 0) in x)
    model += pulp.lpSum(x[(0, j)] for j in customers if (0, j) in x) <= instance.get("N_e", n)
    for i in customers:
        outgoing = [(i, j) for j in nodes if (i, j) in x]
        incoming = [(j, i) for j in nodes if (j, i) in x]
        model += pulp.lpSum(x[arc] for arc in outgoing) == pulp.lpSum(x[arc] for arc in incoming)
        model += pulp.lpSum(x[arc] for arc in outgoing) <= 1
        model += (
            pulp.lpSum(flow[arc] for arc in incoming)
            - pulp.lpSum(flow[arc] for arc in outgoing)
            == q[i - 1] * w[i - 1]
        )
    for arc in arcs:
        model += flow[arc] <= q_vehicle * x[arc]

    # (11)-(12): remaining battery. battery[0] is the return-state variable.
    for i in customers:
        if (0, i) in x:
            model += battery[i] <= instance["B"] - instance["h"] * dist[0, i] * x[(0, i)]
        for j in nodes:
            if (i, j) in x:
                model += (
                    battery[j]
                    <= battery[i]
                    - instance["h"] * dist[i, j] * x[(i, j)]
                    + instance["B"] * (1 - x[(i, j)])
                )

    variables = {
        "v": v,
        "z": z,
        "w": w,
        "x": x,
        "flow": flow,
        "battery": battery,
        "preprocessing": reductions,
    }
    return model, variables


def _solver(name: str, time_limit: float, msg: bool):
    key = name.lower()
    if key == "gurobi":
        return pulp.GUROBI(msg=msg, timeLimit=time_limit)
    if key == "scip":
        return pulp.SCIP_PY(msg=msg, timeLimit=time_limit)
    if key == "cbc":
        return pulp.PULP_CBC_CMD(msg=msg, timeLimit=time_limit)
    raise ValueError(f"Unknown solver: {name}")


def _extract_solution(instance: Dict, variables: Dict) -> Dict:
    n = instance["n_customers"]
    m = instance["n_stations"]
    station_assignments = {
        l: [i for i in range(n) if (i, l) in variables["z"] and pulp.value(variables["z"][(i, l)]) > 0.5]
        for l in range(m)
        if pulp.value(variables["v"][l]) > 0.5
    }
    selected_arcs = [arc for arc, var in variables["x"].items() if pulp.value(var) > 0.5]
    successors = {i: j for i, j in selected_arcs}
    routes = []
    for first in sorted(j for i, j in selected_arcs if i == 0):
        route = [0, first]
        current = first
        while current != 0 and len(route) <= n + 2:
            current = successors.get(current, 0)
            route.append(current)
        routes.append(route)
    return {
        "opened_stations": sorted(station_assignments),
        "station_assignments": station_assignments,
        "routes": routes,
        "direct_customers": [i for i in range(n) if pulp.value(variables["w"][i]) > 0.5],
    }


def solve_compact(
    instance: Dict,
    time_limit: float = 300,
    solver_name: str = "gurobi",
    msg: bool = False,
    preprocess: bool = False,
    relax: bool = False,
) -> Dict:
    model, variables = build_compact_model(instance, preprocess=preprocess, relax=relax)
    started = time.perf_counter()
    try:
        model.solve(_solver(solver_name, time_limit, msg))
        runtime = time.perf_counter() - started
        status = pulp.LpStatus.get(model.status, str(model.status))
        objective = pulp.value(model.objective) if model.status > 0 else None
        # CBC can report "Optimal" when it stops at the externally supplied
        # time limit with an incumbent. Keep the experiment table honest.
        if solver_name.lower() in {"cbc", "scip"} and runtime >= 0.98 * time_limit:
            status = "TimeLimit/Feasible" if objective is not None else "TimeLimit"
        solution = _extract_solution(instance, variables) if objective is not None else {}
        return {
            "method": f"{'lp_' if relax else ''}{'reduced_' if preprocess else ''}compact_{solver_name.lower()}",
            "status": status,
            "objective": objective,
            "runtime": runtime,
            "solution": solution,
            "n_variables": len(model.variables()),
            "n_constraints": len(model.constraints),
            "preprocessing": variables["preprocessing"],
        }
    except Exception as exc:
        return {
            "method": f"{'lp_' if relax else ''}{'reduced_' if preprocess else ''}compact_{solver_name.lower()}",
            "status": "error",
            "objective": None,
            "runtime": time.perf_counter() - started,
            "solution": {},
            "error": str(exc),
            "n_variables": len(model.variables()),
            "n_constraints": len(model.constraints),
            "preprocessing": variables["preprocessing"],
        }


def solve_reduced_compact(
    instance: Dict,
    time_limit: float = 300,
    solver_name: str = "gurobi",
    msg: bool = False,
) -> Dict:
    return solve_compact(
        instance,
        time_limit=time_limit,
        solver_name=solver_name,
        msg=msg,
        preprocess=True,
    )


def plot_solution(instance: Dict, result: Dict, output_path: str | Path) -> None:
    if not result.get("solution"):
        return
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    points = np.vstack([instance["depot"], instance["customers"]])
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(points[1:, 0], points[1:, 1], c="tab:blue", s=40, label="Customers")
    ax.scatter(*instance["depot"], c="black", marker="*", s=180, label="Depot")
    for route in result["solution"]["routes"]:
        xy = points[route]
        ax.plot(xy[:, 0], xy[:, 1], marker="o", linewidth=1.5)
    colors = plt.cm.Set2(np.linspace(0, 1, max(1, instance["n_stations"])))
    for l, assigned in result["solution"]["station_assignments"].items():
        station = instance["stations"][l]
        ax.scatter(*station, marker="s", s=90, color=colors[l])
        for i in assigned:
            customer = instance["customers"][i]
            ax.plot([customer[0], station[0]], [customer[1], station[1]], linestyle="--", color=colors[l], alpha=0.6)
    ax.set(title=f"{instance['name']} - {result['method']} ({result['objective']:.2f})", xlim=(0, 100), ylim=(0, 100))
    ax.grid(alpha=0.2)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
