#!/usr/bin/env python3
"""
Interactive Demo - Motion Detection Project via Orchestration.

This demo shows the orchestrator implementing a real motion detection
project using background subtraction techniques with OpenCV.

Run with: python -m tests.orchestration.demo
"""

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.orchestration.framework import OrchestrationTestFramework, OrchestrationPhase
from tests.orchestration.visualizer import Visualizer


# Pre-filled planning answers for the motion detection project
MOTION_DETECTION_ANSWERS = {
	# Requirements phase
	"q1": "Detect motion in video streams using background subtraction. The system should identify moving objects and highlight them visually.",
	"q2": "Success means: (1) Motion is correctly detected in test videos, (2) Bounding boxes appear around moving objects, (3) System runs at 15+ FPS",
	"q3": "Must use Python 3.10+, OpenCV for image processing. No external ML models - use classical CV techniques only.",
	"q4": "Out of scope: multiple camera support, GPU acceleration, machine learning models, audio processing",
	"q5": "Personal learning project, no external stakeholders",

	# Architecture phase
	"q6": "Fresh project, no existing code to interact with",
	"q7": "Python with OpenCV (cv2), numpy for array operations. Standard library for everything else.",
	"q8": "Must process video at minimum 15 FPS, ideally 30 FPS. Latency under 100ms per frame.",
	"q9": "No security concerns - local video files only, no network access needed",
	"q10": "Graceful handling of: camera not found, video file not readable, invalid frame data",

	# Verification phase
	"q11": "Manual verification: run with sample video, visually confirm motion is detected correctly",
	"q12": "Unit tests for: background model initialization, frame differencing, contour detection, bounding box calculation",
	"q13": "Integration test: process sample video file end-to-end, verify output video has annotations",
	"q14": "Acceptance criteria: motion detected within 0.5 seconds of appearing, false positive rate under 5%",
}


async def run_demo():
	"""
	Interactive demo showing orchestrator implementing motion detection.

	Steps:
	1. Show the goal and context
	2. Walk through planning Q&A (with pre-filled answers)
	3. Show plan generation and approval
	4. Delegate each task with visualization
	5. Monitor execution with live updates
	6. Run verification and show results
	7. Demonstrate the final project (if Claude CLI available)
	"""
	print_header()

	# Configuration
	project_name = "motion-detection"
	working_dir = Path.home() / "personal_projects" / "motion-detection-demo"

	# Check if Claude CLI is available
	use_mocks = not check_claude_cli()

	if use_mocks:
		print("\n[NOTE] Claude CLI not found - running in mock mode")
		print("       The demo will simulate task execution\n")
	else:
		print("\n[NOTE] Claude CLI found - running with real execution")
		print("       Each task will be executed by Claude Code\n")

	# Create framework
	framework = OrchestrationTestFramework(
		project_name=project_name,
		working_dir=working_dir,
		use_mocks=use_mocks,
		verbose=True,
		cleanup_on_exit=False,  # Keep the project for inspection
	)

	# Register phase change callback for extra logging
	async def on_phase_change(phase: OrchestrationPhase):
		if phase == OrchestrationPhase.COMPLETE:
			print("\n" + "=" * 60)
			print("Demo complete! Check the project at:")
			print(f"  {working_dir}")
			print("=" * 60)

	framework.on_phase_change(on_phase_change)

	# Run the full orchestration
	project_goal = """
	Build a motion detection system using background subtraction techniques.

	The system should:
	1. Initialize a background model from first N frames
	2. Compare subsequent frames against the background
	3. Apply thresholding to detect significant changes
	4. Find contours around motion regions
	5. Draw bounding boxes on detected motion
	6. Display or save the annotated video

	Use OpenCV's BackgroundSubtractor or implement frame differencing manually.
	"""

	result = await framework.run_full_orchestration(
		project_goal=project_goal.strip(),
		planning_answers=MOTION_DETECTION_ANSWERS,
	)

	# Show final result
	print("\n" + "=" * 60)
	print("DEMO RESULT SUMMARY")
	print("=" * 60)
	print(f"  Success: {result.success}")
	print(f"  Project Path: {result.project_path}")
	print(f"  Plan ID: {result.plan_id}")
	print(f"  Tasks: {result.tasks_completed}/{result.tasks_total}")
	print(f"  Verification: {'PASSED' if result.verification_passed else 'FAILED'}")
	print(f"  Duration: {result.duration_seconds:.1f}s")

	if result.error:
		print(f"  Error: {result.error}")

	# If successful and not mocked, try to run the project
	if result.success and not use_mocks:
		print("\nAttempting to run the implemented project...")
		try:
			await run_motion_detection_demo(working_dir)
		except Exception as e:
			print(f"Could not run demo: {e}")

	return result


