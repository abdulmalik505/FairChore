"""
FairChore Simulation — Persona & Scenario Generator

Generates synthetic households with realistic preference profiles.
Each household = a scores table + capability table ready for algorithm input.

Usage:
    from personas import generate_scenario, SCENARIOS
    scenario = generate_scenario(SCENARIOS[0], seed=42)
"""

import random
import math

# ─── CHORE POOL ──────────────────────────────────────────────────────────────
# Each chore has: category, physical effort (1-5), time (1-5),
# minimum age to do it, whether it requires physical mobility

CHORE_POOL = [
    # Kitchen
    {"name": "Wash dishes",       "category": "kitchen",   "effort": 2, "time": 2, "min_age": 8,  "mobility": False},
    {"name": "Cook dinner",       "category": "cooking",   "effort": 3, "time": 4, "min_age": 14, "mobility": False},
    {"name": "Clean counters",    "category": "kitchen",   "effort": 1, "time": 1, "min_age": 8,  "mobility": False},
    {"name": "Clean fridge",      "category": "kitchen",   "effort": 2, "time": 3, "min_age": 12, "mobility": False},
    {"name": "Meal prep",         "category": "cooking",   "effort": 2, "time": 3, "min_age": 14, "mobility": False},
    # Cleaning
    {"name": "Vacuum floors",     "category": "cleaning",  "effort": 3, "time": 3, "min_age": 10, "mobility": True},
    {"name": "Mop floors",        "category": "cleaning",  "effort": 3, "time": 3, "min_age": 12, "mobility": True},
    {"name": "Dust surfaces",     "category": "cleaning",  "effort": 1, "time": 2, "min_age": 8,  "mobility": False},
    {"name": "Tidy living room",  "category": "cleaning",  "effort": 1, "time": 2, "min_age": 6,  "mobility": False},
    {"name": "Sweep entrance",    "category": "cleaning",  "effort": 2, "time": 1, "min_age": 8,  "mobility": True},
    # Bathroom
    {"name": "Clean toilet",      "category": "bathroom",  "effort": 2, "time": 2, "min_age": 14, "mobility": False},
    {"name": "Clean shower",      "category": "bathroom",  "effort": 3, "time": 3, "min_age": 14, "mobility": True},
    {"name": "Clean sink",        "category": "bathroom",  "effort": 1, "time": 1, "min_age": 10, "mobility": False},
    {"name": "Restock bathroom",  "category": "bathroom",  "effort": 1, "time": 1, "min_age": 12, "mobility": False},
    # Laundry
    {"name": "Do laundry",        "category": "laundry",   "effort": 2, "time": 2, "min_age": 12, "mobility": False},
    {"name": "Hang dry clothes",  "category": "laundry",   "effort": 2, "time": 2, "min_age": 10, "mobility": True},
    {"name": "Fold clothes",      "category": "laundry",   "effort": 1, "time": 2, "min_age": 8,  "mobility": False},
    {"name": "Iron clothes",      "category": "laundry",   "effort": 2, "time": 3, "min_age": 14, "mobility": False},
    # Outdoor
    {"name": "Take out trash",    "category": "outdoor",   "effort": 2, "time": 1, "min_age": 10, "mobility": True},
    {"name": "Recycling",         "category": "outdoor",   "effort": 1, "time": 1, "min_age": 8,  "mobility": True},
    {"name": "Grocery shopping",  "category": "outdoor",   "effort": 3, "time": 4, "min_age": 16, "mobility": True},
    {"name": "Yard work",         "category": "outdoor",   "effort": 4, "time": 3, "min_age": 14, "mobility": True},
    # General
    {"name": "Change bed sheets", "category": "general",   "effort": 2, "time": 2, "min_age": 10, "mobility": True},
    {"name": "Water plants",      "category": "general",   "effort": 1, "time": 1, "min_age": 6,  "mobility": False},
    {"name": "Clean windows",     "category": "general",   "effort": 3, "time": 3, "min_age": 14, "mobility": True},
]

ALL_CATEGORIES = ["kitchen", "cooking", "cleaning", "bathroom", "laundry", "outdoor", "general"]

# ─── PERSONA TEMPLATES ───────────────────────────────────────────────────────
# category_weights: higher number = dislikes that category MORE
# effort_sensitivity: how much physical effort matters to this person
# base_burden: overall multiplier (busy people find everything harder)
# restricted_categories: categories this person CANNOT do
# restricted_mobility: if True, cannot do chores requiring mobility
# age: affects which chores they can do (compared to chore min_age)
# contribution: expected share (1.0 = full share, 0.5 = half share)

