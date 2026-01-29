"""
Structured output schemas for Claude CLI responses.

Defines response schemas that can be used to request and validate
structured JSON output from Claude CLI sessions.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResponseSchema:
	"""A schema for structured output from Claude CLI."""

	name: str
	description: str
	json_schema: dict[str, Any] = field(default_factory=dict)

	def validate(self, response_str: str) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
		"""
		Parse and validate a response against this schema.

		Returns:
			Tuple of (is_valid, parsed_data, error_message)
		"""
		try:
			data = json.loads(response_str)
		except json.JSONDecodeError as e:
			return False, None, f"Invalid JSON: {e}"

		# Validate required top-level keys
		required = self.json_schema.get("required", [])
		properties = self.json_schema.get("properties", {})

		for key in required:
			if key not in data:
				return False, data, f"Missing required key: {key}"

		# Validate property types (best-effort)
		for key, prop_schema in properties.items():
			if key in data:
				expected_type = prop_schema.get("type")
				if expected_type and not _check_type(data[key], expected_type):
					return False, data, f"Key '{key}' expected type '{expected_type}', got '{type(data[key]).__name__}'"

		return True, data, None


def _check_type(value: Any, expected: str) -> bool:
	"""Check if a value matches the expected JSON schema type."""
	type_map = {
		"string": str,
		"number": (int, float),
		"integer": int,
		"boolean": bool,
		"array": list,
		"object": dict,
	}
	expected_type = type_map.get(expected)
	if expected_type is None:
		return True  # Unknown type, skip validation
	return isinstance(value, expected_type)


# Predefined schemas

CODE_REVIEW_SCHEMA = ResponseSchema(
	name="code_review",
	description="Structured code review result",
	json_schema={
		"type": "object",
		"required": ["summary", "issues", "suggestions"],
		"properties": {
			"summary": {"type": "string", "description": "Overall review summary"},
			"issues": {
				"type": "array",
				"description": "List of issues found",
				"items": {
					"type": "object",
					"properties": {
						"severity": {"type": "string", "enum": ["critical", "warning", "info"]},
						"file": {"type": "string"},
						"line": {"type": "integer"},
						"message": {"type": "string"},
					},
				},
			},
			"suggestions": {
				"type": "array",
				"description": "Improvement suggestions",
				"items": {"type": "string"},
			},
			"approved": {"type": "boolean", "description": "Whether the code is approved"},
		},
	},
)

TASK_RESULT_SCHEMA = ResponseSchema(
	name="task_result",
	description="Structured task execution result",
	json_schema={
		"type": "object",
		"required": ["status", "summary"],
		"properties": {
			"status": {"type": "string", "description": "completed, failed, or blocked"},
			"summary": {"type": "string", "description": "What was done"},
			"files_modified": {
				"type": "array",
				"description": "Files that were modified",
				"items": {"type": "string"},
			},
			"tests_passed": {"type": "boolean", "description": "Whether tests passed"},
			"errors": {
				"type": "array",
				"description": "Errors encountered",
				"items": {"type": "string"},
			},
		},
	},
)

PLAN_SCHEMA = ResponseSchema(
	name="plan",
	description="Structured implementation plan",
	json_schema={
		"type": "object",
		"required": ["goal", "phases"],
		"properties": {
			"goal": {"type": "string", "description": "What the plan achieves"},
			"phases": {
				"type": "array",
				"description": "Implementation phases",
				"items": {
					"type": "object",
					"properties": {
						"name": {"type": "string"},
						"description": {"type": "string"},
						"tasks": {"type": "array"},
					},
				},
			},
			"success_criteria": {
				"type": "array",
				"description": "How to verify success",
				"items": {"type": "string"},
			},
			"constraints": {
				"type": "array",
				"description": "Constraints and limitations",
				"items": {"type": "string"},
			},
		},
	},
)

_SCHEMAS: dict[str, ResponseSchema] = {
	"code_review": CODE_REVIEW_SCHEMA,
	"task_result": TASK_RESULT_SCHEMA,
	"plan": PLAN_SCHEMA,
}


def get_schema(name: str) -> Optional[ResponseSchema]:
	"""Get a predefined schema by name."""
	return _SCHEMAS.get(name)


def validate_response(
	response_str: str, schema: ResponseSchema,
) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
	"""
	Validate a response string against a schema.

	Returns:
		Tuple of (is_valid, parsed_data, error_message)
	"""
	return schema.validate(response_str)
