"""Tests for structured output schemas."""

import json

from claude_orchestrator.schemas import (
	ResponseSchema,
	CODE_REVIEW_SCHEMA,
	TASK_RESULT_SCHEMA,
	PLAN_SCHEMA,
	get_schema,
	validate_response,
)


class TestResponseSchema:
	"""Tests for ResponseSchema validation."""

	def test_validate_valid_json(self):
		"""Valid JSON matching schema should pass."""
		schema = ResponseSchema(
			name="test",
			description="test",
			json_schema={
				"type": "object",
				"required": ["name"],
				"properties": {
					"name": {"type": "string"},
				},
			},
		)
		is_valid, data, error = schema.validate('{"name": "hello"}')
		assert is_valid is True
		assert data == {"name": "hello"}
		assert error is None

	def test_validate_invalid_json(self):
		"""Invalid JSON should fail."""
		schema = ResponseSchema(name="test", description="test")
		is_valid, data, error = schema.validate("not json")
		assert is_valid is False
		assert data is None
		assert "Invalid JSON" in error

	def test_validate_missing_required_key(self):
		"""Missing required key should fail."""
		schema = ResponseSchema(
			name="test",
			description="test",
			json_schema={
				"type": "object",
				"required": ["name", "age"],
				"properties": {
					"name": {"type": "string"},
					"age": {"type": "integer"},
				},
			},
		)
		is_valid, data, error = schema.validate('{"name": "hello"}')
		assert is_valid is False
		assert "Missing required key: age" in error

	def test_validate_wrong_type(self):
		"""Wrong type for a property should fail."""
		schema = ResponseSchema(
			name="test",
			description="test",
			json_schema={
				"type": "object",
				"required": ["count"],
				"properties": {
					"count": {"type": "integer"},
				},
			},
		)
		is_valid, data, error = schema.validate('{"count": "not a number"}')
		assert is_valid is False
		assert "expected type 'integer'" in error

	def test_validate_correct_types(self):
		"""Correct types should pass validation."""
		schema = ResponseSchema(
			name="test",
			description="test",
			json_schema={
				"type": "object",
				"required": ["name", "count", "active", "items"],
				"properties": {
					"name": {"type": "string"},
					"count": {"type": "integer"},
					"active": {"type": "boolean"},
					"items": {"type": "array"},
				},
			},
		)
		data = json.dumps({"name": "x", "count": 5, "active": True, "items": [1, 2]})
		is_valid, parsed, error = schema.validate(data)
		assert is_valid is True
		assert error is None

	def test_validate_extra_keys_ok(self):
		"""Extra keys not in schema should not cause failure."""
		schema = ResponseSchema(
			name="test",
			description="test",
			json_schema={
				"type": "object",
				"required": ["name"],
				"properties": {
					"name": {"type": "string"},
				},
			},
		)
		is_valid, data, error = schema.validate('{"name": "x", "extra": 42}')
		assert is_valid is True

	def test_validate_empty_schema(self):
		"""Empty schema should pass any valid JSON."""
		schema = ResponseSchema(name="test", description="test")
		is_valid, data, error = schema.validate('{"anything": "goes"}')
		assert is_valid is True


class TestPredefinedSchemas:
	"""Tests for predefined schemas."""

	def test_code_review_schema_exists(self):
		"""CODE_REVIEW_SCHEMA should be properly defined."""
		assert CODE_REVIEW_SCHEMA.name == "code_review"
		assert "summary" in CODE_REVIEW_SCHEMA.json_schema["required"]
		assert "issues" in CODE_REVIEW_SCHEMA.json_schema["required"]

	def test_task_result_schema_exists(self):
		"""TASK_RESULT_SCHEMA should be properly defined."""
		assert TASK_RESULT_SCHEMA.name == "task_result"
		assert "status" in TASK_RESULT_SCHEMA.json_schema["required"]
		assert "summary" in TASK_RESULT_SCHEMA.json_schema["required"]

	def test_plan_schema_exists(self):
		"""PLAN_SCHEMA should be properly defined."""
		assert PLAN_SCHEMA.name == "plan"
		assert "goal" in PLAN_SCHEMA.json_schema["required"]
		assert "phases" in PLAN_SCHEMA.json_schema["required"]

	def test_get_schema_valid(self):
		"""get_schema should return predefined schemas."""
		assert get_schema("code_review") is CODE_REVIEW_SCHEMA
		assert get_schema("task_result") is TASK_RESULT_SCHEMA
		assert get_schema("plan") is PLAN_SCHEMA

	def test_get_schema_invalid(self):
		"""get_schema should return None for unknown names."""
		assert get_schema("nonexistent") is None


class TestValidateResponse:
	"""Tests for the validate_response helper function."""

	def test_validate_response_valid(self):
		"""validate_response should work with valid data."""
		data = json.dumps({"summary": "ok", "issues": [], "suggestions": []})
		is_valid, parsed, error = validate_response(data, CODE_REVIEW_SCHEMA)
		assert is_valid is True

	def test_validate_response_invalid(self):
		"""validate_response should detect missing keys."""
		data = json.dumps({"summary": "ok"})
		is_valid, parsed, error = validate_response(data, CODE_REVIEW_SCHEMA)
		assert is_valid is False

	def test_validate_task_result_valid(self):
		"""Task result schema should validate correctly."""
		data = json.dumps({
			"status": "completed",
			"summary": "All done",
			"files_modified": ["src/main.py"],
			"tests_passed": True,
		})
		is_valid, parsed, error = validate_response(data, TASK_RESULT_SCHEMA)
		assert is_valid is True
