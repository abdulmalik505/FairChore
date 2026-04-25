"""
Top-Trading Envy-Cycle Elimination for Chore Allocation (EF1-guaranteed)

Based on: Bhaskar, Sricharan, Vaish (2021)
  "On Approximate Envy-Freeness for Indivisible Chores and Mixed Resources"
  APPROX/RANDOM 2021, LIPIcs Vol. 207, pp. 1:1–1:23.

Why this algorithm exists:
    The standard envy-cycle elimination (Lipton et al. 2004) was designed for
    GOODS. It does NOT work for CHORES because swapping bundles in a regular
    envy graph can CREATE new EF1 violations.

    Bhaskar et al. fixed this by using a TOP-TRADING envy graph: each person
    points ONLY to whoever holds their single most-preferred bundle (lowest
    burden). Cycles in this graph are safe to rotate without breaking EF1.

How it works:
    1. Start with empty bundles for everyone.
    2. Process chores one at a time (hardest first by average score).
    3. Before assigning each chore:
       a. Build the top-trading envy graph:
          - Each person looks at ALL bundles (including their own).
          - If someone else's bundle is their favourite, they point to that person.
          - If their own bundle is their favourite (lowest burden), no outgoing
            edge — they are a SINK.
       b. If cycles exist, rotate bundles along the cycle:
          - Everyone in the cycle gets the bundle they pointed to.
          - Rebuild the graph and check for more cycles.
       c. Find a sink (someone who doesn't envy anyone).
       d. Assign the chore to the sink.
    4. Return the final allocation.

Why sinks always exist:
    The top-trading graph is a FUNCTIONAL graph (each node has at most 1
    outgoing edge). After removing all cycles, at least one node must have
    no outgoing edge. That node is a sink.

Fairness guarantee:
    EF1 — for every pair of members i, j, member i does not envy member j
    after removing at most one chore from i's bundle.

    This is the SAME guarantee as Round-Robin, but achieved through a
    completely different mechanism (graph-based swaps vs greedy picking).

    This guarantee holds for unconstrained preferences. Capability
    constraints (is_capable=False) may introduce unavoidable envy
    in some cases, because members restricted to fewer chores can
    receive a lighter load that others cannot be compensated for.

    Why EF1 holds: The sink doesn't envy anyone before receiving the chore.
    After receiving one chore, they might envy someone — but only by that
    single chore. That's exactly the EF1 definition.

Complexity:
    O(n² · m) — for each of m chores, we may rebuild the graph (O(n²)) and
    detect/resolve cycles. Polynomial and fast for household sizes.

Difference from the other two algorithms:
    - Round-Robin (greedy):  members take turns picking least-disliked chore
    - Bag-Filling (threshold): packs chores into bundles up to a fairness limit
    - Top-Trading (graph):  resolves envy via bundle swaps, assigns to non-envious member

Input/Output format: same as round_robin.py and bag_filling.py
    scores[member][chore] = positive integer (higher = "I hate this more")
    capable[member][chore] = True/False (can this member do this chore?)
    Returns allocation[member] = list of chore names
"""


def _bundle_burden(scores, member, bundle, capable=None):
    """
    Compute total burden of a bundle for a specific member.

    If capable is provided and the bundle contains any chore this member
    cannot do, returns infinity. This prevents cycle rotations from ever
    routing infeasible chores to incapable members — a member will never
    "want" a bundle they can't actually perform.

    Example: if bundle = ["Dishes", "Trash"] and scores["Alice"]["Dishes"] = 30,
    scores["Alice"]["Trash"] = 5, then _bundle_burden(scores, "Alice", bundle) = 35.

    But if capable["Alice"]["Dishes"] = False, returns float('inf') instead.
    """
    if capable is not None:
        for c in bundle:
            if not capable[member][c]:
                return float('inf')
    return sum(scores[member][c] for c in bundle)


def _build_top_trading_graph(scores, bundles, members, capable=None):
    """
    Build the top-trading envy graph.

    Each member points to whoever holds their single most-preferred bundle
    (lowest total burden from THEIR perspective). If their own bundle is
    best (or tied), they don't point anywhere — they're a sink.

    When capable is provided, bundles containing infeasible chores are
    treated as infinitely burdensome, so no member will ever point toward
    a bundle they couldn't actually perform.

    Returns:
        dict — {member: target_member} for members who point somewhere.
               Members NOT in the dict are sinks (they prefer their own bundle).

    Example with 3 members:
        If Alice prefers Bob's bundle, Bob prefers his own, Carol prefers Alice's:
        graph = {"Alice": "Bob", "Carol": "Alice"}
        Sinks = ["Bob"]  (Bob is not in graph → he's happy with his own bundle)
    """
    graph = {}

    for member in members:
        # Evaluate every bundle from this member's perspective
        best_owner = member  # default: own bundle is best
        best_burden = _bundle_burden(scores, member, bundles[member], capable)

        for other in members:
            if other == member:
                continue
            other_burden = _bundle_burden(scores, member, bundles[other], capable)
            if other_burden < best_burden:
                # This member would prefer the other's bundle (less burden)
                best_burden = other_burden
                best_owner = other
            # On ties: keep own bundle (don't add edge). This reduces
            # unnecessary swaps and is consistent with the paper.

        if best_owner != member:
            graph[member] = best_owner

    return graph


