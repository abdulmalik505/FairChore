"""
Bag-Filling Algorithm for Chore Allocation (MMS-oriented)

How it works:
    1. Compute a fairness threshold for each member (how heavy a bag they can tolerate)
    2. Sort chores from hardest to easiest
    3. Start an empty bag. Add chores one-by-one (hardest first).
       Only add a chore if at least one member still finds the bag acceptable.
    4. When no more chores fit: hand the bag to a member who finds it acceptable.
    5. Remove that member and those chores. Repeat with a new bag.
    6. Last member gets whatever remains.

Fairness guarantee:
    1-out-of-floor(2n/3) MMS — each member's total burden is within a known
    bound of their maximin share guarantee.
    Source: Hosseini, Searns, Segal-Halevi, AAMAS 2022, Theorem 4.1.

Input/Output format: same as round_robin.py
    scores[member][chore] = positive integer (higher = worse)
    capable[member][chore] = True/False
    Returns allocation[member] = list of chore names
"""

import math


def _compute_threshold(member_scores, chore_order, n):
    """
    Compute the fairness threshold for one member.

    This is the maximum total burden a bag can have for this member
    to still consider it "acceptable."

    From Hosseini et al. Theorem 4.1, the threshold is the MAX of:
      1. The single hardest chore's score
      2. Sum of the d-th and (d+1)-th hardest chores
      3. Sum of the (2d-1)-th, 2d-th, and (2d+1)-th hardest chores
      4. Total of all scores divided by d

    where d = floor(2n/3).

    We take the MAX because in positive scores (higher = worse),
    the threshold is the loosest acceptable upper bound.

    Args:
        member_scores: dict {chore_name: score} for this member
        chore_order: list of chore names sorted by THIS member's score (descending)
        n: number of members in the household
    """
    m = len(chore_order)
    d = max(math.floor(2 * n / 3), 1)  # at least 1 to avoid division by zero

    # Helper: get score at position idx (0-indexed), return 0 if out of bounds
    # (equivalent to adding dummy chores with value 0, as the paper requires)
    def score_at(idx):
        if idx < m:
            return member_scores[chore_order[idx]]
        return 0

    # Value 1: single hardest chore
    val1 = score_at(0)

    # Value 2: sum of chores at positions d-1 and d (0-indexed)
    # Paper uses 1-indexed c_d and c_{d+1}
    val2 = score_at(d - 1) + score_at(d)

    # Value 3: sum of chores at positions 2d-2, 2d-1, 2d (0-indexed)
    # Paper uses 1-indexed c_{2d-1}, c_{2d}, c_{2d+1}
    val3 = score_at(2 * d - 2) + score_at(2 * d - 1) + score_at(2 * d)

    # Value 4: total score divided by d (proportional share)
    total = sum(member_scores[c] for c in chore_order)
    val4 = total / d

    # Threshold is the maximum of all four
    # (In the paper's negative notation, it's the min. Flipped because we use positive scores.)
    threshold = max(val1, val2, val3, val4)

    return threshold


def _compute_threshold_practical(member_scores, chore_order, n):
    """
    PRACTICAL variant: tighter threshold using d = n instead of d = floor(2n/3).

    Why: The paper's threshold uses d = floor(2n/3), which is too loose for
    small households (n < 6). For n=2, d=1 means the threshold equals the
    total of ALL chores, so one bag swallows everything.

    Fix: Use d = n (proportional share). Each bag can hold at most 1/n of
    the total burden. This forces even distribution across all members.

    The four threshold values from Corollary 3.1 still apply — we just
    compute them with a tighter d, producing smaller (stricter) thresholds.
    """
    m = len(chore_order)
    d = n  # THE KEY CHANGE: use n instead of floor(2n/3)

    def score_at(idx):
        if idx < m:
            return member_scores[chore_order[idx]]
        return 0

    val1 = score_at(0)
    val2 = score_at(d - 1) + score_at(d) if d < m else score_at(0)
    val3 = score_at(2*d - 2) + score_at(2*d - 1) + score_at(2*d) if 2*d < m else val2
    total = sum(member_scores[c] for c in chore_order)
    val4 = total / d

    return max(val1, val2, val3, val4)


