"""
Baseline Allocation Algorithms (for comparison against fair-division algorithms)

These represent what households currently do WITHOUT fairness algorithms.
Comparing your algorithms against these baselines proves they add value.

Random: each chore assigned to a random capable member
Rotation: chores assigned in fixed order, cycling through members
"""

import random as _random


def random_allocation(scores, capable=None, seed=None):
    """
    Assign each chore to a random capable member.
    No fairness consideration at all.
    """
    rng = _random.Random(seed)
    members = list(scores.keys())
    chores = list(scores[members[0]].keys())

    if capable is None:
        capable = {m: {c: True for c in chores} for m in members}

    allocation = {m: [] for m in members}

    for c in chores:
        feasible = [m for m in members if capable[m][c]]
        if feasible:
            chosen = rng.choice(feasible)
            allocation[chosen].append(c)

    return allocation


def rotation_allocation(scores, capable=None):
    """
    Assign chores in fixed order, cycling through members.
    Chore 1 → member 1, chore 2 → member 2, ..., chore n+1 → member 1, etc.
    Skips if member can't do that chore (gives to next capable member).

    This is what most real households and simple apps do.
    """
    members = list(scores.keys())
    chores = list(scores[members[0]].keys())
    n = len(members)

    if capable is None:
        capable = {m: {c: True for c in chores} for m in members}

    allocation = {m: [] for m in members}

    for i, c in enumerate(chores):
        assigned = False
        for offset in range(n):
            m = members[(i + offset) % n]
            if capable[m][c]:
                allocation[m].append(c)
                assigned = True
                break
        # If no one can do it (shouldn't happen), assign to first member
        if not assigned:
            allocation[members[0]].append(c)

    return allocation


if __name__ == "__main__":
    scores = {
        "Alice": {"Dishes": 10, "Cooking": 40, "Vacuuming": 25, "Bathroom": 35, "Trash": 5, "Laundry": 15},
        "Bob":   {"Dishes": 30, "Cooking": 15, "Vacuuming": 20, "Bathroom": 45, "Trash": 10, "Laundry": 25},
        "Carol": {"Dishes": 20, "Cooking": 25, "Vacuuming": 40, "Bathroom": 15, "Trash": 30, "Laundry": 10},
    }

    print("=== Random Allocation ===")
    result = random_allocation(scores, seed=42)
    for m, c in result.items():
        total = sum(scores[m][ch] for ch in c)
        print(f"  {m}: {c}  (burden: {total})")

    print("\n=== Rotation Allocation ===")
    result = rotation_allocation(scores)
    for m, c in result.items():
        total = sum(scores[m][ch] for ch in c)
        print(f"  {m}: {c}  (burden: {total})")
