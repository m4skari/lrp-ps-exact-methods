"""Experiment runner: paper B&P vs compact Branch-and-Cut with MCI."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from branch_and_price.run_bnp import branch_and_price, plot_convergence as plot_bnp
from compact_model.branch_cut_mci import solve_branch_cut_mci
from compact_model.compact_mip import build_compact_model, plot_solution
from compact_model.lp_mci import solution_service_metrics


def _load_instances(instance_dir: str) -> list[dict]:
    instances = []
    for path in sorted(Path(instance_dir).glob("*.pkl")):
        with path.open("rb") as stream:
            instances.append(pickle.load(stream))
    return instances


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def plot_model_sizes(instances: Iterable[dict], output_path: Path) -> None:
    names, compact_vars, compact_cons, reduced_vars, reduced_cons = [], [], [], [], []
    for instance in instances:
        compact, _ = build_compact_model(instance)
        reduced_lp, _ = build_compact_model(instance, preprocess=True, relax=True)
        names.append(instance["name"])
        compact_vars.append(len(compact.variables()))
        compact_cons.append(len(compact.constraints))
        reduced_vars.append(len(reduced_lp.variables()))
        reduced_cons.append(len(reduced_lp.constraints))
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10, 5))
    width = 0.2
    ax.bar(x - 1.5 * width, compact_vars, width, label="Original variables")
    ax.bar(x - 0.5 * width, reduced_vars, width, label="Preprocessed LP variables")
    ax.bar(x + 0.5 * width, compact_cons, width, label="Original constraints")
    ax.bar(x + 1.5 * width, reduced_cons, width, label="Preprocessed LP constraints")
    ax.set_xticks(x, names, rotation=25, ha="right")
    ax.set(ylabel="Count", title="Model size before MCI cuts")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def _comparison_plots(df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    names = list(df["instance"].drop_duplicates())
    x = np.arange(len(names))
    methods = ["paper_branch_price", "branch_cut_mci"]
    labels = ["Paper B&P", "Branch-and-Cut + MCI"]
    colors = ["tab:blue", "tab:orange"]

    fig, ax = plt.subplots(figsize=(10, 5))
    width = 0.34
    for k, method in enumerate(methods):
        values = df[df.method == method].set_index("instance").reindex(names)["runtime"]
        ax.bar(x + (k - 0.5) * width, values, width, label=labels[k], color=colors[k])
    ax.set_yscale("log")
    ax.set_xticks(x, names, rotation=25, ha="right")
    ax.set(ylabel="Runtime (seconds, log scale)", title="Runtime comparison of exact methods")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "runtime_comparison.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for method, label, color in zip(methods, labels, colors):
        subset = df[df.method == method].set_index("instance").reindex(names)
        ax.plot(names, subset["objective"], marker="o", label=label, color=color)
    ax.set(ylabel="Optimal objective", title="Objective comparison")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "objective_bound_comparison.png", dpi=180)
    plt.close(fig)

    bc = df[df.method == "branch_cut_mci"].set_index("instance").reindex(names)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(names, bc["mci_cuts_added"], color="tab:orange", label="Cuts added")
    ax.plot(names, bc["mci_candidates"], color="tab:blue", marker="o", label="Candidate minimal covers")
    ax.set(ylabel="Count", title="MCI separation in Branch-and-Cut")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "mci_cut_activity.png", dpi=180)
    plt.close(fig)


def _service_plot(service_df: pd.DataFrame, output_dir: Path) -> None:
    paper = service_df[service_df.method == "paper_branch_price"].copy()
    names = paper["instance"].tolist()
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x, paper["facility_demand"], label="Served by facilities", color="tab:orange")
    ax.bar(
        x,
        paper["small_gv_demand"],
        bottom=paper["facility_demand"],
        label="Served by Small GVs",
        color="tab:blue",
    )
    ax.set_xticks(x, names, rotation=25, ha="right")
    ax.set(ylabel="Demand units", title="Demand split in the paper B&P solution")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "demand_split_paper_solution.png", dpi=180)
    plt.close(fig)


def run_all_comparisons(
    instance_dir: str = "data/generated_instances",
    time_limit: float = 60,
) -> pd.DataFrame:
    instances = _load_instances(instance_dir)
    if not instances:
        raise FileNotFoundError(f"No .pkl instances found in {instance_dir}")

    results_root = Path("results")
    plot_model_sizes(instances, results_root / "02_model" / "model_size.png")
    records = []
    service_records = []
    details = {}

    for instance in instances:
        name = instance["name"]
        details[name] = {}

        paper = branch_and_price(instance, time_limit=time_limit)
        details[name][paper["method"]] = paper
        records.append(
            {
                "instance": name,
                "customers": instance["n_customers"],
                "stations": instance["n_stations"],
                "method": paper["method"],
                "status": paper["status"],
                "objective": paper["objective"],
                "runtime": paper["runtime"],
            }
        )
        service_records.append({"instance": name, "method": paper["method"], **solution_service_metrics(instance, paper)})
        plot_bnp(paper, results_root / "04_paper_method" / f"{name}_convergence.png")
        plot_solution(instance, paper, results_root / "04_paper_method" / f"{name}_solution.png")

        branch_cut = solve_branch_cut_mci(instance, time_limit=time_limit)
        details[name][branch_cut["method"]] = branch_cut
        records.append(
            {
                "instance": name,
                "customers": instance["n_customers"],
                "stations": instance["n_stations"],
                "method": branch_cut["method"],
                "status": branch_cut["status"],
                "objective": branch_cut["objective"],
                "runtime": branch_cut["runtime"],
                "mci_candidates": branch_cut["mci_candidates"],
                "mci_cuts_added": branch_cut["mci_cuts_added"],
                "node_count": branch_cut["node_count"],
                "mip_gap": branch_cut["mip_gap"],
            }
        )
        service_records.append({"instance": name, "method": branch_cut["method"], **solution_service_metrics(instance, branch_cut)})
        plot_solution(instance, branch_cut, results_root / "05_branch_cut_mci" / f"{name}_solution.png")

    df = pd.DataFrame(records)
    paper_obj = df[df.method == "paper_branch_price"].set_index("instance")["objective"]
    df["paper_objective"] = df["instance"].map(paper_obj)
    df["relative_gap_to_paper"] = (df["objective"] - df["paper_objective"]) / df["paper_objective"]
    df.loc[df["relative_gap_to_paper"].abs() < 1e-8, "relative_gap_to_paper"] = 0.0

    service_df = pd.DataFrame(service_records)
    output_dir = results_root / "06_comparison"
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "comparison_results.csv", index=False)
    service_df.to_csv(output_dir / "service_split_results.csv", index=False)
    (output_dir / "solution_details.json").write_text(
        json.dumps(details, default=_json_default, indent=2), encoding="utf-8"
    )
    _comparison_plots(df, output_dir)
    _service_plot(service_df, output_dir)
    return df


if __name__ == "__main__":
    print(run_all_comparisons().to_string(index=False))