def bag_filling(scores, capable=None, variant="paper"):
    """
    Assign chores using the bag-filling algorithm.

    Builds one bag at a time, packing chores from hardest to easiest,
    then hands each bag to a member who finds it acceptable.

    Args:
        scores: dict[member][chore] = score
        capable: dict[member][chore] = True/False
        variant: "paper" = original Hosseini et al. threshold (d = floor(2n/3))
                 "practical" = tighter threshold (d = n) for small households
    """

    members = list(scores.keys())
    all_chores = list(scores[members[0]].keys())
    n = len(members)

    # If no capability info given, everyone can do everything
    if capable is None:
        capable = {}
        for m in members:
            capable[m] = {}
            for c in all_chores:
                capable[m][c] = True

    # --- STEP 1: Compute threshold for each member ---
    thresholds = {}
    for m in members:
        # Sort chores by THIS member's scores, descending (hardest first)
        member_order = sorted(all_chores, key=lambda c: scores[m][c], reverse=True)
        if variant == "practical":
            thresholds[m] = _compute_threshold_practical(scores[m], member_order, n)
        else:
            thresholds[m] = _compute_threshold(scores[m], member_order, n)

    # --- STEP 2: Sort chores by average score across all members (hardest first) ---
    # This gives a global ordering for processing.
    remaining_chores = sorted(
        all_chores,
        key=lambda c: sum(scores[m][c] for m in members) / n,
        reverse=True
    )

    # --- STEP 3: Main bag-filling loop ---
    remaining_members = list(members)
    allocation = {}
    for m in members:
        allocation[m] = []

    while remaining_members and remaining_chores:

        # If only one member left, they get everything remaining
        if len(remaining_members) == 1:
            last_member = remaining_members[0]
            allocation[last_member] = list(remaining_chores)
            remaining_chores = []
            break

        # Start a new empty bag
        bag = []
        bag_scores = {}  # bag_scores[member] = total score of bag for that member
        for m in remaining_members:
            bag_scores[m] = 0

        used_chores = []  # chores added to this bag

        # Try adding chores from hardest to easiest
        for c in list(remaining_chores):

            # Check: can at least one remaining member accept the bag WITH this chore?
            can_add = False
            for m in remaining_members:
                if capable[m][c] and (bag_scores[m] + scores[m][c]) <= thresholds[m]:
                    can_add = True
                    break

            if can_add:
                bag.append(c)
                used_chores.append(c)
                for m in remaining_members:
                    if capable[m][c]:  # Only accumulate burden for capable members
                        bag_scores[m] += scores[m][c]

        # --- STEP 4: Assign the bag to a member who finds it acceptable ---
        assigned = False
        for m in remaining_members:
            # Check: does this member find the bag acceptable?
            # (total burden ≤ their threshold AND they're capable of all chores in the bag)
            all_capable = all(capable[m][c] for c in bag)
            if all_capable and bag_scores[m] <= thresholds[m]:
                allocation[m] = list(bag)
                remaining_members.remove(m)
                for c in used_chores:
                    remaining_chores.remove(c)
                assigned = True
                break

        # If no one found the bag acceptable (edge case),
        # assign to the member with lowest burden for this bag
        if not assigned and bag:
            best_member = min(
                remaining_members,
                key=lambda m: bag_scores[m] if all(capable[m][c] for c in bag) else float('inf')
            )
            allocation[best_member] = list(bag)
            remaining_members.remove(best_member)
            for c in used_chores:
                remaining_chores.remove(c)

        # If bag was empty (no chores could be added), break to avoid infinite loop
        if not used_chores:
            # Give all remaining chores to remaining members via simple distribution
            for i, c in enumerate(list(remaining_chores)):
                m = remaining_members[i % len(remaining_members)]
                allocation[m].append(c)
            remaining_chores = []
            break

    return allocation


# ─── QUICK TEST ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Same example as round_robin.py for comparison

    scores = {
        "Alice": {
            "Dishes": 10, "Cooking": 40, "Vacuuming": 25,
            "Bathroom": 35, "Trash": 5, "Laundry": 15
        },
        "Bob": {
            "Dishes": 30, "Cooking": 15, "Vacuuming": 20,
            "Bathroom": 45, "Trash": 10, "Laundry": 25
        },
        "Carol": {
            "Dishes": 20, "Cooking": 25, "Vacuuming": 40,
            "Bathroom": 15, "Trash": 30, "Laundry": 10
        },
    }

    print("=== Thresholds ===\n")
    n = len(scores)
    for m in scores:
        order = sorted(scores[m].keys(), key=lambda c: scores[m][c], reverse=True)
        t = _compute_threshold(scores[m], order, n)
        print(f"  {m}: threshold = {t:.1f}  (chore order: {order})")

    print()
    result = bag_filling(scores)

    print("=== Bag-Filling Allocation ===\n")
    for member, chores in result.items():
        total = sum(scores[member][c] for c in chores)
        print(f"  {member}: {chores}  (total burden: {total})")
