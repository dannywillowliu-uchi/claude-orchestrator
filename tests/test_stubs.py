"""Tests for stub tools when optional extras are missing."""

import json

import pytest

from claude_orchestrator.tools.stubs import (
	EXTRAS_META,
	KNOWLEDGE_TOOL_NAMES,
	VISUAL_TOOL_NAMES,
	_make_stub_response,
)


class TestStubResponse:
	"""Test the JSON error responses from stub tools."""

	def test_visual_stub_response_format(self):
		"""Visual stub should return correct JSON with install instructions."""
		result = json.loads(_make_stub_response("take_screenshot", "visual"))
		assert result["error"] == "missing_dependency"
		assert result["tool"] == "take_screenshot"
		assert result["extra"] == "visual"
		assert "pip install claude-orchestrator[visual]" in result["install"]
		assert "message" in result

	def test_knowledge_stub_response_format(self):
		"""Knowledge stub should return correct JSON with install instructions."""
		result = json.loads(_make_stub_response("search_docs", "knowledge"))
		assert result["error"] == "missing_dependency"
		assert result["tool"] == "search_docs"
		assert result["extra"] == "knowledge"
		assert "pip install claude-orchestrator[knowledge]" in result["install"]

	@pytest.mark.parametrize("tool_name", VISUAL_TOOL_NAMES)
	def test_all_visual_tools_have_stubs(self, tool_name: str):
		"""Every visual tool name should produce a valid stub response."""
		result = json.loads(_make_stub_response(tool_name, "visual"))
		assert result["tool"] == tool_name

	@pytest.mark.parametrize("tool_name", KNOWLEDGE_TOOL_NAMES)
	def test_all_knowledge_tools_have_stubs(self, tool_name: str):
		"""Every knowledge tool name should produce a valid stub response."""
		result = json.loads(_make_stub_response(tool_name, "knowledge"))
		assert result["tool"] == tool_name


class TestExtrasMetadata:
	"""Test that extras metadata is complete and consistent."""

	def test_visual_meta_has_all_fields(self):
		meta = EXTRAS_META["visual"]
		assert "tools" in meta
		assert "install" in meta
		assert "description" in meta
		assert len(meta["tools"]) == 6

	def test_knowledge_meta_has_all_fields(self):
		meta = EXTRAS_META["knowledge"]
		assert "tools" in meta
		assert "install" in meta
		assert "description" in meta
		assert len(meta["tools"]) == 5

	def test_visual_tool_names_match_actual(self):
		"""Stub tool names should match the real visual tool names."""
		expected = {
			"take_screenshot", "take_element_screenshot", "verify_element",
			"get_page_content", "list_screenshots", "delete_screenshot",
		}
		assert set(VISUAL_TOOL_NAMES) == expected

	def test_knowledge_tool_names_match_actual(self):
		"""Stub tool names should match the real knowledge tool names."""
		expected = {
			"search_docs", "get_doc", "list_doc_sources",
			"index_docs", "crawl_and_index_docs",
		}
		assert set(KNOWLEDGE_TOOL_NAMES) == expected