PERSONA_TEMPLATES = {
    "balanced_adult": {
        "category_weights": {"kitchen": 1.0, "cooking": 1.0, "cleaning": 1.0, "bathroom": 1.0, "laundry": 1.0, "outdoor": 1.0, "general": 1.0},
        "effort_sensitivity": 1.0,
        "base_burden": 1.0,
        "restricted_mobility": False,
        "age": 30,
        "contribution": 1.0,
        "description": "No strong preferences, handles everything equally",
    },
    "busy_worker": {
        "category_weights": {"kitchen": 1.1, "cooking": 1.3, "cleaning": 1.2, "bathroom": 1.1, "laundry": 1.0, "outdoor": 1.2, "general": 1.0},
        "effort_sensitivity": 1.3,
        "base_burden": 1.4,
        "restricted_mobility": False,
        "age": 30,
        "contribution": 0.7,
        "description": "Time-pressed, dislikes everything more, especially time-consuming chores",
    },
    "clean_freak": {
        "category_weights": {"kitchen": 0.6, "cooking": 1.0, "cleaning": 0.5, "bathroom": 0.6, "laundry": 0.7, "outdoor": 1.3, "general": 0.8},
        "effort_sensitivity": 0.8,
        "base_burden": 0.9,
        "restricted_mobility": False,
        "age": 25,
        "contribution": 1.0,
        "description": "Doesn't mind cleaning, dislikes outdoor/physical tasks",
    },
    "bathroom_hater": {
        "category_weights": {"kitchen": 1.0, "cooking": 0.9, "cleaning": 1.0, "bathroom": 2.0, "laundry": 1.0, "outdoor": 0.9, "general": 1.0},
        "effort_sensitivity": 1.0,
        "base_burden": 1.0,
        "restricted_mobility": False,
        "age": 25,
        "contribution": 1.0,
        "description": "Strong aversion to bathroom chores specifically",
    },
    "kitchen_lover": {
        "category_weights": {"kitchen": 0.5, "cooking": 0.4, "cleaning": 1.3, "bathroom": 1.2, "laundry": 1.1, "outdoor": 1.0, "general": 1.0},
        "effort_sensitivity": 1.0,
        "base_burden": 1.0,
        "restricted_mobility": False,
        "age": 28,
        "contribution": 1.0,
        "description": "Enjoys cooking and kitchen work, dislikes cleaning",
    },
    "outdoor_preferer": {
        "category_weights": {"kitchen": 1.3, "cooking": 1.1, "cleaning": 1.4, "bathroom": 1.3, "laundry": 1.2, "outdoor": 0.5, "general": 0.8},
        "effort_sensitivity": 0.8,
        "base_burden": 1.0,
        "restricted_mobility": False,
        "age": 25,
        "contribution": 1.0,
        "description": "Prefers outdoor and physical tasks, dislikes indoor cleaning",
    },
    "avoidant": {
        "category_weights": {"kitchen": 1.2, "cooking": 1.3, "cleaning": 1.5, "bathroom": 1.4, "laundry": 1.3, "outdoor": 0.9, "general": 1.1},
        "effort_sensitivity": 1.5,
        "base_burden": 1.4,
        "restricted_mobility": False,
        "age": 22,
        "contribution": 1.0,
        "description": "Dislikes most chores, especially effort-heavy ones",
    },
    "teenager": {
        "category_weights": {"kitchen": 1.1, "cooking": 1.3, "cleaning": 1.2, "bathroom": 1.5, "laundry": 1.0, "outdoor": 0.8, "general": 1.0},
        "effort_sensitivity": 0.9,
        "base_burden": 1.1,
        "restricted_mobility": False,
        "age": 15,
        "contribution": 0.6,
        "description": "Can do most chores but avoids bathroom and cooking",
    },
    "young_child": {
        "category_weights": {"kitchen": 0.8, "cooking": 1.5, "cleaning": 0.7, "bathroom": 1.5, "laundry": 0.9, "outdoor": 0.7, "general": 0.6},
        "effort_sensitivity": 1.5,
        "base_burden": 0.8,
        "restricted_mobility": False,
        "age": 9,
        "contribution": 0.3,
        "description": "Can only do light, safe chores",
    },
    "elderly": {
        "category_weights": {"kitchen": 0.7, "cooking": 0.8, "cleaning": 1.3, "bathroom": 1.1, "laundry": 0.9, "outdoor": 1.8, "general": 0.9},
        "effort_sensitivity": 2.0,
        "base_burden": 1.0,
        "restricted_mobility": True,
        "age": 70,
        "contribution": 0.4,
        "description": "Prefers light indoor tasks, cannot do physical/mobility chores",
    },
    "injured_member": {
        "category_weights": {"kitchen": 0.9, "cooking": 1.0, "cleaning": 1.2, "bathroom": 1.0, "laundry": 1.0, "outdoor": 1.5, "general": 1.0},
        "effort_sensitivity": 2.0,
        "base_burden": 1.1,
        "restricted_mobility": True,
        "age": 30,
        "contribution": 0.5,
        "description": "Temporary injury, cannot do mobility-requiring chores",
    },
    "exam_period": {
        "category_weights": {"kitchen": 1.0, "cooking": 1.2, "cleaning": 1.1, "bathroom": 1.0, "laundry": 1.0, "outdoor": 1.0, "general": 1.0},
        "effort_sensitivity": 1.2,
        "base_burden": 1.5,
        "restricted_mobility": False,
        "age": 21,
        "contribution": 0.4,
        "description": "Temporarily stressed, reduced contribution expected",
    },
}


