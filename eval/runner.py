"""Eval runner -- executes scenarios and produces scored results.

Usage:
	python -m eval.runner              # Run all scenarios, print report
	python -m eval.runner --baseline   # Run and save baseline.json
"""

import json
import sys
import tempfile
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .scenarios import SCENARIOS, ScenarioResult


def run_scenario(scenario: "Scenario") -> ScenarioResult:  # noqa: F821
	"""Run a single scenario in an isolated temp directory."""
	with tempfile.TemporaryDirectory() as tmp:
		tmp_path = Path(tmp)
		try:
			scenario.setup(tmp_path)
			result = scenario.check(tmp_path)
			return ScenarioResult(
				id=scenario.id,
				name=scenario.name,
				dimension=scenario.dimension,
				passed=result.get("passed", False),
				details=result,
			)
		except Exception as e:
			return ScenarioResult(
				id=scenario.id,
				name=scenario.name,
				dimension=scenario.dimension,
				passed=False,
				error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
			)


def run_all() -> list[ScenarioResult]:
	"""Run all scenarios and return results."""
	return [run_scenario(s) for s in SCENARIOS]


def score_results(results: list[ScenarioResult]) -> dict:
	"""Score results by dimension and overall."""
	by_dimension: dict[str, list[ScenarioResult]] = defaultdict(list)
	for r in results:
		by_dimension[r.dimension].append(r)

	dimension_scores = {}
	for dim, dim_results in sorted(by_dimension.items()):
		passed = sum(1 for r in dim_results if r.passed)
		total = len(dim_results)
		dimension_scores[dim] = {
			"passed": passed,
			"total": total,
			"rate": round(passed / total, 3) if total > 0 else 0,
		}

	total_passed = sum(1 for r in results if r.passed)
	total = len(results)

	return {
		"timestamp": datetime.now().isoformat(),
		"overall": {
			"passed": total_passed,
			"total": total,
			"rate": round(total_passed / total, 3) if total > 0 else 0,
		},
		"dimensions": dimension_scores,
		"scenarios": [
			{
				"id": r.id,
				"name": r.name,
				"dimension": r.dimension,
				"passed": r.passed,
				"error": r.error or None,
			}
			for r in results
		],
	}


def print_report(scores: dict) -> None:
	"""Print a human-readable report."""
	overall = scores["overall"]
	print(f"\n{'=' * 60}")
	print(f"  Eval Results: {overall['passed']}/{overall['total']} passed "
		  f"({overall['rate'] * 100:.1f}%)")
	print(f"{'=' * 60}\n")

	for dim, dim_scores in sorted(scores["dimensions"].items()):
		status = "PASS" if dim_scores["rate"] == 1.0 else "FAIL"
		print(f"  [{status}] {dim}: "
			  f"{dim_scores['passed']}/{dim_scores['total']} "
			  f"({dim_scores['rate'] * 100:.0f}%)")

	# Print failures
	failures = [s for s in scores["scenarios"] if not s["passed"]]
	if failures:
		print(f"\n{'─' * 60}")
		print("  Failures:\n")
		for f in failures:
			print(f"  {f['id']}: {f['name']}")
			if f.get("error"):
				# Print first line of error
				print(f"    {f['error'].splitlines()[0]}")

	print()


def save_baseline(scores: dict, path: str = "eval/baseline.json") -> None:
	"""Save scores as baseline."""
	Path(path).write_text(
		json.dumps(scores, indent=2),
		encoding="utf-8",
	)
	print(f"  Baseline saved to {path}")


def main() -> None:
	"""Run eval suite."""
	results = run_all()
	scores = score_results(results)
	print_report(scores)

	if "--baseline" in sys.argv:
		save_baseline(scores)

	# Exit with error code if any failures
	if scores["overall"]["rate"] < 1.0:
		sys.exit(1)


if __name__ == "__main__":
	main()
