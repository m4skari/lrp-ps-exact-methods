"""
Master Problem با استفاده از PyScipOpt (SCIP) - نسخه نهایی بدون update
"""
import numpy as np
from pyscipopt import Model, quicksum
from typing import List, Dict, Tuple

class MasterProblem:
    def __init__(self, instance: Dict):
        self.instance = instance
        self.n = instance['n_customers']
        self.m = instance['n_stations']
        self.model = None
        self.pattern_columns = []
        self.route_columns = []
        self.dual_mu = None
        self.dual_tau = None
        self.dual_eta = None
        self.v_vars = []
        self.cust_constrs = []
        self.station_constrs = []
        self.veh_constr = None
        self.H_e = None

    def build_initial_rmp(self):
        self.model = Model("RMP")
        self.model.hideOutput()

        # متغیر H_e
        self.H_e = self.model.addVar("H_e", lb=0, ub=self.n, vtype='C')

        # متغیرهای v_l
        self.v_vars = []
        for l in range(self.m):
            f_tilde = self.instance['f_l'][l] + self.instance['phi'] * (
                self.instance['dist'][0, self.n+1+l] + self.instance['dist'][self.n+1+l, 0]
            )
            var = self.model.addVar(f"v_{l}", lb=0, ub=1, vtype='C', obj=f_tilde)
            self.v_vars.append(var)

        # محدودیت مشتریان: در ابتدا یک عبارت 0 می‌سازیم، بعداً با addConsCoeff ضرایب را اضافه می‌کنیم
        self.cust_constrs = []
        for i in range(self.n):
            # ایجاد یک محدودیت با سمت راست 1 و سمت چپ 0 (در ابتدا)
            lhs = quicksum([])  # 0
            constr = self.model.addCons(lhs == 1, name=f"cust_{i}")
            self.cust_constrs.append(constr)

        # محدودیت ایستگاه‌ها: sum_{p in P_l} z_p - v_l = 0
        self.station_constrs = []
        for l in range(self.m):
            lhs = quicksum([]) - self.v_vars[l]
            constr = self.model.addCons(lhs == 0, name=f"station_{l}")
            self.station_constrs.append(constr)

        # محدودیت تعداد وسایل: sum_r x_r - H_e = 0
        self.veh_constr = self.model.addCons(quicksum([]) - self.H_e == 0, name="num_vehicles")

        # الگوهای خالی برای هر ایستگاه (هزینه صفر)
        for l in range(self.m):
            var = self.model.addVar(f"pattern_empty_{l}", lb=0, ub=1, vtype='C', obj=0.0)
            # اضافه کردن به محدودیت station
            self.model.addConsCoeff(self.station_constrs[l], var, 1.0)
            self.pattern_columns.append((l, var, []))

    def add_pattern_column(self, station_idx: int, customers: List[int], _rc: float):
        cost = sum(self.instance['a_l'][station_idx] * self.instance['demands'][i] for i in customers)
        var = self.model.addVar(f"pattern_{station_idx}_{len(self.pattern_columns)}",
                                lb=0, ub=1, vtype='C', obj=cost)
        for i in customers:
            self.model.addConsCoeff(self.cust_constrs[i], var, 1.0)
        self.model.addConsCoeff(self.station_constrs[station_idx], var, 1.0)
        self.pattern_columns.append((station_idx, var, customers))

    def add_route_column(self, route: List[int], _rc: float):
        dist = self.instance['dist']
        c_e = self.instance['c_e']
        cost = 0.0
        for idx in range(len(route)-1):
            i, j = route[idx], route[idx+1]
            if i == 0:
                cost += c_e + dist[i, j]
            else:
                cost += dist[i, j]
        var = self.model.addVar(f"route_{len(self.route_columns)}",
                                lb=0, ub=1, vtype='C', obj=cost)
        customers_in_route = [node-1 for node in route if node != 0]
        for i in customers_in_route:
            self.model.addConsCoeff(self.cust_constrs[i], var, 1.0)
        self.model.addConsCoeff(self.veh_constr, var, 1.0)
        self.route_columns.append((var, route))

    def solve_rmp(self) -> Tuple[float, np.ndarray, np.ndarray, float]:
        self.model.optimize()
        status = self.model.getStatus()
        if status != 'optimal':
            raise RuntimeError(f"RMP not optimal, status {status}")

        obj_val = self.model.getObjVal()

        # استخراج مقادیر دوگان
        mu = np.array([self.model.getDualsolLinear(self.cust_constrs[i]) for i in range(self.n)])
        tau = np.array([self.model.getDualsolLinear(self.station_constrs[l]) for l in range(self.m)])
        eta = self.model.getDualsolLinear(self.veh_constr)

        self.dual_mu = mu
        self.dual_tau = tau
        self.dual_eta = eta
        return obj_val, mu, tau, eta

    def get_var_values(self):
        v_vals = {l: self.model.getVal(self.v_vars[l]) for l in range(self.m)}
        pattern_vals = [(l, self.model.getVal(var), cust_list) for (l, var, cust_list) in self.pattern_columns]
        route_vals = [(self.model.getVal(var), route) for (var, route) in self.route_columns]
        H_e_val = self.model.getVal(self.H_e) if self.H_e is not None else 0.0
        return v_vals, pattern_vals, route_vals, H_e_val