# ─── SCENARIO DEFINITIONS ────────────────────────────────────────────────────
# Each scenario: name, member definitions, chore count range, description

SCENARIOS = [
    # --- Small households (2-3) ---
    {
        "name": "Equal couple",
        "members": [("Partner A", "balanced_adult"), ("Partner B", "balanced_adult")],
        "chore_range": (6, 10),
        "description": "Two adults, similar preferences, no constraints",
    },
    {
        "name": "Unequal couple",
        "members": [("Worker", "busy_worker"), ("Home partner", "clean_freak")],
        "chore_range": (8, 12),
        "description": "One busy worker, one who doesn't mind cleaning",
    },
    {
        "name": "Student flat (3)",
        "members": [("Student A", "balanced_adult"), ("Student B", "kitchen_lover"), ("Student C", "outdoor_preferer")],
        "chore_range": (8, 12),
        "description": "Three students with different preferences",
    },
    {
        "name": "Student flat with freeloader",
        "members": [("Student A", "clean_freak"), ("Student B", "balanced_adult"), ("Student C", "avoidant")],
        "chore_range": (8, 12),
        "description": "One member avoids chores — tests fairness under asymmetry",
    },
    {
        "name": "Couple + lodger",
        "members": [("Partner A", "balanced_adult"), ("Partner B", "kitchen_lover"), ("Lodger", "busy_worker")],
        "chore_range": (8, 12),
        "description": "Couple plus one outsider with different availability",
    },
    # --- Medium households (4-6) ---
    {
        "name": "Family with young kids",
        "members": [("Parent A", "balanced_adult"), ("Parent B", "busy_worker"), ("Child 1", "young_child"), ("Child 2", "young_child")],
        "chore_range": (10, 15),
        "description": "Two adults + two children with capability restrictions",
    },
    {
        "name": "Family with teenagers",
        "members": [("Parent A", "balanced_adult"), ("Parent B", "kitchen_lover"), ("Teen 1", "teenager"), ("Teen 2", "teenager"), ("Teen 3", "teenager")],
        "chore_range": (12, 16),
        "description": "Parents + teens who can do most chores but avoid some",
    },
    {
        "name": "Professional houseshare",
        "members": [("Worker A", "busy_worker"), ("Worker B", "busy_worker"), ("Worker C", "bathroom_hater"), ("Worker D", "outdoor_preferer")],
        "chore_range": (10, 14),
        "description": "All working adults, limited time, strong preferences",
    },
    {
        "name": "Mixed houseshare",
        "members": [("Student", "exam_period"), ("Worker A", "busy_worker"), ("Worker B", "balanced_adult"), ("Freelancer", "clean_freak"), ("New flatmate", "balanced_adult")],
        "chore_range": (12, 16),
        "description": "Different lifestyles, one in exam period (reduced contribution)",
    },
    {
        "name": "Student house (6)",
        "members": [("S1", "balanced_adult"), ("S2", "kitchen_lover"), ("S3", "outdoor_preferer"), ("S4", "avoidant"), ("S5", "clean_freak"), ("S6", "bathroom_hater")],
        "chore_range": (14, 20),
        "description": "Large student flat, very diverse preferences",
    },
    # --- Large households (6+) ---
    {
        "name": "Multi-generational family",
        "members": [("Parent A", "balanced_adult"), ("Parent B", "kitchen_lover"), ("Teen", "teenager"), ("Grandparent", "elderly"), ("Aunt/Uncle", "busy_worker"), ("Cousin", "teenager")],
        "chore_range": (14, 20),
        "description": "Mixed ages with elderly and youth capability constraints",
    },
    {
        "name": "Large houseshare (8)",
        "members": [("M1", "balanced_adult"), ("M2", "busy_worker"), ("M3", "clean_freak"), ("M4", "avoidant"), ("M5", "kitchen_lover"), ("M6", "outdoor_preferer"), ("M7", "bathroom_hater"), ("M8", "balanced_adult")],
        "chore_range": (18, 24),
        "description": "Large house, diverse preferences, coordination challenge",
    },
    {
        "name": "Houseshare with injured member",
        "members": [("M1", "balanced_adult"), ("M2", "balanced_adult"), ("M3", "injured_member"), ("M4", "kitchen_lover")],
        "chore_range": (10, 14),
        "description": "One member with mobility restrictions",
    },
    {
        "name": "All similar preferences",
        "members": [("M1", "balanced_adult"), ("M2", "balanced_adult"), ("M3", "balanced_adult"), ("M4", "balanced_adult")],
        "chore_range": (10, 14),
        "description": "Worst case — everyone hates the same things equally",
    },
    {
        "name": "Extreme preference conflict",
        "members": [("Clean freak", "clean_freak"), ("Avoidant", "avoidant"), ("Bathroom hater", "bathroom_hater"), ("Busy worker", "busy_worker")],
        "chore_range": (10, 14),
        "description": "Strong preference conflicts — tests algorithm robustness",
    },
    {
        "name": "Very large household (10)",
        "members": [
            ("M1", "balanced_adult"), ("M2", "busy_worker"), ("M3", "clean_freak"),
            ("M4", "avoidant"), ("M5", "kitchen_lover"), ("M6", "outdoor_preferer"),
            ("M7", "teenager"), ("M8", "balanced_adult"), ("M9", "bathroom_hater"),
            ("M10", "exam_period"),
        ],
        "chore_range": (20, 28),
        "description": "10 members, highly diverse, one temporarily reduced",
    },
    {
        "name": "Stress test (15)",
        "members": [
            ("M1", "balanced_adult"), ("M2", "busy_worker"), ("M3", "clean_freak"),
            ("M4", "avoidant"), ("M5", "kitchen_lover"), ("M6", "outdoor_preferer"),
            ("M7", "teenager"), ("M8", "elderly"), ("M9", "bathroom_hater"),
            ("M10", "exam_period"), ("M11", "balanced_adult"), ("M12", "injured_member"),
            ("M13", "busy_worker"), ("M14", "teenager"), ("M15", "balanced_adult"),
        ],
        "chore_range": (25, 30),
        "description": "Maximum size, multiple constraints, maximum diversity",
    },
]


