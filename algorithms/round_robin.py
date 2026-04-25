"""
Round-Robin Algorithm for Chore Allocation

Algorithm source:
    Aziz, Rauchecker, Schryen, Walsh (AAAI 2017), Algorithm 1.
    "Algorithms for Max-Min Share Fair Allocation of Indivisible Chores."

How it works:
    Members take turns. On each turn, the current member picks
    the chore they hate LEAST from the remaining pile.
    This continues until all chores are assigned.

Fairness guarantees:
    EF1 (Envy-Free up to One Item):
        Aziz, Caragiannis, Igarashi, Walsh (AAMAS 2022), Section 3.
        "Fair Allocation of Indivisible Goods and Chores."
        Proven for pure chores instances with additive utilities.

    (2 - 1/n) approximation of MMS:
        Aziz et al. (AAAI 2017), Theorem 9.

    Both guarantees hold for unconstrained preferences. Capability
    constraints (is_capable=False) may introduce unavoidable envy
    because members restricted to fewer chores can receive a lighter
    load that others cannot be compensated for.

Input format:
    scores: dict of dict
        scores[member][chore] = positive integer (higher = "I hate this more")
        Example: scores["Alice"]["Dishes"] = 30

    capable: dict of dict
        capable[member][chore] = True/False (can this member do this chore?)
        Example: capable["Alice"]["Shopping"] = False
        If not provided, everyone is assumed capable of everything.

Output format:
    allocation: dict
        allocation[member] = list of chore names assigned to that member
        Example: allocation["Alice"] = ["Trash", "Dishes"]
"""


def round_robin(scores, capable=None):
    """
    Assign chores using greedy round-robin.

    Each member, in turn order, picks the feasible chore
    they dislike the least (lowest score).
    """

    members = list(scores.keys())
    chores = list(scores[members[0]].keys())
    n = len(members)

    # If no capability info given, everyone can do everything
    if capable is None:
        capable = {}
        for m in members:
            capable[m] = {}
            for c in chores:
                capable[m][c] = True

    # --- SETUP ---
    # Start with empty assignment for everyone
    allocation = {}
    for m in members:
        allocation[m] = []

    # Track which chores are still unassigned
    remaining = set(chores)

    # --- MAIN LOOP ---
    # Members take turns picking. Order is just the list order.
    # We cycle through: member 0, member 1, ..., member n-1, member 0, ...
    turn = 0

    while remaining:
        current_member = members[turn % n]

        # Find chores this member CAN do from the remaining pile
        feasible = []
        for c in remaining:
            if capable[current_member][c]:
                feasible.append(c)

        if feasible:
            # Pick the chore with the LOWEST score (least hated)
            best_chore = min(feasible, key=lambda c: scores[current_member][c])

            # Assign it
            allocation[current_member].append(best_chore)
            remaining.remove(best_chore)

        # If no feasible chores for this member, skip their turn

        turn += 1

        # Safety: if we've gone through all members and nothing was assigned,
        # break to avoid infinite loop (means remaining chores are infeasible for everyone)
        if turn > n * len(chores):
            break

    return allocation


# ─── QUICK TEST (only runs if you execute this file directly) ───────────────

if __name__ == "__main__":
    # Example: 3 housemates, 6 chores
    # Scores are "how much do you hate this chore" (1-100 scale)

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

    result = round_robin(scores)

    print("=== Round-Robin Allocation ===\n")
    for member, chores in result.items():
        total = sum(scores[member][c] for c in chores)
        print(f"  {member}: {chores}  (total burden: {total})")