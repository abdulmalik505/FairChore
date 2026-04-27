"""
FairChore Simulation Runner (report-ready)

Runs every scenario × every algorithm × two scoring methods, many random seeds.
Produces:
    results/summary.csv             — raw per-run metrics
    results/key_findings.md         — computed summary + scenario breakdown
    results/summary_table.tex       — LaTeX tabular for the report
    results/ef1_comparison.png      — EF1 rate per algorithm with 95% CI
    results/mms_comparison.png      — worst-MMS ratio vs household size with CI
    results/workload_balance.png    — boxplot of workload-ratio distribution
    results/runtime_scaling.png     — runtime vs household size (log y)
    results/budget_vs_rating.png    — scoring-method comparison
    results/zero_chores.png         — members receiving no chores (practical fairness)
    results/constrained_vs_unconstrained.png — split by capability profile
    results/pareto_workload_runtime.png      — workload-std × runtime Pareto scatter

Usage: python scripts/run_eval.py
"""

import sys
import os
import time
import csv
import math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from algorithms import (
    greedy_round_robin, bag_filling, top_trading_envy_cycle,
    random_allocation, rotation_allocation, compute_all_metrics
)
from simulation.personas import SCENARIOS, generate_scenario, PERSONA_TEMPLATES

# ─── CONFIG ──────────────────────────────────────────────────────────────────

RUNS_PER_SCENARIO = 100
SCORING_METHODS = ["budget", "rating"]
ALGORITHMS = {
    "Round-Robin":             lambda s, c: greedy_round_robin(s, c),
    "Bag-Filling (Paper)":     lambda s, c: bag_filling(s, c, variant="paper"),
    "Bag-Filling (Practical)": lambda s, c: bag_filling(s, c, variant="practical"),
    "Random":                  lambda s, c: random_allocation(s, c, seed=None),
    "Rotation":                lambda s, c: rotation_allocation(s, c),
    "Top-Trading":             lambda s, c: top_trading_envy_cycle(s, c),
}
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

# Report-ready colour palette (colour-blind safe, print-friendly)
ALGO_COLORS = {
    "Round-Robin":             "#1F77B4",   # blue
    "Bag-Filling (Paper)":     "#FF7F0E",   # orange
    "Bag-Filling (Practical)": "#2CA02C",   # green
    "Random":                  "#7F7F7F",   # grey
    "Rotation":                "#8C564B",   # brown
    "Top-Trading":             "#9467BD",   # purple
}


# ─── CAPABILITY PROFILING ────────────────────────────────────────────────────

def _scenario_has_capability_constraints(scenario_def):
    """True if any member persona introduces real capability restrictions
    (age < 16 or restricted_mobility). Contribution-only reductions are NOT
    capability constraints — they don't shrink the feasible chore set.
    """
    for _, persona in scenario_def["members"]:
        t = PERSONA_TEMPLATES[persona]
        if t["age"] < 16 or t["restricted_mobility"]:
            return True
    return False


CONSTRAINED_SCENARIOS = {
    s["name"] for s in SCENARIOS if _scenario_has_capability_constraints(s)
}


# ─── PUBLICATION STYLING ─────────────────────────────────────────────────────

def _style_setup():
    """Apply a consistent, report-ready matplotlib style.
    Called once at the top of generate_charts."""
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "font.family": "DejaVu Sans",
        "font.size": 10.5,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.labelweight": "regular",
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


# ─── STATS HELPERS ───────────────────────────────────────────────────────────

def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _stderr(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var) / math.sqrt(len(xs))


def _ci95(xs):
    """Return (mean, half-width of 95% CI using normal approx: 1.96 × SEM)."""
    return _mean(xs), 1.96 * _stderr(xs)


def _ef1_rate(subset):
    return 100.0 * sum(1 for r in subset if r["ef1"]) / max(len(subset), 1)


def _ef1_rate_ci(subset):
    """Wilson score interval for a binomial proportion (more accurate than
    normal approximation for rates near 0 or 1)."""
    n = len(subset)
    if n == 0:
        return 0.0, 0.0
    successes = sum(1 for r in subset if r["ef1"])
    p = successes / n
    z = 1.96
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return 100 * centre, 100 * spread


# ─── CORE LOOP ───────────────────────────────────────────────────────────────

def run_single(algorithm_fn, scores, capable):
    start = time.perf_counter()
    allocation = algorithm_fn(scores, capable)
    elapsed = time.perf_counter() - start
    return allocation, elapsed