# ─── SCORE GENERATION ────────────────────────────────────────────────────────

def _select_chores(chore_count, rng):
    """Pick a random subset of chores from the pool."""
    count = min(chore_count, len(CHORE_POOL))
    return rng.sample(CHORE_POOL, count)


def _can_do_chore(persona_template, chore):
    """Check if a persona can physically do a chore."""
    template = PERSONA_TEMPLATES[persona_template]

    # Age restriction
    if template["age"] < chore["min_age"]:
        return False

    # Mobility restriction
    if template["restricted_mobility"] and chore["mobility"]:
        return False

    return True


def _generate_raw_score(persona_template, chore, rng):
    """
    Generate a raw disutility score for one person + one chore.

    Score = base_effort * category_weight * effort_sensitivity * base_burden + noise
    Higher = hates more.
    """
    template = PERSONA_TEMPLATES[persona_template]

    # Base: chore's inherent effort (1-5)
    base = chore["effort"] + chore["time"] * 0.5

    # Category preference
    cat_weight = template["category_weights"].get(chore["category"], 1.0)

    # Effort sensitivity
    effort_mult = template["effort_sensitivity"]

    # Overall burden
    burden = template["base_burden"]

    # Compute raw score
    raw = base * cat_weight * effort_mult * burden

    # Add noise (±20% variation)
    noise = rng.gauss(0, raw * 0.2)
    raw = max(0.1, raw + noise)  # keep positive

    return raw


