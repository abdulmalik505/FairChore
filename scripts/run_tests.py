"""
FairChore Test Runner

Runs all four test suites and prints a report-ready summary.

Suites:
  1. Unit tests       — algorithm correctness and fairness metrics
  2. Integration tests — multi-round fairness across all 17 simulation scenarios
  3. API tests        — HTTP endpoint tests via Flask test client (requires PostgreSQL)
  4. DB / Schema tests — database schema structure and seed data integrity

Usage:
  python scripts/run_tests.py
"""

import subprocess
import sys
import os
import io
import time

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LINE = "=" * 72
results = []


def run(label, cmd):
    print(f"\n{LINE}")
    print(f"  {label}")
    print(LINE)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=False)
    elapsed = time.time() - t0
    results.append((label, r.returncode, elapsed))
    return r.returncode


run("1. UNIT TESTS  — Algorithm correctness & fairness metrics",
    [sys.executable, "tests/unit/test_algorithms.py"])

run("2. INTEGRATION TESTS  — Multi-round fairness (all 17 scenarios × 3 algorithms)",
    [sys.executable, "tests/integration/test_fairness_over_time.py"])

run("3. API TESTS  — Flask endpoint behaviour (requires PostgreSQL running)",
    [sys.executable, "-m", "pytest", "tests/api/", "-v", "--tb=short", "-q"])

run("4. DB / SCHEMA TESTS  — Schema structure & seed data integrity",
    [sys.executable, "-m", "pytest", "tests/db/", "-v", "--tb=short", "-q"])


# ── Report-ready summary ──────────────────────────────────────────────────────

print(f"\n\n{LINE}")
print("  FAIRCHORE TEST REPORT — OVERALL RESULTS")
print(LINE)
print()

all_passed = True
for label, code, elapsed in results:
    status = "PASS" if code == 0 else "FAIL"
    mark   = "✓" if code == 0 else "✗"
    print(f"  [{status}]  {mark}  {label}")
    print(f"           Completed in {elapsed:.1f}s")
    print()
    if code != 0:
        all_passed = False

print(LINE)
if all_passed:
    print("  RESULT: ALL TEST SUITES PASSED")
else:
    print("  RESULT: ONE OR MORE SUITES FAILED — see output above for details")
print(LINE)
print()

sys.exit(0 if all_passed else 1)
