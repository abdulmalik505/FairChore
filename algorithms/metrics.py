"""
FairChore Metrics — Independent Fairness Verification

Takes ANY allocation and checks fairness properties.
Does NOT trust the algorithm — verifies the output independently.

Metrics computed:
    1. EF1 (Envy-Free up to One Item) — yes/no + list of violations
    2. MMS approximation ratio — how close is worst-off member to their guarantee
    3. Max envy — biggest envy between any pair
    4. Workload balance — ratio of max burden to min burden
"""

from itertools import permutations


def check_ef1(scores, allocation):
    """
    Check if allocation satisfies EF1 for chores.

    EF1 for chores: for every pair (i, j), either:
      - i does NOT envy j (i's burden ≤ j's burden from i's perspective), OR
      - removing ONE chore from i's bundle eliminates the envy

    Returns:
        (is_ef1: bool, violations: list of (member_i, member_j) pairs that violate EF1)
    """
    members = list(allocation.keys())
    violations = []

    for i in members:
        for j in members:
            if i == j:
                continue

            burden_i = sum(scores[i].get(c, 0) for c in allocation[i])
            burden_j = sum(scores[i].get(c, 0) for c in allocation[j])

            # i envies j if i's burden is higher than j's (from i's perspective)
            if burden_i <= burden_j:
                continue  # no envy

            # Check if removing one chore from i's bundle eliminates envy
            can_fix = False
            for c in allocation[i]:
                burden_without_c = burden_i - scores[i].get(c, 0)
                if burden_without_c <= burden_j:
                    can_fix = True
                    break

            if not can_fix:
                violations.append((i, j))

    return len(violations) == 0, violations


def compute_max_envy(scores, allocation):
    """
    Compute the maximum envy between any pair of members.

    Envy of i towards j = i's burden - j's burden (from i's perspective).
    Positive means i envies j.

    Returns:
        (max_envy: float, pair: (i, j) or None)
    """
    members = list(allocation.keys())
    max_envy = 0
    worst_pair = None

    for i in members:
        for j in members:
            if i == j:
                continue
            burden_i = sum(scores[i].get(c, 0) for c in allocation[i])
            burden_j = sum(scores[i].get(c, 0) for c in allocation[j])
            envy = burden_i - burden_j
            if envy > max_envy:
                max_envy = envy
                worst_pair = (i, j)

    return max_envy, worst_pair


def compute_workload_balance(scores, allocation):
    """
    Compute workload balance metrics.

    Each member's burden = sum of their OWN scores for their assigned chores.

    Returns dict with:
        min_burden, max_burden, ratio (max/min, inf if min=0),
        std_dev, burdens (dict per member)
    """
    burdens = {}
    for m in allocation:
        burdens[m] = sum(scores[m].get(c, 0) for c in allocation[m])

    values = list(burdens.values())
    min_b = min(values) if values else 0
    max_b = max(values) if values else 0
    mean_b = sum(values) / len(values) if values else 0

    if min_b > 0:
        ratio = max_b / min_b
    elif max_b > 0:
        # Someone got 0 burden → ratio is undefined; expose as None so it
        # serialises as JSON null (float('inf') is not valid JSON).
        ratio = None
    else:
        ratio = 1.0

    # Standard deviation
    if len(values) > 1:
        variance = sum((v - mean_b) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
    else:
        std_dev = 0.0

    return {
        "min": min_b,
        "max": max_b,
        "mean": mean_b,
        "ratio": ratio,
        "std_dev": std_dev,
        "burdens": burdens,
    }


def compute_mms_exact(scores, member, n_members):
    """
    Compute exact MMS value for one member (brute force).
    Only feasible for small instances (≤12 chores).

    MMS = the best worst-case: if this member divided all chores into n bundles,
    what's the minimum burden they could guarantee for their worst bundle?

    For chores with positive scores (higher = worse):
    MMS = min over all partitions of: max bundle burden

    Returns the MMS value (positive number = burden threshold).
    """
    chores = list(scores[member].keys())
    m = len(chores)

    if m == 0:
        return 0

    # For large instances, use approximation
    if m > 8 or n_members > 3:
        return _approximate_mms(scores, member, n_members)

    # Brute force: try all partitions
    best_worst = float('inf')

    def partition(idx, bundles):
        nonlocal best_worst
        if idx == len(chores):
            worst = max(sum(scores[member][c] for c in b) for b in bundles)
            best_worst = min(best_worst, worst)
            return
        for b in bundles:
            b.append(chores[idx])
            partition(idx + 1, bundles)
            b.pop()

    bundles = [[] for _ in range(n_members)]
    partition(0, bundles)
    return best_worst


def _approximate_mms(scores, member, n_members):
    """
    Greedy approximation of MMS for larger instances.
    Sort chores by score descending, round-robin assign to bundles.
    """
    chores = sorted(scores[member].keys(), key=lambda c: scores[member][c], reverse=True)
    bundles = [0.0] * n_members

    for c in chores:
        # Add to the bundle with lowest current burden
        min_idx = min(range(n_members), key=lambda i: bundles[i])
        bundles[min_idx] += scores[member][c]

    return max(bundles)


def compute_mms_ratios(scores, allocation):
    """
    Compute MMS approximation ratio for each member.

    Ratio = member's actual burden / their MMS value.
    Ratio ≤ 1.0 means they got less than their MMS guarantee (good).
    Ratio > 1.0 means they got more burden than their MMS guarantee (bad).

    Returns dict[member] = {burden, mms, ratio}
    """
    members = list(allocation.keys())
    n = len(members)
    result = {}

    for m in members:
        burden = sum(scores[m].get(c, 0) for c in allocation[m])
        mms = compute_mms_exact(scores, m, n)
        ratio = burden / mms if mms > 0 else 0.0
        result[m] = {"burden": burden, "mms": mms, "ratio": ratio}

    return result


def zero_chore_count(allocation):
    """Count how many members got zero chores."""
    return sum(1 for m in allocation if len(allocation[m]) == 0)


def all_chores_assigned(scores, allocation):
    """Check that every chore is assigned exactly once."""
    members = list(scores.keys())
    all_chores = set(scores[members[0]].keys())
    assigned = set()
    for m in allocation:
        for c in allocation[m]:
            if c in assigned:
                return False, f"Chore '{c}' assigned to multiple members"
            assigned.add(c)
    missing = all_chores - assigned
    if missing:
        return False, f"Chores not assigned: {missing}"
    return True, "All chores assigned exactly once"


def compute_all_metrics(scores, allocation):
    """
    Run all metrics on an allocation. Returns a single dict with everything.
    """
    ef1_ok, ef1_violations = check_ef1(scores, allocation)
    max_envy, envy_pair = compute_max_envy(scores, allocation)
    balance = compute_workload_balance(scores, allocation)
    mms = compute_mms_ratios(scores, allocation)
    complete, complete_msg = all_chores_assigned(scores, allocation)

    # Worst MMS ratio across all members
    mms_ratios = [mms[m]["ratio"] for m in mms]
    worst_mms = max(mms_ratios) if mms_ratios else 0

    return {
        "ef1": ef1_ok,
        "ef1_violation_count": len(ef1_violations),
        "max_envy": max_envy,
        "workload_ratio": balance["ratio"],
        "workload_std": balance["std_dev"],
        "worst_mms_ratio": worst_mms,
        "zero_chore_members": zero_chore_count(allocation),
        "all_assigned": complete,
        "burden_min": balance["min"],
        "burden_max": balance["max"],
        "burden_mean": balance["mean"],
    }