def _find_cycle(graph, members):
    """
    Find a cycle in a functional graph (each node has at most 1 outgoing edge).

    Uses path-following: start at a node, follow edges until we either
    revisit a node on our current path (cycle found) or reach a dead end (sink).

    Returns:
        list of members forming a cycle, or None if no cycle exists.

    Example:
        graph = {"A": "B", "B": "C", "C": "A"}
        Returns ["A", "B", "C"]  (A→B→C→A is a cycle)
    """
    visited_global = set()  # nodes fully explored (no cycle through them)

    for start in members:
        if start in visited_global or start not in graph:
            # Already processed, or is a sink (no outgoing edge) — skip
            continue

        # Follow the path from this node
        path = []
        path_set = set()
        current = start

        while current not in visited_global and current in graph and current not in path_set:
            path.append(current)
            path_set.add(current)
            current = graph[current]

        if current in path_set:
            # We revisited a node on our current path — that's a cycle
            cycle_start_idx = path.index(current)
            return path[cycle_start_idx:]

        # No cycle from this starting point — mark all as explored
        visited_global.update(path)

    return None


def _rotate_bundles(bundles, cycle, graph):
    """
    Rotate bundles along a cycle in the top-trading graph.

    Each member in the cycle gets the bundle of the member they pointed to.
    This resolves envy within the cycle — everyone gets what they wanted.

    Capability safety: Because _build_top_trading_graph treats infeasible
    bundles as infinitely burdensome, no member will ever point toward a
    bundle containing chores they cannot do. Therefore, cycle rotations
    never route infeasible chores to incapable members.

    Example:
        cycle = ["A", "B", "C"] where A→B, B→C, C→A
        Before: A has [Dishes], B has [Trash], C has [Cooking]
        After:  A gets B's old bundle [Trash],
                B gets C's old bundle [Cooking],
                C gets A's old bundle [Dishes]
    """
    # Save the bundles before swapping (need copies, not references)
    saved = {}
    for member in cycle:
        target = graph[member]  # who this member points to
        saved[member] = bundles[target][:]  # copy the bundle they want

    # Apply the rotation
    for member in cycle:
        bundles[member] = saved[member]


def top_trading_envy_cycle(scores, capable=None):
    """
    Top-Trading Envy-Cycle Elimination for chore allocation.

    Each member, in order of processing, resolves envy through bundle
    swaps. Chores are then assigned to non-envious members (sinks).
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

    # Handle edge case: single member gets all feasible chores
    if n == 1:
        only = members[0]
        for c in chores:
            if capable[only][c]:
                allocation[only].append(c)
        return allocation

    # Handle edge case: no chores
    if not chores:
        return allocation

    # --- CHORE ORDERING ---
    # Process chores from hardest to easiest (by average score).
    # The paper allows arbitrary order and EF1 still holds, but
    # hardest-first tends to produce better balance because the
    # most contentious chores get resolved while bundles are small.
    def avg_score(chore):
        return sum(scores[m][chore] for m in members) / n

    chore_order = sorted(chores, key=avg_score, reverse=True)

    # --- MAIN LOOP: assign one chore per iteration ---
    for chore in chore_order:
        # Step 1: Build top-trading envy graph (capability-aware)
        graph = _build_top_trading_graph(scores, allocation, members, capable)

        # Step 2: Eliminate all cycles by rotating bundles
        # Safety bound: each rotation removes at least one cycle,
        # and there are at most n nodes, so at most n² iterations.
        max_iterations = n * n
        iteration = 0
        while iteration < max_iterations:
            cycle = _find_cycle(graph, members)
            if cycle is None:
                break  # No more cycles — safe to assign
            _rotate_bundles(allocation, cycle, graph)
            # Rebuild graph (bundle ownership changed)
            graph = _build_top_trading_graph(scores, allocation, members, capable)
            iteration += 1

        # Step 3: Find sinks (members not in graph = prefer own bundle)
        sinks = [m for m in members if m not in graph]

        # Step 4: Pick which sink gets this chore
        # Filter by capability
        eligible = [s for s in sinks if capable[s][chore]]

        # Fallback: if no capable sink, try all capable members
        if not eligible:
            eligible = [m for m in members if capable[m][chore]]

        # Last resort: any member (shouldn't happen with valid input)
        if not eligible:
            eligible = list(members)

        # Among eligible, assign to whoever finds this chore LEAST
        # burdensome. Any choice preserves EF1, but picking the member
        # who minds least improves overall balance.
        chosen = min(eligible, key=lambda m: scores[m][chore])

        allocation[chosen].append(chore)

    return allocation


# ─── QUICK TEST (only runs if you execute this file directly) ───────────────

if __name__ == "__main__":
    # Same example used in round_robin.py and bag_filling.py
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

    result = top_trading_envy_cycle(scores)

    print("=== Top-Trading Envy-Cycle Allocation ===\n")
    for member, assigned in result.items():
        total = sum(scores[member][c] for c in assigned)
        print(f"  {member}: {assigned}  (total burden: {total})")
