#!/usr/bin/env python3
"""
Hairstyle Detector Demo - Uses orchestrator to build a hairstyle detection project.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.orchestration.framework import OrchestrationTestFramework


async def main():
	"""Run the hairstyle detector orchestration demo."""
	print("=" * 60)
	print("HAIRSTYLE DETECTOR - Orchestration Demo")
	print("=" * 60)
	print()
	print("This demo uses the orchestrator to plan and implement")
	print("a hairstyle detection system using computer vision.")
	print()

	# Pre-filled planning answers for hairstyle detection
	planning_answers = {
		"q1": "Detect and classify hairstyles from webcam/video feed",
		"q2": "Identify hairstyle type (short, long, curly, straight, bald, ponytail, etc.) and display label",
		"q3": "Python 3.10+, OpenCV for face/head detection, classify hairstyle region above face",
		"q4": "Not doing hair color detection or style recommendations, just classification",
		"q5": "Personal project for learning computer vision",
		"q6": "Can build on the existing face detection code in motion-detection-demo",
		"q7": "Python with OpenCV, use Haar cascades or DNN for face detection, then analyze hair region",
		"q8": "Real-time detection at 15+ FPS",
		"q9": "No sensitive data, local video only",
		"q10": "Handle cases where no face is detected gracefully",
		"q11": "Live demo shows detected hairstyle label above each face",
		"q12": "Unit tests for detection and classification functions",
		"q13": "Run with webcam, verify hairstyle labels appear correctly",
		"q14": "Hairstyle detected and labeled in real-time on video feed",
	}

	working_dir = Path.home() / "personal_projects" / "hairstyle-detector"

	framework = OrchestrationTestFramework(
		project_name="hairstyle-detector",
		working_dir=working_dir,
		use_mocks=False,
		verbose=True,
		cleanup_on_exit=False,
	)

	print(f"Project will be created at: {working_dir}")
	print()

	result = await framework.run_full_orchestration(
		project_goal="Build a hairstyle detection system that identifies and classifies hairstyles (short, long, curly, straight, bald, ponytail, etc.) from webcam video using computer vision",
		planning_answers=planning_answers,
	)

	print()
	print("=" * 60)
	print("Demo complete! Check the project at:")
	print(f"  {working_dir}")
	print("=" * 60)

	return result


if __name__ == "__main__":
	result = asyncio.run(main())
	sys.exit(0 if result.success else 1)
