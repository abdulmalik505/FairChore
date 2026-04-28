"""
Longitudinal fairness simulation — 26 weeks of allocation.

Measures whether history-aware turn ordering (least-burdened picks first)
produces a fairer cumulative workload than a random ordering baseline, and
produces publication-ready figures for the report:

    results/longitudinal_fairness.png            — cumulative std-dev (aware vs random)
    results/longitudinal_ef1_weekly.png          — EF1 satisfaction per week
    results/longitudinal_gini_weekly.png         — Gini coefficient of cumulative burden
    results/longitudinal_member_trajectory.png   — per-member cumulative burden line
    results/longitudinal_summary.md              — report-ready key findings

Run: python -m evaluation.run_longitudinal
"""

import os
import sys
import math
import random
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from algorithms import greedy_round_robin, compute_all_metrics
from simulation.personas import generate_scenario, SCENARIOS

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ─── CONFIG ──────────────────────────────────────────────────────────────────

N_WEEKS = 26
SEEDS = [0, 1, 2, 3, 4]

TARGET_SCENARIOS = [
    "Equal couple",
    "Student flat (3)",
    "Professional houseshare",
]
TRAJECTORY_SCENARIO = "Student flat with freeloader"   # clearest demo of reciprocity

SCENARIO_MAP = {s["name"]: s for s in SCENARIOS}
RESULTS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "results"))

SCENARIO_COLORS = {
    "Equal couple":            "#1F77B4",
    "Student flat (3)":        "#2CA02C",
    "Professional houseshare": "#D62728",
    "Student flat with freeloader": "#FF7F0E",
}


# ─── PUBLICATION STYLING (shared with run_simulation.py) ─────────────────────

def _style_setup():
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "font.family": "DejaVu Sans",
        "font.size": 10.5,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.edgecolor": "#333333",
        "axes.linewidth": 0.9,
        "axes.grid": True,
        "grid.color": "#CCCCCC",
        "grid.linestyle": "--",
        "grid.linewidth": 0.6,
        "grid.alpha": 0.6,
        "legend.fontsize": 9,
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.edgecolor": "#BBBBBB",
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


# ─── FAIRNESS STATISTICS ─────────────────────────────────────────────────────

def _std(values):
    n = len(values)
    if n == 0:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / n)


def _gini(values):
    """Gini coefficient of a non-negative distribution.  0 = perfect equality,
    1 = one person bears everything.  Stable even when all values are equal."""
    xs = sorted(values)
    n = len(xs)
    s = sum(xs)
    if n == 0 or s == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, start=1):
        cum += i * x
    return (2 * cum) / (n * s) - (n + 1) / n


# ─── CORE SIMULATION ─────────────────────────────────────────────────────────

def simulate_longitudinal(scenario_def, algorithm_fn,
                          n_weeks=N_WEEKS, seed=42, history_aware=True):
    """Runs one scenario for n_weeks, returning a list of per-week dicts."""
    scenario = generate_scenario(scenario_def, scoring="budget", seed=seed)
    scores = scenario["scores"]
    capable = scenario["capable"]
    members = list(scores.keys())

    cum_burden = {m: 0.0 for m in members}
    per_week = []
    rng = random.Random(seed + 1000)

    for week in range(1, n_weeks + 1):
        if history_aware:
            ordered = sorted(members, key=lambda m: cum_burden[m])
        else:
            ordered = members[:]
            rng.shuffle(ordered)
        ordered_scores = {m: scores[m] for m in ordered}
        allocation = algorithm_fn(ordered_scores, capable)
        metrics = compute_all_metrics(scores, allocation)

        for m in members:
            weekly = sum(scores[m].get(c, 0) for c in allocation.get(m, []))
            cum_burden[m] += weekly

        cum_vals = [cum_burden[m] for m in members]
        per_week.append({
            "week": week,
            "ef1":              metrics["ef1"],
            "workload_std":     metrics["workload_std"],
            "cumulative_std":   _std(cum_vals),
            "cumulative_range": max(cum_vals) - min(cum_vals),
            "cumulative_gini":  _gini(cum_vals),
            "max_envy":         metrics["max_envy"],
            "burdens":          dict(cum_burden),
        })
    return per_week


def average_over_seeds(runs):
    """Average per-week dicts across seeds.  Scalar keys only."""
    n_weeks = len(runs[0])
    avg = []
    for i in range(n_weeks):
        row = {"week": i + 1}
        for k in ["cumulative_std", "cumulative_range", "cumulative_gini",
                  "workload_std", "max_envy"]:
            row[k] = sum(r[i][k] for r in runs) / len(runs)
        row["ef1_rate"] = sum(1 for r in runs if r[i]["ef1"]) / len(runs)
        avg.append(row)
    return avg


def mean_member_trajectory(runs, members):
    """For each member, average their cumulative burden across seeds."""
    n_weeks = len(runs[0])
    out = {m: [] for m in members}
    for i in range(n_weeks):
        for m in members:
            out[m].append(sum(r[i]["burdens"][m] for r in runs) / len(runs))
    return out


# ─── CHARTS ──────────────────────────────────────────────────────────────────