def print_header():
	"""Print demo header."""
	print()
	print("=" * 60)
	print("  ORCHESTRATION DEMO: Motion Detection Project")
	print("=" * 60)
	print()
	print("This demo shows the claude-orchestrator implementing a real")
	print("computer vision project from scratch.")
	print()
	print("Project: Motion Detection using Background Subtraction")
	print("Technology: Python, OpenCV, NumPy")
	print()
	print("The orchestrator will:")
	print("  1. Plan the implementation through Q&A")
	print("  2. Generate a phased implementation plan")
	print("  3. Delegate tasks to subagents")
	print("  4. Supervise execution with checkpoints")
	print("  5. Verify the implementation")
	print()


def check_claude_cli() -> bool:
	"""Check if Claude CLI is available."""
	try:
		result = subprocess.run(
			["claude", "--version"],
			capture_output=True,
			text=True,
			timeout=5,
		)
		return result.returncode == 0
	except (FileNotFoundError, subprocess.TimeoutExpired):
		return False


async def run_motion_detection_demo(project_dir: Path):
	"""Run the implemented motion detection project."""
	# Check if main.py exists
	main_file = project_dir / "src" / "main.py"
	if not main_file.exists():
		main_file = project_dir / "main.py"

	if not main_file.exists():
		print("No main.py found to run")
		return

	# Check for sample video
	sample_video = project_dir / "data" / "sample.mp4"
	if not sample_video.exists():
		sample_video = project_dir / "sample.mp4"

	cmd = ["python", str(main_file)]
	if sample_video.exists():
		cmd.append(str(sample_video))

	print(f"Running: {' '.join(cmd)}")

	process = await asyncio.create_subprocess_exec(
		*cmd,
		cwd=str(project_dir),
	)
	await process.wait()


async def run_quick_demo():
	"""Run a quick demo with mocked execution for testing."""
	print_header()
	print("[QUICK MODE] Running with mocked execution\n")

	import tempfile
	working_dir = Path(tempfile.mkdtemp()) / "motion-detection-quick"

	framework = OrchestrationTestFramework(
		project_name="motion-detection",
		working_dir=working_dir,
		use_mocks=True,
		verbose=True,
		cleanup_on_exit=True,
	)

	# Use subset of answers for quick demo
	quick_answers = {
		"q1": "Detect motion using background subtraction",
		"q2": "Motion detected and highlighted",
		"q3": "Python, OpenCV",
		"q4": "No GPU, no ML",
		"q5": "Personal project",
	}

	result = await framework.run_full_orchestration(
		project_goal="Build motion detection with background subtraction",
		planning_answers=quick_answers,
	)

	return result


def main():
	"""Entry point."""
	import argparse

	parser = argparse.ArgumentParser(description="Orchestration Demo")
	parser.add_argument(
		"--quick",
		action="store_true",
		help="Run quick demo with mocked execution",
	)
	parser.add_argument(
		"--mock",
		action="store_true",
		help="Force mocked execution even if Claude CLI available",
	)

	args = parser.parse_args()

	if args.quick:
		result = asyncio.run(run_quick_demo())
	else:
		result = asyncio.run(run_demo())

	sys.exit(0 if result.success else 1)


if __name__ == "__main__":
	main()
