# LRP-PS: Paper Method vs Branch-and-Cut with MCI

This project implements the LRP-PS model from Wang et al. (2022). Large green
vehicles replenish opened pick-up stations only; customer demand is satisfied
either by pick-up stations or by small green vehicles.

## Current experiment

Only two exact methods are reported:

- `paper_branch_price`: the paper-style path/pattern reformulation with station
  pattern generation and exact route columns for the small benchmark instances.
- `branch_cut_mci`: compact MIP solved as Branch-and-Cut with minimal cover
  inequalities (MCI) separated at fractional branch-and-bound nodes.

The benchmark generator uses tighter station coverage radii and sets an explicit
upper bound `N_e` on the number of small green vehicles.

## MCI

For a station l, if a minimal cover C violates the station capacity, the cut

```text
sum_{i in C} z_il <= (|C| - 1) v_l
```

is valid for all integer feasible solutions and can remove fractional LP/MIP-node
solutions.

## Run

```powershell
python -m pip install -r requirements.txt
python main.py --time-limit 60
```

Outputs:

- `results/06_comparison/comparison_results.csv`: objective, runtime, MCI
  candidates/cuts, nodes, and gap.
- `results/06_comparison/mci_bound_analysis.csv`: root LP vs LP+MCI bound effect.
- `results/06_comparison/service_split_results.csv`: demand served by stations
  vs small GVs, fleet usage, and large-GV travel saving.
- `results/06_comparison/runtime_comparison.png`: runtime comparison.
- `results/06_comparison/mci_cut_activity.png`: MCI candidate and cut counts.

