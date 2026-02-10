"""Pytest integration for the eval framework."""

import json
from pathlib import Path

from eval.runner import run_all, score_results


def test_eval_all_scenarios_pass():
	"""All eval scenarios should pass."""
	results = run_all()
	scores = score_results(results)

	failures = [s for s in scores["scenarios"] if not s["passed"]]
	failure_details = "\n".join(
		f"  {f['id']}: {f['name']} -- {f.get('error', 'no details')}"
		for f in failures
	)

	assert scores["overall"]["rate"] == 1.0, (
		f"Eval suite: {scores['overall']['passed']}/{scores['overall']['total']} passed.\n"
		f"Failures:\n{failure_details}"
	)


def test_eval_has_minimum_scenarios():
	"""Eval suite should have at least 20 scenarios."""
	from eval.scenarios import SCENARIOS

	assert len(SCENARIOS) >= 20, f"Expected >= 20 scenarios, got {len(SCENARIOS)}"


def test_eval_covers_all_dimensions():
	"""Eval suite should cover all key dimensions."""
	from eval.scenarios import SCENARIOS

	dimensions = {s.dimension for s in SCENARIOS}
	expected = {
		"workflow_lifecycle",
		"bootstrap",
		"tool_disclosure",
		"project_memory",
		"context_recovery",
		"edge_cases",
		"review_artifacts",
	}
	missing = expected - dimensions
	assert not missing, f"Missing dimensions: {missing}"


def test_eval_baseline_exists():
	"""Baseline file should exist after running eval."""
	baseline_path = Path("eval/baseline.json")
	assert baseline_path.exists(), "eval/baseline.json not found -- run eval runner first"

	baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
	assert baseline["overall"]["rate"] == 1.0
	assert baseline["overall"]["total"] >= 20