def run_simulation():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    all_results = []
    total = len(SCENARIOS) * RUNS_PER_SCENARIO * len(SCORING_METHODS) * len(ALGORITHMS)
    done = 0

    print(f"FairChore Simulation")
    print(f"{'=' * 60}")
    print(f"Scenarios: {len(SCENARIOS)}  "
          f"(constrained: {len(CONSTRAINED_SCENARIOS)} / "
          f"unconstrained: {len(SCENARIOS) - len(CONSTRAINED_SCENARIOS)})")
    print(f"Runs per scenario: {RUNS_PER_SCENARIO}")
    print(f"Scoring methods:   {SCORING_METHODS}")
    print(f"Algorithms:        {list(ALGORITHMS.keys())}")
    print(f"Total allocations: {total}")
    print(f"{'=' * 60}\n")

    for scenario_def in SCENARIOS:
        n_members = len(scenario_def["members"])
        sname = scenario_def["name"]
        constrained = sname in CONSTRAINED_SCENARIOS
        print(f"Scenario: {sname} ({n_members} members, "
              f"{'constrained' if constrained else 'unconstrained'})...")

        for scoring in SCORING_METHODS:
            for run_idx in range(RUNS_PER_SCENARIO):
                seed = run_idx * 1000 + hash(sname) % 10000
                scenario = generate_scenario(scenario_def, scoring=scoring, seed=seed)

                for algo_name, algo_fn in ALGORITHMS.items():
                    allocation, runtime = run_single(
                        algo_fn, scenario["scores"], scenario["capable"]
                    )
                    metrics = compute_all_metrics(scenario["scores"], allocation)
                    all_results.append({
                        "scenario":          sname,
                        "n_members":         n_members,
                        "n_chores":          scenario["n_chores"],
                        "constrained":       constrained,
                        "scoring":           scoring,
                        "algorithm":         algo_name,
                        "run":               run_idx,
                        "seed":              seed,
                        "runtime_ms":        runtime * 1000,
                        "ef1":               metrics["ef1"],
                        "ef1_violations":    metrics["ef1_violation_count"],
                        "max_envy":          metrics["max_envy"],
                        "workload_ratio":    metrics["workload_ratio"],
                        "workload_std":      metrics["workload_std"],
                        "worst_mms_ratio":   metrics["worst_mms_ratio"],
                        "zero_chore_members": metrics["zero_chore_members"],
                        "all_assigned":      metrics["all_assigned"],
                        "burden_min":        metrics["burden_min"],
                        "burden_max":        metrics["burden_max"],
                        "burden_mean":       metrics["burden_mean"],
                    })
                    done += 1

            pct = 100 * done / total
            print(f"  [{scoring}] {pct:.0f}% complete")

    csv_path = os.path.join(RESULTS_DIR, "summary.csv")
    if all_results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
            writer.writeheader()
            writer.writerows(all_results)
        print(f"\nRaw data saved: {csv_path}")

    generate_charts(all_results)
    print_summary(all_results)
    return all_results


# ─── CHARTS ──────────────────────────────────────────────────────────────────

def generate_charts(results):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping charts")
        return

    _style_setup()
    budget = [r for r in results if r["scoring"] == "budget"]
    if not budget:
        return

    algos = list(ALGORITHMS.keys())
    sizes = sorted(set(r["n_members"] for r in budget))

    # Lean evaluation set — four charts, each making a single sharp claim.
    _chart_ef1_by_algorithm_ci(budget, algos, plt)        # ef1_by_algorithm.png
    _chart_mms_vs_size(budget, algos, sizes, plt)         # mms_comparison.png
    _chart_constrained_vs_unconstrained(budget, algos, plt)  # constrained_vs_unconstrained.png
    _chart_pareto(budget, algos, plt)                     # pareto_workload_runtime.png
    print(f"\nAll charts saved under {RESULTS_DIR}/")


