"""
زیرمسئله اول (PSCSP) با PyScipOpt
"""
import numpy as np
from pyscipopt import Model, quicksum
from typing import List, Tuple

def solve_pscsp(instance: dict, station_idx: int, mu: np.ndarray, tau: float) -> Tuple[List[int], float]:
    n = instance['n_customers']
    demands = instance['demands']
    Q_l = instance['Q_l'][station_idx]
    a_l = instance['a_l'][station_idx]
    r_l = instance['r_l'][station_idx]
    station_node = instance['n_customers'] + 1 + station_idx
    dist = instance['dist']

    eligible = [i for i in range(n) if dist[i+1, station_node] <= r_l + 1e-6]
    if not eligible:
        return [], -tau

    model = Model("PSCSP")
    model.hideOutput()
    z = {idx: model.addVar(f"z_{idx}", vtype='B') for idx in range(len(eligible))}
    
    objective = quicksum((mu[eligible[idx]] - a_l * demands[eligible[idx]]) * z[idx]
                         for idx in range(len(eligible)))
    model.setObjective(objective, sense='maximize')
    model.addCons(quicksum(demands[eligible[idx]] * z[idx] for idx in range(len(eligible))) <= Q_l)
    model.optimize()

    if model.getStatus() != 'optimal':
        return [], -tau

    pattern = [eligible[idx] for idx in range(len(eligible)) if model.getVal(z[idx]) > 0.5]
    obj_val = model.getObjVal()
    reduced_cost = - (obj_val + tau)
    return pattern, reduced_cost