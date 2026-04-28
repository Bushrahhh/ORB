"""
Post-simulation analysis: read results.csv and render a 2×2 matplotlib dashboard.
"""
from __future__ import annotations

import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import NUM_SATELLITES

THEME_BG = "#08001a"
THEME_GRID = "#2a1a4a"
COLOR_PURPLE = "#7F77DD"
COLOR_PINK = "#D4537E"


def _apply_dark_axes(ax):
    ax.set_facecolor(THEME_BG)
    ax.tick_params(colors=COLOR_PURPLE)
    ax.spines["bottom"].set_color(THEME_GRID)
    ax.spines["top"].set_color(THEME_GRID)
    ax.spines["left"].set_color(THEME_GRID)
    ax.spines["right"].set_color(THEME_GRID)
    ax.grid(True, color=THEME_GRID, linestyle="-", linewidth=0.6, alpha=0.9)
    ax.set_xlabel("Simulation time (s)", color=COLOR_PURPLE, fontsize=9)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_color(COLOR_PURPLE)


def generate_plots(csv_path: str, out_png: str) -> None:
    if not os.path.isfile(csv_path):
        _empty_figure(out_png, f"Missing: {csv_path}")
        return

    df = pd.read_csv(csv_path)
    if df.empty or "sim_time" not in df.columns:
        _empty_figure(out_png, "No rows in results.csv — run the simulation first.")
        return

    t = df["sim_time"].values

    isl_cols = [f"isl_u{i}" for i in range(NUM_SATELLITES)]
    for c in isl_cols:
        if c not in df.columns:
            df[c] = 0.0

    fig, axes = plt.subplots(2, 2, figsize=(12, 10), facecolor=THEME_BG)
    fig.patch.set_facecolor(THEME_BG)
    fig.suptitle(
        "OrbitNet — simulation analysis",
        color=COLOR_PINK,
        fontsize=14,
        fontweight="bold",
    )

    # 1) Near misses & maneuvers (cumulative)
    ax1 = axes[0, 0]
    if "near_misses" in df.columns:
        ax1.plot(t, df["near_misses"], color=COLOR_PINK, linewidth=1.8, label="Near misses (cum.)")
    if "maneuvers" in df.columns:
        ax1.plot(t, df["maneuvers"], color=COLOR_PURPLE, linewidth=1.8, label="Maneuvers (cum.)")
    ax1.set_ylabel("Count", color=COLOR_PURPLE, fontsize=9)
    ax1.legend(facecolor=THEME_BG, edgecolor=THEME_GRID, labelcolor=COLOR_PURPLE, fontsize=8)
    _apply_dark_axes(ax1)
    ax1.set_title("Collision workload", color=COLOR_PINK, fontsize=10)

    # 2) Avg network latency
    ax2 = axes[0, 1]
    if "avg_latency_ms" in df.columns:
        ax2.plot(t, df["avg_latency_ms"], color=COLOR_PURPLE, linewidth=1.6)
    ax2.set_ylabel("Avg latency (ms)", color=COLOR_PURPLE, fontsize=9)
    _apply_dark_axes(ax2)
    ax2.set_title("Network latency", color=COLOR_PINK, fontsize=10)

    # 3) ISL utilization heatmap (satellite × time)
    ax3 = axes[1, 0]
    mat = df[isl_cols].values.T
    n = len(t)
    t0, t1 = (float(t[0]), float(t[-1])) if n else (0.0, 1.0)
    if n <= 1:
        t1 = t0 + 1.0
    im = ax3.imshow(
        mat,
        aspect="auto",
        cmap="magma",
        interpolation="nearest",
        vmin=0.0,
        vmax=max(0.05, float(np.nanmax(mat)) if mat.size else 0.05),
        origin="lower",
        extent=[t0, t1, -0.5, NUM_SATELLITES - 0.5],
    )
    ax3.set_yticks(range(NUM_SATELLITES))
    ax3.set_yticklabels([f"S{i}" for i in range(NUM_SATELLITES)], color=COLOR_PURPLE, fontsize=7)
    ax3.set_xlabel("Simulation time (s)", color=COLOR_PURPLE, fontsize=9)
    ax3.set_facecolor(THEME_BG)
    ax3.set_title("ISL link utilization (mean incident load)", color=COLOR_PINK, fontsize=10)
    cb = fig.colorbar(im, ax=ax3, fraction=0.046, pad=0.04)
    cb.ax.yaxis.set_tick_params(color=COLOR_PURPLE)
    plt.setp(cb.ax.get_yticklabels(), color=COLOR_PURPLE)

    # 4) Packet delivery rate
    ax4 = axes[1, 1]
    if "delivery_rate_pct" in df.columns:
        ax4.plot(t, df["delivery_rate_pct"], color=COLOR_PINK, linewidth=1.6)
    elif "packets_delivered" in df.columns and "packets_sent" in df.columns:
        sent = df["packets_sent"].replace(0, np.nan)
        rate = df["packets_delivered"] / sent * 100.0
        ax4.plot(t, rate.fillna(0.0), color=COLOR_PINK, linewidth=1.6)
    ax4.set_ylabel("Delivery rate (%)", color=COLOR_PURPLE, fontsize=9)
    ax4.set_ylim(0, 105)
    _apply_dark_axes(ax4)
    ax4.set_title("Packet delivery rate", color=COLOR_PINK, fontsize=10)

    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_png, dpi=150, facecolor=THEME_BG, edgecolor="none")
    plt.close(fig)
    print(f"  Analysis figure saved -> {out_png}")


def _empty_figure(out_png: str, message: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 6), facecolor=THEME_BG)
    ax.set_facecolor(THEME_BG)
    ax.text(
        0.5, 0.5, message,
        ha="center", va="center", color=COLOR_PINK, fontsize=12, wrap=True,
    )
    ax.axis("off")
    fig.savefig(out_png, dpi=120, facecolor=THEME_BG)
    plt.close(fig)
    print(f"  Placeholder analysis saved -> {out_png}")


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    csv_p = os.path.join(base, "results.csv")
    png_p = os.path.join(base, "results_analysis.png")
    if len(sys.argv) >= 2:
        csv_p = sys.argv[1]
    if len(sys.argv) >= 3:
        png_p = sys.argv[2]
    generate_plots(csv_p, png_p)