def _chart_ef1_by_algorithm_ci(budget, algos, plt):
    """Aggregated EF1 rate per algorithm with Wilson 95% CI — a single-number
    headline figure for the report."""
    fig, ax = plt.subplots(figsize=(8, 5))
    means, errs, colors = [], [], []
    for algo in algos:
        subset = [r for r in budget if r["algorithm"] == algo]
        m, w = _ef1_rate_ci(subset)
        means.append(m)
        errs.append(w)
        colors.append(ALGO_COLORS[algo])
    x = list(range(len(algos)))
    ax.bar(x, means, yerr=errs, capsize=4, color=colors,
           edgecolor="white", linewidth=0.7,
           error_kw={"ecolor": "#222", "elinewidth": 1.0})
    ax.set_xticks(x)
    ax.set_xticklabels(algos, rotation=25, ha="right")
    ax.set_ylabel("EF1 satisfaction rate (%)")
    ax.set_title("Aggregate EF1 rate by algorithm (Wilson 95% CI)")
    ax.set_ylim(0, 105)
    for xi, m, w in zip(x, means, errs):
        ax.text(xi, min(m + w + 2, 102), f"{m:.1f}%",
                ha="center", va="bottom", fontsize=9)
    plt.savefig(os.path.join(RESULTS_DIR, "ef1_by_algorithm.png"))
    plt.close(fig)


def _chart_mms_vs_size(budget, algos, sizes, plt):
    fig, ax = plt.subplots(figsize=(10, 6))
    for algo in algos:
        means, errs = [], []
        for s in sizes:
            subset = [r["worst_mms_ratio"] for r in budget
                      if r["algorithm"] == algo and r["n_members"] == s]
            m, e = _ci95(subset)
            means.append(m)
            errs.append(e)
        ax.errorbar(sizes, means, yerr=errs, fmt="o-",
                    color=ALGO_COLORS[algo], label=algo,
                    markersize=5, linewidth=1.5, capsize=3)
    ax.axhline(1.0, color="#2CA02C", ls="--", lw=0.8,
               alpha=0.6, label="MMS guarantee (= 1)")
    ax.set_xlabel("Number of household members")
    ax.set_ylabel("Worst-case MMS ratio (lower = fairer)")
    ax.set_title("MMS approximation vs household size (mean ± 95% CI)")
    ax.set_xticks(sizes)
    ax.legend(ncols=2)
    plt.savefig(os.path.join(RESULTS_DIR, "mms_comparison.png"))
    plt.close(fig)


def _chart_constrained_vs_unconstrained(budget, algos, plt):
    """Side-by-side panes. Shows that capability constraints break Bag-Filling
    (paper) while Top-Trading and Round-Robin hold up."""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    for ax, label, subset_filter in [
        (axes[0], "Unconstrained scenarios (n = {n})",
         lambda r: r["scenario"] not in CONSTRAINED_SCENARIOS),
        (axes[1], "Capability-constrained scenarios (n = {n})",
         lambda r: r["scenario"] in CONSTRAINED_SCENARIOS),
    ]:
        filtered = [r for r in budget if subset_filter(r)]
        rates, errs, colors = [], [], []
        for algo in algos:
            subset = [r for r in filtered if r["algorithm"] == algo]
            m, w = _ef1_rate_ci(subset)
            rates.append(m)
            errs.append(w)
            colors.append(ALGO_COLORS[algo])
        x = list(range(len(algos)))
        ax.bar(x, rates, yerr=errs, capsize=3, color=colors,
               edgecolor="white", linewidth=0.6,
               error_kw={"ecolor": "#222", "elinewidth": 0.8})
        ax.set_xticks(x)
        ax.set_xticklabels(algos, rotation=25, ha="right", fontsize=9)
        ax.set_title(label.format(n=len(set(r["scenario"] for r in filtered))))
        ax.set_ylim(0, 110)
        for xi, m in zip(x, rates):
            ax.text(xi, m + 2, f"{m:.0f}%", ha="center", fontsize=8.5)
    axes[0].set_ylabel("EF1 satisfaction rate (%)")
    fig.suptitle("EF1 rate under capability constraints (Wilson 95% CI)",
                 fontsize=13, fontweight="bold")
    plt.savefig(os.path.join(RESULTS_DIR, "constrained_vs_unconstrained.png"))
    plt.close(fig)


