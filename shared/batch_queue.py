#!/usr/bin/env python3
"""
batch_queue.py
--------------
Batch processing queue with persistence and resume capability.

Features:
- Queue management for batch processing
- Persistence to disk for resume capability
- Status tracking (pending, processing, complete, failed, skipped)
- Statistics and progress reporting
"""

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Literal, Dict, Any
from enum import Enum


class QueueStatus(str, Enum):
    """Status values for queue items."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class QueueItem:
    """Single item in batch processing queue."""

    path: str  # Store as string for JSON serialization
    status: str = QueueStatus.PENDING
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
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'QueueItem':
        """Create from dictionary."""
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

    def get_next(self) -> Optional[QueueItem]:
        """
        Get next unprocessed item from queue.

        Returns:
            Next pending item, or None if queue is complete
        """
        for item in self.items:
            if item.status == QueueStatus.PENDING:
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
        pending = sum(1 for item in self.items if item.status == QueueStatus.PENDING)
        processing = sum(1 for item in self.items if item.status == QueueStatus.PROCESSING)
        complete = sum(1 for item in self.items if item.status == QueueStatus.COMPLETE)
        failed = sum(1 for item in self.items if item.status == QueueStatus.FAILED)
        skipped = sum(1 for item in self.items if item.status == QueueStatus.SKIPPED)

        return {
            'total': total,
            'pending': pending,
            'processing': processing,
            'complete': complete,
            'failed': failed,
            'skipped': skipped,
            'finished': complete + failed + skipped,
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
        """Check if all items are processed."""
        return all(item.status != QueueStatus.PENDING for item in self.items)

    def reset_processing_items(self) -> None:
        """
        Reset items stuck in 'processing' state to 'pending'.

        Useful for resuming after a crash.
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