def chart_member_trajectory(scenario_name, series_aware, series_random, weeks):
    """Single combined figure for the longitudinal study.

    Left panel:  std-dev of cumulative burden over 26 weeks, every target
                 scenario × aware/random condition. Shows that history-aware
                 ordering keeps the spread tighter than random order does.
    Right panel: per-member cumulative burden lines for one focal scenario
                 (the freeloader case), aware-only. Shows the individual
                 trajectories converging week by week — the visual proof
                 that "the algorithm balances the burden over time".
    """
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(15, 6),
                                     gridspec_kw={"width_ratios": [1.15, 1]})

    # ── Panel A: convergence across all target scenarios ─────────────────
    for sname in TARGET_SCENARIOS:
        color = SCENARIO_COLORS[sname]
        aware = [w["cumulative_std"] for w in series_aware[sname]]
        rand  = [w["cumulative_std"] for w in series_random[sname]]
        ax_a.plot(weeks, aware, color=color, linewidth=2.1,
                  label=f"{sname} — history-aware")
        ax_a.plot(weeks, rand, color=color, linewidth=1.5, linestyle="--",
                  alpha=0.55, label=f"{sname} — random")
    ax_a.set_xlabel("Week")
    ax_a.set_ylabel("Std-dev of cumulative burden  (lower = more equal)")
    ax_a.set_title("(a) History-aware ordering keeps the spread tighter")
    ax_a.set_xticks(range(1, N_WEEKS + 1, 4))
    ax_a.legend(fontsize=7.5, loc="upper left", framealpha=0.95)

    # ── Panel B: per-member trajectory for the focal scenario ────────────
    scenario_def = SCENARIO_MAP[scenario_name]
    aware_runs = [simulate_longitudinal(scenario_def, greedy_round_robin,
                                        seed=s, history_aware=True)
                  for s in SEEDS]
    members = list(aware_runs[0][0]["burdens"].keys())
    aware_traj = mean_member_trajectory(aware_runs, members)
    palette = plt.cm.tab10.colors
    for i, m in enumerate(members):
        ax_b.plot(weeks, aware_traj[m], color=palette[i % len(palette)],
                  linewidth=1.9, label=m)
    ax_b.set_xlabel("Week")
    ax_b.set_ylabel("Cumulative burden per member")
    ax_b.set_title(f"(b) Per-member trajectories converge — {scenario_name}")
    ax_b.set_xticks(range(1, N_WEEKS + 1, 4))
    ax_b.legend(fontsize=8, loc="upper left")

    fig.suptitle(
        "Longitudinal fairness: history-aware vs random ordering, 26 weeks",
        fontsize=13, fontweight="bold", y=1.02,
    )
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, "longitudinal_member_trajectory.png"),
                bbox_inches="tight")
    plt.close(fig)


# ─── REPORT ──────────────────────────────────────────────────────────────────

def write_summary(summary_rows):
    """Emit a markdown summary for the report."""
    lines = [
        "# Longitudinal Fairness Results",
        "",
        f"{N_WEEKS} weeks · {len(SEEDS)} seeds · Round-Robin on 3 scenarios.",
        "Lower cumulative std / Gini = more equal total workload.",
        "",
        "| Scenario | Aware (W26 std) | Random (W26 std) | Aware vs random | "
        "Aware Gini W26 | Random Gini W26 |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['scenario']} | {row['aware_w26']:.2f} | "
            f"{row['rand_w26']:.2f} | **{row['vs_random_pct']:+.1f}%** | "
            f"{row['aware_gini_w26']:.3f} | {row['rand_gini_w26']:.3f} |"
        )
    lines += [
        "",
        "**Interpretation:** A negative `aware vs random` value would mean "
        "history-aware ordering made things worse.  A positive value is how "
        "much flatter the cumulative burden distribution was at week 26 "
        "under history-aware ordering versus random ordering.",
        "",
    ]
    with open(os.path.join(RESULTS_DIR, "longitudinal_summary.md"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    _style_setup()
    os.makedirs(RESULTS_DIR, exist_ok=True)

    series_aware = defaultdict(list)
    series_random = defaultdict(list)

    print(f"Longitudinal simulation — {N_WEEKS} weeks × {len(SEEDS)} seeds")
    print("=" * 60)

    for sname in TARGET_SCENARIOS:
        scenario_def = SCENARIO_MAP[sname]
        aware_runs = [simulate_longitudinal(scenario_def, greedy_round_robin,
                                            seed=s, history_aware=True)
                      for s in SEEDS]
        rand_runs = [simulate_longitudinal(scenario_def, greedy_round_robin,
                                           seed=s, history_aware=False)
                     for s in SEEDS]
        series_aware[sname] = average_over_seeds(aware_runs)
        series_random[sname] = average_over_seeds(rand_runs)
        print(f"  {sname}: done")

    weeks = list(range(1, N_WEEKS + 1))
    chart_member_trajectory(TRAJECTORY_SCENARIO, series_aware, series_random, weeks)

    summary_rows = []
    for sname in TARGET_SCENARIOS:
        aware = series_aware[sname]
        rand = series_random[sname]
        w1_aware = aware[0]["cumulative_std"]
        w26_aware = aware[-1]["cumulative_std"]
        w26_rand = rand[-1]["cumulative_std"]
        vs_random = (
            (w26_rand - w26_aware) / w26_rand * 100 if w26_rand > 0 else 0
        )
        summary_rows.append({
            "scenario":        sname,
            "aware_w1":        w1_aware,
            "aware_w26":       w26_aware,
            "rand_w26":        w26_rand,
            "vs_random_pct":   vs_random,
            "aware_gini_w26":  aware[-1]["cumulative_gini"],
            "rand_gini_w26":   rand[-1]["cumulative_gini"],
        })

    write_summary(summary_rows)

    print("\nWeek-26 summary (std of cumulative burden, lower = fairer):")
    print("-" * 70)
    print(f"{'Scenario':<28}{'Aware':>10}{'Random':>10}{'Improvement':>14}")
    print("-" * 70)
    for row in summary_rows:
        print(f"{row['scenario']:<28}{row['aware_w26']:>10.2f}"
              f"{row['rand_w26']:>10.2f}{row['vs_random_pct']:>13.1f}%")
    print("-" * 70)
    print(f"\nAll longitudinal charts saved under {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
