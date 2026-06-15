"""Reproducible benchmark generation for the LRP-PS experiments."""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Dict, Iterable, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_CONFIGS: Tuple[Tuple[str, int, int, str, str, int], ...] = (
    ("random_center_n06_p2", 6, 2, "center", "random", 101),
    ("random_center_n08_p2", 8, 2, "center", "random", 102),
    ("random_corner_n10_p3", 10, 3, "corner", "random", 103),
    ("cluster_corner_n12_p3", 12, 3, "corner", "clustered", 104),
    ("random_center_n14_p4", 14, 4, "center", "random", 105),
)


def distance_matrix(points: np.ndarray) -> np.ndarray:
    diff = points[:, None, :] - points[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


def _customer_coordinates(
    rng: np.random.Generator, n_customers: int, distribution: str
) -> np.ndarray:
    if distribution == "random":
        return rng.uniform(5.0, 95.0, size=(n_customers, 2))
    if distribution != "clustered":
        raise ValueError(f"Unknown distribution: {distribution}")
    centers = np.array([[27.0, 72.0], [73.0, 28.0]])
    allocation = rng.integers(0, len(centers), size=n_customers)
    points = centers[allocation] + rng.normal(0.0, 7.0, size=(n_customers, 2))
    return np.clip(points, 2.0, 98.0)


def generate_instance(
    name: str,
    n_customers: int,
    n_stations: int,
    depot_type: str = "center",
    distribution: str = "random",
    seed: int = 42,
) -> Dict:
    """Generate one feasible Euclidean instance using the paper's scaling rules."""
    rng = np.random.default_rng(seed)
    depot = np.array([50.0, 50.0]) if depot_type == "center" else np.array([5.0, 5.0])
    customers = _customer_coordinates(rng, n_customers, distribution)

    # Candidate stations are near demand centers, with a small random displacement.
    station_seeds = customers[rng.choice(n_customers, size=n_stations, replace=False)]
    stations = np.clip(station_seeds + rng.normal(0.0, 5.0, station_seeds.shape), 2.0, 98.0)
    demands = rng.integers(4, 13, size=n_customers, endpoint=False).astype(int)

    points = np.vstack([depot, customers, stations])
    dist = distance_matrix(points)
    d_max = float(np.max(dist))

    # Section 5.1 uses B >= ceil(2*d_max) and f_l = ceil(0.5*B).
    # The paper's sensitivity section changes r_l; here we deliberately use a
    # tighter neighborhood so a station can only serve genuinely nearby demand.
    battery = int(np.ceil(2.15 * d_max))
    station_capacity = max(20, int(np.ceil(0.42 * demands.sum() / n_stations)))
    vehicle_capacity = max(int(demands.max()), int(np.ceil(0.28 * demands.sum())))
    coverage_radius = float(np.clip(0.14 * battery, 12.0, 22.0))
    max_small_gvs = int(max(1, min(n_customers, np.ceil(demands.sum() / vehicle_capacity) + 1)))

    return {
        "name": name,
        "depot": depot,
        "customers": customers,
        "stations": stations,
        "demands": demands,
        "dist": dist,
        "n_customers": n_customers,
        "n_stations": n_stations,
        "f_l": np.full(n_stations, int(np.ceil(0.5 * battery)), dtype=float),
        "a_l": np.full(n_stations, 0.01, dtype=float),
        "Q_l": np.full(n_stations, station_capacity, dtype=float),
        "r_l": np.full(n_stations, coverage_radius, dtype=float),
        "Q_c": float(vehicle_capacity),
        "Q_e": float(vehicle_capacity),
        "B": float(battery),
        "N_e": max_small_gvs,
        "c_e": 0.0,
        "phi": 0.1,
        "h": 1.0,
        "depot_type": depot_type,
        "distribution": distribution,
        "seed": seed,
    }


def plot_instance(instance: Dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    depot = instance["depot"]
    customers = instance["customers"]
    stations = instance["stations"]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(customers[:, 0], customers[:, 1], c="tab:blue", s=42, label="Customers")
    ax.scatter(stations[:, 0], stations[:, 1], c="tab:orange", marker="s", s=85, label="Stations")
    ax.scatter([depot[0]], [depot[1]], c="black", marker="*", s=180, label="Depot")
    for i, (x, y) in enumerate(customers, start=1):
        ax.annotate(f"{i}({instance['demands'][i-1]})", (x, y), xytext=(3, 3), textcoords="offset points", fontsize=7)
    for l, (x, y) in enumerate(stations):
        radius = instance["r_l"][l]
        ax.add_patch(plt.Circle((x, y), radius, color="tab:orange", alpha=0.06))
        ax.annotate(f"P{l+1}", (x, y), xytext=(4, -11), textcoords="offset points", fontsize=8)
    ax.set(xlim=(0, 100), ylim=(0, 100), xlabel="x", ylabel="y", title=instance["name"])
    ax.grid(alpha=0.2)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def generate_benchmarks(
    output_dir: str = "data/generated_instances",
    plot_dir: str = "results/01_data",
    configs: Iterable[Tuple[str, int, int, str, str, int]] = DEFAULT_CONFIGS,
) -> list[Path]:
    output = Path(output_dir)
    plots = Path(plot_dir)
    output.mkdir(parents=True, exist_ok=True)
    plots.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    summary = []
    for config in configs:
        instance = generate_instance(*config)
        path = output / f"{instance['name']}.pkl"
        with path.open("wb") as stream:
            pickle.dump(instance, stream)
        plot_instance(instance, plots / f"{instance['name']}.png")
        paths.append(path)
        summary.append(
            {
                "name": instance["name"],
                "customers": instance["n_customers"],
                "stations": instance["n_stations"],
                "total_demand": int(instance["demands"].sum()),
                "vehicle_capacity": instance["Q_e"],
                "station_capacity": instance["Q_l"][0],
                "coverage_radius": instance["r_l"][0],
                "battery": instance["B"],
                "max_small_gvs": instance["N_e"],
            }
        )
    (plots / "instances.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return paths


# Backward-compatible name used by the original main.py.
generate_small_benchmarks = generate_benchmarks


if __name__ == "__main__":
    generate_benchmarks()