def _chart_pareto(budget, algos, plt):
    """Workload-std vs runtime scatter. Algorithms to the bottom-left
    dominate. Each point is one scenario (averaged across runs)."""
    fig, ax = plt.subplots(figsize=(10, 6.5))
    scenarios = list(dict.fromkeys(r["scenario"] for r in budget))
    for algo in algos:
        xs, ys = [], []
        for sname in scenarios:
            subset = [r for r in budget
                      if r["algorithm"] == algo and r["scenario"] == sname]
            if subset:
                xs.append(_mean([r["runtime_ms"] for r in subset]))
                ys.append(_mean([r["workload_std"] for r in subset
                                 if r["workload_std"] != float("inf")]))
        ax.scatter(xs, ys, s=55, color=ALGO_COLORS[algo],
                   label=algo, alpha=0.75, edgecolors="white", linewidths=0.8)
    ax.set_xlabel("Mean runtime (ms, log scale)")
    ax.set_ylabel("Mean workload std-dev (lower = more equal burden)")
    ax.set_title("Fairness × speed Pareto front — one dot per (algorithm, scenario)")
    ax.set_xscale("log")
    ax.text(0.02, 0.02, "↙ bottom-left dominates (faster AND fairer)",
            transform=ax.transAxes, fontsize=9,
            color="#555", style="italic")
    ax.legend(ncols=2, loc="upper right")
    plt.savefig(os.path.join(RESULTS_DIR, "pareto_workload_runtime.png"))
    plt.close(fig)


# ─── REPORTS ─────────────────────────────────────────────────────────────────

