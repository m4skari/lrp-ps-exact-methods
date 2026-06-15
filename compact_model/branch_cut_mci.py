"""Branch-and-cut compact solver with minimal cover inequalities."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

import gurobipy as gp
from gurobipy import GRB
import numpy as np

from compact_model.compact_mip import exact_preprocessing
from compact_model.lp_mci import minimal_cover_inequalities, solution_service_metrics


def _fixed_station_cost(instance: Dict, l: int) -> float:
    n = instance["n_customers"]
    station_node = n + 1 + l
    round_trip = instance["dist"][0, station_node] + instance["dist"][station_node, 0]
    return float(instance["f_l"][l] + instance["phi"] * round_trip)


def build_gurobi_compact(instance: Dict, preprocess: bool = True, relax: bool = False):
    n = instance["n_customers"]
    m = instance["n_stations"]
    q = instance["demands"]
    dist = instance["dist"]
    q_vehicle = float(instance.get("Q_e", instance["Q_c"]))
    reductions = exact_preprocessing(instance) if preprocess else None
    eligible = (
        reductions["eligible_assignments"]
        if reductions is not None
        else {(i, l) for i in range(n) for l in range(m)}
    )
    direct_possible = reductions["direct_possible"] if reductions is not None else set(range(n))
    arcs = sorted(
        reductions["feasible_arcs"]
        if reductions is not None
        else {(i, j) for i in range(n + 1) for j in range(n + 1) if i != j}
    )

    model = gp.Model(f"LRPPS_BC_{instance['name']}")
    vtype = GRB.CONTINUOUS if relax else GRB.BINARY
    v = model.addVars(range(m), lb=0.0, ub=1.0, vtype=vtype, name="v")
    z = model.addVars(sorted(eligible), lb=0.0, ub=1.0, vtype=vtype, name="z")
    w = model.addVars(range(n), lb=0.0, ub=1.0, vtype=vtype, name="w")
    x = model.addVars(arcs, lb=0.0, ub=1.0, vtype=vtype, name="x")
    flow = model.addVars(arcs, lb=0.0, vtype=GRB.CONTINUOUS, name="flow")
    battery = model.addVars(range(n + 1), lb=0.0, ub=float(instance["B"]), vtype=GRB.CONTINUOUS, name="battery")

    model.setObjective(
        gp.quicksum(_fixed_station_cost(instance, l) * v[l] for l in range(m))
        + gp.quicksum(instance["a_l"][l] * q[i] * z[i, l] for i, l in eligible)
        + gp.quicksum((instance["c_e"] + dist[0, j]) * x[0, j] for j in range(1, n + 1) if (0, j) in x)
        + gp.quicksum(dist[i, j] * x[i, j] for i, j in arcs if i != 0),
        GRB.MINIMIZE,
    )

    for i in range(n):
        model.addConstr(gp.quicksum(z[i, l] for l in range(m) if (i, l) in z) + w[i] == 1, name=f"serve_{i}")
        if i not in direct_possible:
            model.addConstr(w[i] == 0, name=f"direct_impossible_{i}")
        for l in range(m):
            if (i, l) in z:
                station_node = n + 1 + l
                model.addConstr(dist[i + 1, station_node] * z[i, l] <= instance["r_l"][l] * v[l])
                model.addConstr(z[i, l] <= v[l])

    for l in range(m):
        model.addConstr(
            gp.quicksum(q[i] * z[i, l] for i in range(n) if (i, l) in z) <= instance["Q_l"][l] * v[l],
            name=f"station_capacity_{l}",
        )

    model.addConstr(
        gp.quicksum(x[0, j] for j in range(1, n + 1) if (0, j) in x)
        == gp.quicksum(x[j, 0] for j in range(1, n + 1) if (j, 0) in x),
        name="route_balance_depot",
    )
    model.addConstr(
        gp.quicksum(x[0, j] for j in range(1, n + 1) if (0, j) in x) <= int(instance.get("N_e", n)),
        name="small_gv_limit",
    )

    for i in range(1, n + 1):
        outgoing = [(i, j) for j in range(n + 1) if (i, j) in x]
        incoming = [(j, i) for j in range(n + 1) if (j, i) in x]
        model.addConstr(gp.quicksum(x[arc] for arc in outgoing) == gp.quicksum(x[arc] for arc in incoming))
        model.addConstr(gp.quicksum(x[arc] for arc in outgoing) <= 1)
        model.addConstr(
            gp.quicksum(flow[arc] for arc in incoming) - gp.quicksum(flow[arc] for arc in outgoing)
            == q[i - 1] * w[i - 1],
            name=f"load_flow_{i}",
        )

    for arc in arcs:
        model.addConstr(flow[arc] <= q_vehicle * x[arc])

    for i in range(1, n + 1):
        if (0, i) in x:
            model.addConstr(battery[i] <= instance["B"] - instance["h"] * dist[0, i] * x[0, i])
        for j in range(n + 1):
            if (i, j) in x:
                model.addConstr(
                    battery[j]
                    <= battery[i]
                    - instance["h"] * dist[i, j] * x[i, j]
                    + instance["B"] * (1 - x[i, j])
                )

    variables = {"v": v, "z": z, "w": w, "x": x, "flow": flow, "battery": battery, "preprocessing": reductions}
    return model, variables


def solve_branch_cut_mci(instance: Dict, time_limit: float = 300, msg: bool = False) -> Dict:
    model, variables = build_gurobi_compact(instance, preprocess=True, relax=False)
    covers = minimal_cover_inequalities(instance, set(variables["z"].keys()))
    model.Params.OutputFlag = 1 if msg else 0
    model.Params.TimeLimit = time_limit
    model.Params.PreCrush = 1

    cut_stats = {"added": 0, "seen": set()}

    def callback(cb_model, where):
        if where != GRB.Callback.MIPNODE:
            return
        if cb_model.cbGet(GRB.Callback.MIPNODE_STATUS) != GRB.OPTIMAL:
            return
        v_rel = cb_model.cbGetNodeRel(variables["v"])
        z_rel = cb_model.cbGetNodeRel(variables["z"])
        for idx, (l, subset) in enumerate(covers):
            if idx in cut_stats["seen"]:
                continue
            lhs = sum(z_rel[i, l] for i in subset)
            rhs = (len(subset) - 1) * v_rel[l]
            if lhs > rhs + 1e-6:
                cb_model.cbCut(
                    gp.quicksum(variables["z"][i, l] for i in subset)
                    <= (len(subset) - 1) * variables["v"][l]
                )
                cut_stats["seen"].add(idx)
                cut_stats["added"] += 1

    started = time.perf_counter()
    try:
        model.optimize(callback if covers else None)
        runtime = time.perf_counter() - started
        status = _status_name(model.Status)
        objective = model.ObjVal if model.SolCount else None
        solution = _extract_gurobi_solution(instance, variables) if model.SolCount else {}
        result = {
            "method": "branch_cut_mci",
            "status": status,
            "objective": objective,
            "runtime": runtime,
            "solution": solution,
            "n_variables": model.NumVars,
            "n_constraints": model.NumConstrs,
            "mci_candidates": len(covers),
            "mci_cuts_added": cut_stats["added"],
            "node_count": model.NodeCount,
            "mip_gap": model.MIPGap if model.SolCount and model.Status != GRB.OPTIMAL else 0.0,
            "preprocessing": variables["preprocessing"],
        }
        result.update({f"metric_{k}": v for k, v in solution_service_metrics(instance, result).items()})
        return result
    except Exception as exc:
        return {
            "method": "branch_cut_mci",
            "status": "error",
            "objective": None,
            "runtime": time.perf_counter() - started,
            "solution": {},
            "error": str(exc),
            "n_variables": model.NumVars,
            "n_constraints": model.NumConstrs,
            "mci_candidates": len(covers),
            "mci_cuts_added": cut_stats["added"],
            "node_count": None,
            "mip_gap": None,
            "preprocessing": variables["preprocessing"],
        }


def _status_name(status: int) -> str:
    return {
        GRB.OPTIMAL: "Optimal",
        GRB.TIME_LIMIT: "TimeLimit",
        GRB.INFEASIBLE: "Infeasible",
        GRB.INF_OR_UNBD: "InfOrUnbd",
        GRB.UNBOUNDED: "Unbounded",
    }.get(status, str(status))


def _extract_gurobi_solution(instance: Dict, variables: Dict) -> Dict:
    n = instance["n_customers"]
    m = instance["n_stations"]
    station_assignments = {
        l: [i for i in range(n) if (i, l) in variables["z"] and variables["z"][i, l].X > 0.5]
        for l in range(m)
        if variables["v"][l].X > 0.5
    }
    selected_arcs = [arc for arc, var in variables["x"].items() if var.X > 0.5]
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
        "direct_customers": [i for i in range(n) if variables["w"][i].X > 0.5],
    }