def generate_scores_budget(members_with_personas, chores, rng):
    """
    Generate scores using 100-point budget system.
    Each member distributes exactly 100 points across all chores.
    Higher = "I hate this more."
    """
    scores = {}
    capable = {}

    for member_name, persona_type in members_with_personas:
        # Generate raw scores
        raw = {}
        cap = {}
        for chore in chores:
            c_name = chore["name"]
            cap[c_name] = _can_do_chore(persona_type, chore)
            raw[c_name] = _generate_raw_score(persona_type, chore, rng)

        # Normalize to sum to 100
        total_raw = sum(raw.values())
        if total_raw > 0:
            scores[member_name] = {c: round(raw[c] / total_raw * 100, 1) for c in raw}
        else:
            # Fallback: equal distribution
            n_chores = len(chores)
            scores[member_name] = {c: round(100 / n_chores, 1) for c in raw}

        capable[member_name] = cap

    return scores, capable


def generate_scores_rating(members_with_personas, chores, rng):
    """
    Generate scores using 1-10 per-chore rating.
    Each chore rated independently. No budget constraint.
    """
    scores = {}
    capable = {}

    for member_name, persona_type in members_with_personas:
        raw = {}
        cap = {}
        for chore in chores:
            c_name = chore["name"]
            cap[c_name] = _can_do_chore(persona_type, chore)
            raw_score = _generate_raw_score(persona_type, chore, rng)
            # Scale to 1-10 range
            # Raw scores typically range from ~0.5 to ~15, map to 1-10
            scaled = max(1, min(10, round(raw_score * 1.2)))
            raw[c_name] = scaled

        scores[member_name] = raw
        capable[member_name] = cap

    return scores, capable


def generate_scenario(scenario_def, scoring="budget", seed=None):
    """
    Generate a complete scenario ready for algorithm input.

    Args:
        scenario_def: one entry from SCENARIOS list
        scoring: "budget" (100 points) or "rating" (1-10 per chore)
        seed: random seed for reproducibility

    Returns dict with:
        - name: scenario name
        - description: what this scenario tests
        - members: list of (name, persona_type) tuples
        - chores: list of chore dicts
        - scores: dict[member][chore] = number
        - capable: dict[member][chore] = True/False
        - scoring_method: "budget" or "rating"
        - seed: the seed used
    """
    rng = random.Random(seed)

    # Select chores
    chore_min, chore_max = scenario_def["chore_range"]
    chore_count = rng.randint(chore_min, chore_max)
    chores = _select_chores(chore_count, rng)

    # Generate scores
    members = scenario_def["members"]
    if scoring == "budget":
        scores, capable = generate_scores_budget(members, chores, rng)
    else:
        scores, capable = generate_scores_rating(members, chores, rng)

    return {
        "name": scenario_def["name"],
        "description": scenario_def["description"],
        "members": members,
        "chores": chores,
        "chore_names": [c["name"] for c in chores],
        "scores": scores,
        "capable": capable,
        "scoring_method": scoring,
        "seed": seed,
        "n_members": len(members),
        "n_chores": len(chores),
    }


# ─── QUICK TEST ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Available Scenarios ===\n")
    for i, s in enumerate(SCENARIOS):
        n = len(s["members"])
        c_lo, c_hi = s["chore_range"]
        print(f"  {i+1:2d}. {s['name']} ({n} members, {c_lo}-{c_hi} chores)")
        print(f"      {s['description']}")

    print(f"\n=== Sample: Generating '{SCENARIOS[2]['name']}' ===\n")
    result = generate_scenario(SCENARIOS[2], scoring="budget", seed=42)
    print(f"Members: {[m[0] for m in result['members']]}")
    print(f"Chores ({result['n_chores']}): {result['chore_names']}")
    print(f"\nScores (100-point budget):")
    for member in result["scores"]:
        total = sum(result["scores"][member].values())
        print(f"  {member}: total={total:.1f}")
        for chore, score in sorted(result["scores"][member].items(), key=lambda x: -x[1])[:5]:
            cap = "✓" if result["capable"][member][chore] else "✗"
            print(f"    {chore}: {score} [{cap}]")