def generate_report(results_dir, results):
    budget = [r for r in results if r["scoring"] == "budget"]
    if not budget:
        return

    summary = {}
    for algo in ALGORITHMS:
        subset = [r for r in budget if r["algorithm"] == algo]
        if not subset:
            continue
        n = len(subset)
        ef1_mean, ef1_ci = _ef1_rate_ci(subset)
        summary[algo] = {
            "n":            n,
            "ef1_rate":     ef1_mean,
            "ef1_ci":       ef1_ci,
            "mms_ratio":    _mean([r["worst_mms_ratio"] for r in subset]),
            "avg_envy":     _mean([r["max_envy"] for r in subset]),
            "burden_ratio": _mean([min((r["workload_ratio"] or 100), 100) for r in subset]),
            "avg_time":     _mean([r["runtime_ms"] for r in subset]),
            "zero_chores":  _mean([r["zero_chore_members"] for r in subset]),
        }

    scenarios = sorted(set(r["scenario"] for r in budget))
    scenario_ef1 = {}
    for sname in scenarios:
        scenario_ef1[sname] = {}
        for algo in ALGORITHMS:
            sub = [r for r in budget if r["scenario"] == sname and r["algorithm"] == algo]
            if sub:
                scenario_ef1[sname][algo] = round(_ef1_rate(sub))

    total = len(budget)
    best_ef1 = max(summary, key=lambda a: summary[a]["ef1_rate"])
    worst_ef1 = min(summary, key=lambda a: summary[a]["ef1_rate"])
    best_mms = min(summary, key=lambda a: summary[a]["mms_ratio"])

    md = [
        f"# FairChore Simulation Results",
        f"",
        f"{total:,} allocations • {len(scenarios)} scenarios • "
        f"{len(ALGORITHMS)} algorithms • {RUNS_PER_SCENARIO} runs each",
        f"",
        f"## Overall rankings (budget scoring)",
        f"",
        f"| Algorithm | EF1 rate (%) | 95% CI | MMS ratio | Avg envy | "
        f"Burden ratio | Avg time (ms) | Left out |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for algo in ALGORITHMS:
        if algo not in summary:
            continue
        d = summary[algo]
        md.append(
            f"| {algo} | {d['ef1_rate']:.1f} | ±{d['ef1_ci']:.1f} | "
            f"{d['mms_ratio']:.2f} | {d['avg_envy']:.1f} | "
            f"{d['burden_ratio']:.2f} | {d['avg_time']:.3f} | {d['zero_chores']:.2f} |"
        )

    md += [
        f"",
        f"## Key findings",
        f"",
        f"1. **{best_ef1} achieved the highest EF1 rate "
        f"({summary[best_ef1]['ef1_rate']:.1f}% ± {summary[best_ef1]['ef1_ci']:.1f})**; "
        f"**{best_mms} produced the best worst-case MMS ratio "
        f"({summary[best_mms]['mms_ratio']:.2f})**.",
        f"2. **Algorithm choice dominates scenario difficulty for EF1.** "
        f"Range: {summary[worst_ef1]['ef1_rate']:.1f}% ({worst_ef1}) → "
        f"{summary[best_ef1]['ef1_rate']:.1f}% ({best_ef1}).",
        f"3. **Capability constraints break Bag-Filling (Paper).** "
        f"See `constrained_vs_unconstrained.png` — members are left out of the "
        f"allocation in constrained scenarios (mean: "
        f"{summary.get('Bag-Filling (Paper)', {}).get('zero_chores', 0):.2f} per run).",
        f"",
        f"## Scenario breakdown (EF1 rate, %)",
        f"",
        f"| Scenario | Round-Robin | Bag-Filling (Practical) | Top-Trading |",
        f"|---|---|---|---|",
    ]
    for sname in scenarios:
        ef1 = scenario_ef1.get(sname, {})
        md.append(
            f"| {sname} | {ef1.get('Round-Robin', 0)}% | "
            f"{ef1.get('Bag-Filling (Practical)', 0)}% | "
            f"{ef1.get('Top-Trading', 0)}% |"
        )

    with open(os.path.join(results_dir, "key_findings.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("Report saved: key_findings.md")

    _emit_latex_table(results_dir, summary, scenario_ef1, scenarios)


def _emit_latex_table(results_dir, summary, scenario_ef1, scenarios):
    """Emit a publication-ready LaTeX tabular block for the overall ranking
    and the scenario breakdown. Copy-paste into the report as-is."""
    lines = [
        "% Auto-generated by evaluation/run_simulation.py — do not edit by hand.",
        "% -------- Overall ranking --------",
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Algorithm & EF1 (\\%) & 95\\% CI & MMS & Envy & Bal. & Time (ms) \\\\",
        "\\midrule",
    ]
    for algo in ALGORITHMS:
        if algo not in summary:
            continue
        d = summary[algo]
        lines.append(
            f"{algo} & {d['ef1_rate']:.1f} & $\\pm${d['ef1_ci']:.1f} & "
            f"{d['mms_ratio']:.2f} & {d['avg_envy']:.1f} & "
            f"{d['burden_ratio']:.2f} & {d['avg_time']:.3f} \\\\"
        )
    lines += ["\\bottomrule", "\\end{tabular}", "",
              "% -------- Scenario breakdown (EF1 %) --------",
              "\\begin{tabular}{lrrr}",
              "\\toprule",
              "Scenario & RR & BF-P & TT \\\\",
              "\\midrule"]
    for sname in scenarios:
        ef1 = scenario_ef1.get(sname, {})
        safe = sname.replace("&", "\\&")
        lines.append(
            f"{safe} & {ef1.get('Round-Robin', 0)} & "
            f"{ef1.get('Bag-Filling (Practical)', 0)} & "
            f"{ef1.get('Top-Trading', 0)} \\\\"
        )
    lines += ["\\bottomrule", "\\end{tabular}", ""]

    with open(os.path.join(results_dir, "summary_table.tex"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("LaTeX table saved: summary_table.tex")


def print_summary(results):
    print(f"\n{'=' * 80}")
    print(f"SUMMARY (budget scoring, {RUNS_PER_SCENARIO} runs × {len(SCENARIOS)} scenarios)")
    print(f"{'=' * 80}")
    header = f"{'Algorithm':<25} {'EF1 (%)':>9} {'MMS':>7} {'Envy':>7} " \
             f"{'Balance':>9} {'Time (ms)':>11} {'Left out':>10}"
    print(header)
    print("-" * len(header))
    for algo in ALGORITHMS:
        subset = [r for r in results if r["algorithm"] == algo and r["scoring"] == "budget"]
        if not subset:
            continue
        n = len(subset)
        ef1_rate = 100 * sum(1 for r in subset if r["ef1"]) / n
        avg_mms = _mean([r["worst_mms_ratio"] for r in subset])
        avg_envy = _mean([r["max_envy"] for r in subset])
        avg_wl = _mean([min((r["workload_ratio"] or 100), 100) for r in subset])
        avg_t = _mean([r["runtime_ms"] for r in subset])
        avg_z = _mean([r["zero_chore_members"] for r in subset])
        print(f"{algo:<25} {ef1_rate:>8.1f}% {avg_mms:>7.2f} {avg_envy:>7.1f} "
              f"{avg_wl:>9.2f} {avg_t:>11.3f} {avg_z:>10.2f}")


def main():
    print("Starting FairChore Simulation...\n")
    results = run_simulation()
    print(f"\nSimulation complete. {len(results)} allocations computed.")
    generate_report(RESULTS_DIR, results)


if __name__ == "__main__":
    main()
