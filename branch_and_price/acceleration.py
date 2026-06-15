"""
روش‌های شتاب‌دهی: valid lower bound, MIP heuristic, tight upper bound
"""
import gurobipy as gp
from gurobipy import GRB
import numpy as np
from typing import Dict, Tuple, Optional
from .master_problem import MasterProblem

def compute_valid_lower_bound(mp: MasterProblem, best_pattern_rc: float, best_route_rc: float) -> float:
    """کران پایین معتبر (فرمول 4.6.1)"""
    return mp.model.ObjVal + best_pattern_rc + best_route_rc

def mip_heuristic(mp: MasterProblem, time_limit: int = 30) -> Tuple[float, Optional[Dict]]:
    """
    حل MIP روی RMP (متغیرها را صحیح می‌کند) برای یافتن کران بالا
    Returns:
        obj_val, solution dict
    """
    # کپی از مدل
    model_copy = mp.model.copy()
    # تغییر نوع متغیرها به باینری برای متغیرهای pattern و route و v_l
    for var in model_copy.getVars():
        if var.VarName.startswith('pattern_') or var.VarName.startswith('route_') or var.VarName.startswith('v_'):
            var.setAttr('VType', GRB.BINARY)
    # متغیر H_e را صحیح کنیم
    for var in model_copy.getVars():
        if var.VarName == 'H_e':
            var.setAttr('VType', GRB.INTEGER)
    model_copy.Params.TimeLimit = time_limit
    model_copy.Params.OutputFlag = 0
    model_copy.optimize()
    if model_copy.Status == GRB.OPTIMAL or model_copy.Status == GRB.TIME_LIMIT:
        return model_copy.ObjVal, None
    return float('inf'), None

def tight_upper_bound(mp: MasterProblem, instance: Dict) -> float:
    """
    Tight Upper Bound با حل مسئله تخصیص ایستگاه‌ها (PSAP) برای مشتریان باقیمانده
    (وقتی قوانین 1-4 برقرار باشند)
    """
    # استخراج باز بودن ایستگاه‌ها و مشتریان پوشش داده شده توسط وسایل کوچک
    v_vals, pattern_vals, route_vals, H_e_val = mp.get_var_values()
    opened_stations = [l for l, val in v_vals.items() if val > 0.5]
    # مشتریانی که توسط وسایل کوچک سرویس می‌شوند
    cust_covered_by_route = set()
    for val, route in route_vals:
        if val > 0.5:
            for node in route:
                if node != 0:
                    cust_covered_by_route.add(node-1)
    remaining_cust = [i for i in range(instance['n_customers']) if i not in cust_covered_by_route]
    if not remaining_cust:
        # همه مشتریان پوشش داده شده‌اند
        gv_cost = sum(route_vals[i][1] for i in range(len(route_vals)) if route_vals[i][0] > 0.5)
        return mp.model.ObjVal  # یا محاسبه مجدد
    
    # حل PSAP (فرمول 69-74)
    # ساده‌سازی: از Gurobi استفاده می‌کنیم
    m = len(opened_stations)
    n_rem = len(remaining_cust)
    if m == 0 or n_rem == 0:
        return mp.model.ObjVal
    
    model = gp.Model("PSAP")
    model.Params.OutputFlag = 0
    # متغیرها: v_l برای ایستگاه‌های باز شده (در اینجا ثابت هستند؟ بهتر است دوباره تصمیم بگیریم)
    # ولی طبق مقاله، فرض می‌کنیم ایستگاه‌های باز شده همان‌ها هستند.
    # برای سادگی، فقط تخصیص به ایستگاه‌های باز شده را انجام می‌دهیم.
    # متغیر z_il برای مشتریان باقیمانده
    z = model.addVars(n_rem, m, vtype=GRB.BINARY, name="z")
    # هزینه هدف = sum a_l q_i z_il + هزینه ثابت ایستگاه‌ها (در صورت بسته شدن مجدد)
    obj = gp.LinExpr()
    for idx, i in enumerate(remaining_cust):
        for j, l in enumerate(opened_stations):
            obj += instance['a_l'][l] * instance['demands'][i] * z[idx, j]
    # هزینه ثابت ایستگاه‌های باز (قبلاً در mp حساب شده، برای کران بالا فقط اضافه می‌کنیم)
    fixed_cost = sum(instance['f_l'][l] + instance['phi']*(instance['dist'][0, instance['n_customers']+1+l] + 
                     instance['dist'][instance['n_customers']+1+l, 0]) for l in opened_stations)
    model.setObjective(obj + fixed_cost, GRB.MINIMIZE)
    # هر مشتری به یک ایستگاه
    for idx in range(n_rem):
        model.addConstr(gp.quicksum(z[idx, j] for j in range(m)) == 1)
    # ظرفیت ایستگاه‌ها
    for j, l in enumerate(opened_stations):
        model.addConstr(gp.quicksum(instance['demands'][remaining_cust[idx]] * z[idx, j] for idx in range(n_rem)) <= instance['Q_l'][l])
    # محدوده شعاع (از قبل اعمال می‌شود)
    for idx, i in enumerate(remaining_cust):
        for j, l in enumerate(opened_stations):
            dist_il = instance['dist'][i+1, instance['n_customers']+1+l]
            if dist_il > instance['r_l'][l] + 1e-6:
                model.addConstr(z[idx, j] == 0)
    
    model.optimize()
    if model.Status == GRB.OPTIMAL:
        return model.ObjVal
    else:
        return float('inf')