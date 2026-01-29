"""
Batch Processor - Fan-out/fan-in execution of multiple items.

Processes a batch of items concurrently with configurable concurrency
limits. Each item is processed independently; individual failures
do not abort the batch.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class BatchStatus(str, Enum):
	"""Status of a batch operation."""
	PENDING = "pending"
	RUNNING = "running"
	COMPLETED = "completed"
	PARTIAL_FAILURE = "partial_failure"
	FAILED = "failed"


@dataclass
class BatchItem(Generic[T]):
	"""A single item in a batch."""
	id: str
	data: T
	priority: int = 0


@dataclass
class BatchResult(Generic[R]):
	"""Result of processing a single batch item."""
	item_id: str
	success: bool
	result: Optional[R] = None
	error: Optional[str] = None


@dataclass
class BatchSummary(Generic[R]):
	"""Summary of a completed batch operation."""
	status: BatchStatus
	total: int
	succeeded: int
	failed: int
	results: list[BatchResult[R]] = field(default_factory=list)

	@property
	def success_rate(self) -> float:
		"""Percentage of items that succeeded."""
		if self.total == 0:
			return 0.0
		return self.succeeded / self.total


class BatchProcessor(Generic[T, R]):
	"""
	Processes batches of items with concurrency control.

	Uses asyncio.Semaphore to limit concurrent processing.
	Individual item failures are captured without aborting the batch.
	"""

	def __init__(self, max_concurrency: int = 5):
		"""
		Initialize batch processor.

		Args:
			max_concurrency: Maximum number of items processed concurrently
		"""
		self.max_concurrency = max_concurrency

	async def execute(
		self,
		items: list[BatchItem[T]],
		handler: Callable[[BatchItem[T]], Awaitable[R]],
		on_item_complete: Optional[Callable[[BatchResult[R]], Awaitable[None]]] = None,
	) -> BatchSummary[R]:
		"""
		Execute a batch of items through the handler.

		Args:
			items: List of items to process
			handler: Async function to process each item
			on_item_complete: Optional callback after each item completes

		Returns:
			BatchSummary with results for all items
		"""
		if not items:
			return BatchSummary(
				status=BatchStatus.COMPLETED,
				total=0,
				succeeded=0,
				failed=0,
				results=[],
			)

		semaphore = asyncio.Semaphore(self.max_concurrency)
		results: list[BatchResult[R]] = []
		results_lock = asyncio.Lock()

		async def process_item(item: BatchItem[T]) -> None:
			async with semaphore:
				try:
					result_data = await handler(item)
					batch_result = BatchResult(
						item_id=item.id,
						success=True,
						result=result_data,
					)
				except Exception as e:
					logger.warning(f"Batch item {item.id} failed: {e}")
					batch_result = BatchResult(
						item_id=item.id,
						success=False,
						error=str(e),
					)

				async with results_lock:
					results.append(batch_result)

				if on_item_complete:
					try:
						await on_item_complete(batch_result)
					except Exception as e:
						logger.warning(f"on_item_complete callback failed for {item.id}: {e}")

		# Fan out
		tasks = [asyncio.create_task(process_item(item)) for item in items]
		await asyncio.gather(*tasks)

		# Fan in
		succeeded = sum(1 for r in results if r.success)
		failed = len(results) - succeeded

		if failed == 0:
			status = BatchStatus.COMPLETED
		elif succeeded == 0:
			status = BatchStatus.FAILED
		else:
			status = BatchStatus.PARTIAL_FAILURE

		return BatchSummary(
			status=status,
			total=len(items),
			succeeded=succeeded,
			failed=failed,
			results=results,
		)
