#!/usr/bin/env python3
"""
batch_queue.py
--------------
Batch processing queue with persistence and resume capability.

Batch completion criteria: see docs/batch_completion_criteria.md.

Features:
- Queue management for batch processing
- Persistence to disk for resume capability
- Status tracking (PENDING, PROCESSING, COMPLETE, FAILED, SKIPPED, DEGRADED, TIMED_OUT, LOCKED)
- Statistics and progress reporting
"""

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from enum import Enum


class QueueStatus(str, Enum):
    """Status values for queue items. See docs/batch_completion_criteria.md."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"
    TIMED_OUT = "timed_out"
    LOCKED = "locked"


# Statuses that mean "no further processing on resume" (skip if fingerprint matches)
DONE_STATUSES = (
    QueueStatus.COMPLETE,
    QueueStatus.DEGRADED,
    QueueStatus.FAILED,
    QueueStatus.SKIPPED,
)


@dataclass
class QueueItem:
    """Single item in batch processing queue. status is QueueStatus (normalized on load)."""

    path: str  # Store as string for JSON serialization
    status: Union[str, QueueStatus] = QueueStatus.PENDING
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    skip_reason: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

    @property
    def path_obj(self) -> Path:
        """Get path as Path object."""
        return Path(self.path)

    def mark_started(self) -> None:
        """Mark item as started processing."""
        self.status = QueueStatus.PROCESSING
        self.started_at = datetime.now().isoformat()

    def mark_complete(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark item as successfully completed."""
        self.status = QueueStatus.COMPLETE
        self.completed_at = datetime.now().isoformat()
        self.result = result or {}

    def mark_failed(self, error: str) -> None:
        """Mark item as failed with error message."""
        self.status = QueueStatus.FAILED
        self.completed_at = datetime.now().isoformat()
        self.error = error

    def mark_skipped(self, reason: str) -> None:
        """Mark item as skipped with reason."""
        self.status = QueueStatus.SKIPPED
        self.completed_at = datetime.now().isoformat()
        self.skip_reason = reason

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization (status as string value)."""
        d = asdict(self)
        if "status" in d and hasattr(d["status"], "value"):
            d["status"] = d["status"].value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueItem':
        """Create from dictionary. Normalizes status from string to QueueStatus."""
        data = dict(data)
        status = data.get("status", QueueStatus.PENDING)
        if isinstance(status, str):
            try:
                data["status"] = QueueStatus(status)
            except ValueError:
                data["status"] = QueueStatus.PENDING
        return cls(**data)


class BatchQueue:
    """Manages batch processing queue with persistence and resume capability."""

    def __init__(self, manifest_path: Optional[Path] = None):
        """
        Initialize batch queue.

        Args:
            manifest_path: Path to save/load queue state (optional)
        """
        self.manifest_path = manifest_path
        self.items: List[QueueItem] = []

    def add_files(self, files: List[Path]) -> None:
        """
        Add files to processing queue.

        Args:
            files: List of file paths to add
        """
        for file_path in files:
            # Check if already in queue
            if not any(item.path == str(file_path) for item in self.items):
                self.items.append(QueueItem(path=str(file_path)))

    def find_item(self, path: Path) -> Optional[QueueItem]:
        """Return queue item for path, or None."""
        path_str = str(path)
        for item in self.items:
            if item.path == path_str or (hasattr(item.path_obj, 'resolve') and str(item.path_obj.resolve()) == str(Path(path_str).resolve())):
                return item
        return None

    def get_next(self) -> Optional[QueueItem]:
        """
        Get next item to process (PENDING, or retryable TIMED_OUT/LOCKED).

        Returns:
            Next item to process, or None if none left
        """
        retryable = (QueueStatus.PENDING, QueueStatus.TIMED_OUT, QueueStatus.LOCKED)
        for item in self.items:
            if item.status in retryable:
                return item
        return None

    def mark_complete(self, item: QueueItem, result: Optional[Dict[str, Any]] = None) -> None:
        """
        Mark item as successfully processed.

        Args:
            item: Queue item to mark complete
            result: Optional processing result data
        """
        item.mark_complete(result)
        if self.manifest_path:
            self.save()

    def mark_failed(self, item: QueueItem, error: str) -> None:
        """
        Mark item as failed with error message.

        Args:
            item: Queue item to mark failed
            error: Error message
        """
        item.mark_failed(error)
        if self.manifest_path:
            self.save()

    def mark_skipped(self, item: QueueItem, reason: str) -> None:
        """
        Mark item as skipped (e.g., locked file, already processed).

        Args:
            item: Queue item to mark skipped
            reason: Reason for skipping
        """
        item.mark_skipped(reason)
        if self.manifest_path:
            self.save()

    def mark_degraded(self, item: QueueItem, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark item as DEGRADED (placeholder-only run)."""
        item.status = QueueStatus.DEGRADED
        item.completed_at = datetime.now().isoformat()
        item.result = result or {}
        if self.manifest_path:
            self.save()

    def mark_timed_out(self, item: QueueItem, error: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark item as TIMED_OUT."""
        item.status = QueueStatus.TIMED_OUT
        item.completed_at = datetime.now().isoformat()
        item.error = error
        item.result = result or {}
        if self.manifest_path:
            self.save()

    def mark_locked(self, item: QueueItem, reason: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark item as LOCKED (reliable lock check before run)."""
        item.status = QueueStatus.LOCKED
        item.completed_at = datetime.now().isoformat()
        item.skip_reason = reason
        item.result = result or {}
        if self.manifest_path:
            self.save()

    def save(self) -> None:
        """Persist queue state to disk."""
        if not self.manifest_path:
            return

        data = {
            'version': '1.0',
            'items': [item.to_dict() for item in self.items]
        }

        # Ensure parent directory exists
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically
        temp_path = self.manifest_path.with_suffix('.tmp')
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(self.manifest_path)

    @classmethod
    def load(cls, manifest_path: Path) -> 'BatchQueue':
        """
        Load existing queue from disk.

        Args:
            manifest_path: Path to manifest file

        Returns:
            Loaded BatchQueue instance
        """
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, 'r') as f:
            data = json.load(f)

        queue = cls(manifest_path=manifest_path)
        queue.items = [QueueItem.from_dict(item_data) for item_data in data.get('items', [])]
        return queue

    def get_stats(self) -> Dict[str, Any]:
        """
        Return processing statistics.

        Returns:
            Dictionary with queue statistics
        """
        total = len(self.items)
        pending = sum(1 for i in self.items if i.status == QueueStatus.PENDING)
        processing = sum(1 for i in self.items if i.status == QueueStatus.PROCESSING)
        complete = sum(1 for i in self.items if i.status == QueueStatus.COMPLETE)
        failed = sum(1 for i in self.items if i.status == QueueStatus.FAILED)
        skipped = sum(1 for i in self.items if i.status == QueueStatus.SKIPPED)
        degraded = sum(1 for i in self.items if i.status == QueueStatus.DEGRADED)
        timed_out = sum(1 for i in self.items if i.status == QueueStatus.TIMED_OUT)
        locked = sum(1 for i in self.items if i.status == QueueStatus.LOCKED)
        finished = complete + failed + skipped + degraded + timed_out + locked

        return {
            'total': total,
            'pending': pending,
            'processing': processing,
            'complete': complete,
            'failed': failed,
            'skipped': skipped,
            'degraded': degraded,
            'timed_out': timed_out,
            'locked': locked,
            'finished': finished,
            'success_rate': (complete / total * 100) if total > 0 else 0.0,
            'failure_rate': (failed / total * 100) if total > 0 else 0.0
        }

    def get_pending_items(self) -> List[QueueItem]:
        """Get list of pending items."""
        return [item for item in self.items if item.status == QueueStatus.PENDING]

    def get_failed_items(self) -> List[QueueItem]:
        """Get list of failed items."""
        return [item for item in self.items if item.status == QueueStatus.FAILED]

    def get_complete_items(self) -> List[QueueItem]:
        """Get list of completed items."""
        return [item for item in self.items if item.status == QueueStatus.COMPLETE]

    def is_complete(self) -> bool:
        """Check if no items are PENDING or PROCESSING (all decided)."""
        return not any(
            item.status == QueueStatus.PENDING or item.status == QueueStatus.PROCESSING
            for item in self.items
        )

    def reset_processing_items(self) -> None:
        """
        Reset items stuck in PROCESSING state to PENDING (crash recovery).
        """
        for item in self.items:
            if item.status == QueueStatus.PROCESSING:
                item.status = QueueStatus.PENDING
                item.started_at = None
        if self.manifest_path:
            self.save()

    def __len__(self) -> int:
        """Return number of items in queue."""
        return len(self.items)

    def __iter__(self):
        """Allow iteration over queue items."""
        return iter(self.items)
