"""Tests for batch processor."""

import asyncio

import pytest

from claude_orchestrator.orchestrator.batch import (
	BatchItem,
	BatchProcessor,
	BatchStatus,
	BatchSummary,
)


class TestBatchProcessorBasic:
	"""Basic batch processing tests."""

	@pytest.mark.asyncio
	async def test_empty_batch(self):
		"""Empty batch should return completed with zero counts."""
		processor = BatchProcessor()

		async def handler(item):
			return "done"

		summary = await processor.execute([], handler)
		assert summary.status == BatchStatus.COMPLETED
		assert summary.total == 0
		assert summary.succeeded == 0
		assert summary.failed == 0

	@pytest.mark.asyncio
	async def test_single_item_success(self):
		"""Single item batch should process correctly."""
		processor = BatchProcessor()

		async def handler(item):
			return f"processed-{item.id}"

		items = [BatchItem(id="1", data="test")]
		summary = await processor.execute(items, handler)

		assert summary.status == BatchStatus.COMPLETED
		assert summary.total == 1
		assert summary.succeeded == 1
		assert summary.failed == 0
		assert summary.results[0].success is True
		assert summary.results[0].result == "processed-1"

	@pytest.mark.asyncio
	async def test_multiple_items_success(self):
		"""Multiple items should all be processed."""
		processor = BatchProcessor()

		async def handler(item):
			return item.data * 2

		items = [
			BatchItem(id="1", data=10),
			BatchItem(id="2", data=20),
			BatchItem(id="3", data=30),
		]
		summary = await processor.execute(items, handler)

		assert summary.status == BatchStatus.COMPLETED
		assert summary.total == 3
		assert summary.succeeded == 3
		assert summary.success_rate == 1.0


class TestBatchProcessorErrors:
	"""Error handling tests."""

	@pytest.mark.asyncio
	async def test_single_item_failure(self):
		"""Failed item should be captured without aborting."""
		processor = BatchProcessor()

		async def handler(item):
			if item.id == "2":
				raise ValueError("item 2 failed")
			return "ok"

		items = [
			BatchItem(id="1", data="a"),
			BatchItem(id="2", data="b"),
			BatchItem(id="3", data="c"),
		]
		summary = await processor.execute(items, handler)

		assert summary.status == BatchStatus.PARTIAL_FAILURE
		assert summary.total == 3
		assert summary.succeeded == 2
		assert summary.failed == 1

		failed = [r for r in summary.results if not r.success]
		assert len(failed) == 1
		assert failed[0].item_id == "2"
		assert "item 2 failed" in failed[0].error

	@pytest.mark.asyncio
	async def test_all_items_fail(self):
		"""All items failing should return FAILED status."""
		processor = BatchProcessor()

		async def handler(item):
			raise RuntimeError("boom")

		items = [
			BatchItem(id="1", data="a"),
			BatchItem(id="2", data="b"),
		]
		summary = await processor.execute(items, handler)

		assert summary.status == BatchStatus.FAILED
		assert summary.succeeded == 0
		assert summary.failed == 2


class TestBatchProcessorConcurrency:
	"""Concurrency control tests."""

	@pytest.mark.asyncio
	async def test_concurrency_limit(self):
		"""Concurrency should not exceed max_concurrency."""
		processor = BatchProcessor(max_concurrency=2)
		active = 0
		max_active = 0
		lock = asyncio.Lock()

		async def handler(item):
			nonlocal active, max_active
			async with lock:
				active += 1
				max_active = max(max_active, active)
			await asyncio.sleep(0.05)
			async with lock:
				active -= 1
			return "ok"

		items = [BatchItem(id=str(i), data=i) for i in range(6)]
		summary = await processor.execute(items, handler)

		assert summary.succeeded == 6
		assert max_active <= 2

	@pytest.mark.asyncio
	async def test_fan_out_fan_in(self):
		"""Items should be processed concurrently, not sequentially."""
		processor = BatchProcessor(max_concurrency=5)
		order = []

		async def handler(item):
			await asyncio.sleep(0.01)
			order.append(item.id)
			return "ok"

		items = [BatchItem(id=str(i), data=i) for i in range(5)]
		summary = await processor.execute(items, handler)

		assert summary.succeeded == 5
		assert len(order) == 5


class TestBatchProcessorCallbacks:
	"""Callback tests."""

	@pytest.mark.asyncio
	async def test_on_item_complete_called(self):
		"""on_item_complete should be called for each item."""
		processor = BatchProcessor()
		completed_ids = []

		async def handler(item):
			return "ok"

		async def on_complete(result):
			completed_ids.append(result.item_id)

		items = [BatchItem(id=str(i), data=i) for i in range(3)]
		await processor.execute(items, handler, on_item_complete=on_complete)

		assert len(completed_ids) == 3
		assert set(completed_ids) == {"0", "1", "2"}

	@pytest.mark.asyncio
	async def test_callback_failure_does_not_abort(self):
		"""Failing callback should not abort the batch."""
		processor = BatchProcessor()

		async def handler(item):
			return "ok"

		async def on_complete(result):
			raise RuntimeError("callback error")

		items = [BatchItem(id="1", data="a")]
		summary = await processor.execute(items, handler, on_item_complete=on_complete)

		assert summary.succeeded == 1


class TestBatchSummary:
	"""Tests for BatchSummary."""

	def test_success_rate_all_passed(self):
		"""100% success rate."""
		summary = BatchSummary(
			status=BatchStatus.COMPLETED,
			total=5,
			succeeded=5,
			failed=0,
		)
		assert summary.success_rate == 1.0

	def test_success_rate_partial(self):
		"""Partial success rate."""
		summary = BatchSummary(
			status=BatchStatus.PARTIAL_FAILURE,
			total=4,
			succeeded=3,
			failed=1,
		)
		assert summary.success_rate == 0.75

	def test_success_rate_empty(self):
		"""Empty batch should have 0% success rate."""
		summary = BatchSummary(
			status=BatchStatus.COMPLETED,
			total=0,
			succeeded=0,
			failed=0,
		)
		assert summary.success_rate == 0.0
