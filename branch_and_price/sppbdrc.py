"""
SPPBDRC با الگوریتم Label Setting
"""
import numpy as np
from collections import deque
from typing import List, Tuple, Optional, FrozenSet

class Label:
    __slots__ = ('node', 'cost', 'load', 'battery', 'visited', 'pred')
    def __init__(self, node: int, cost: float, load: float, battery: float, 
                 visited: FrozenSet[int], pred):
        self.node = node
        self.cost = cost
        self.load = load
        self.battery = battery
        self.visited = visited
        self.pred = pred

def solve_sppbdrc(instance: dict, mu: np.ndarray, eta: float, 
                  heuristic_arcs: bool = True) -> Tuple[Optional[List[int]], float]:
    n = instance['n_customers']
    dist = instance['dist']
    demands = instance['demands']
    Q_c = instance['Q_c']
    B = instance['B']
    h = instance['h']
    c_e = instance['c_e']
    
    def red_cost(i: int, j: int) -> float:
        if i == 0 and 1 <= j <= n:
            return c_e + dist[0, j] - eta - (mu[j-1] if j>=1 else 0)
        elif 1 <= i <= n:
            return dist[i, j] - (mu[i-1] if j != 0 else 0)
        else:
            return dist[i, j]
    
    all_nodes = list(range(0, n+1))
    if heuristic_arcs:
        m_arcs = max(5, (n+1)//3)
        best_arcs = {}
        for i in all_nodes:
            outgoing = [(j, red_cost(i, j)) for j in all_nodes if j != i]
            outgoing.sort(key=lambda x: x[1])
            best_arcs[i] = [j for j, _ in outgoing[:m_arcs]]
    else:
        best_arcs = {i: [j for j in all_nodes if j != i] for i in all_nodes}
    
    labels = {i: [] for i in all_nodes}
    start_label = Label(node=0, cost=0.0, load=0.0, battery=B, 
                        visited=frozenset([0]), pred=None)
    labels[0].append(start_label)
    queue = deque([start_label])
    best_complete = None
    
    while queue:
        cur = queue.popleft()
        if cur.node == 0 and cur.pred is not None:
            if best_complete is None or cur.cost < best_complete.cost:
                best_complete = cur
            continue
        for j in best_arcs[cur.node]:
            if j == cur.node:
                continue
            if j != 0 and j in cur.visited:
                continue
            new_load = cur.load + (demands[j-1] if j>=1 else 0)
            if new_load > Q_c + 1e-6:
                continue
            new_battery = cur.battery - h * dist[cur.node, j]
            if new_battery < -1e-6:
                continue
            new_cost = cur.cost + red_cost(cur.node, j)
            new_visited = cur.visited.union([j]) if j != 0 else cur.visited
            new_label = Label(node=j, cost=new_cost, load=new_load, 
                              battery=new_battery, visited=new_visited, pred=cur)
            dominated = False
            for existing in labels[j]:
                if (existing.load <= new_label.load + 1e-6 and 
                    existing.battery >= new_label.battery - 1e-6 and 
                    existing.cost <= new_label.cost + 1e-6):
                    dominated = True
                    break
            if dominated:
                continue
            new_labels = []
            for existing in labels[j]:
                if not (new_label.load <= existing.load + 1e-6 and 
                        new_label.battery >= existing.battery - 1e-6 and 
                        new_label.cost <= existing.cost + 1e-6):
                    new_labels.append(existing)
            new_labels.append(new_label)
            labels[j] = new_labels
            queue.append(new_label)
    
    if best_complete is None or best_complete.cost >= -1e-6:
        return None, 0.0
    route = []
    lbl = best_complete
    while lbl:
        route.append(lbl.node)
        lbl = lbl.pred
    route.reverse()
    return route, best_complete.cost