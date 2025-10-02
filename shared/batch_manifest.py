#!/usr/bin/env python3
"""
batch_manifest.py
-----------------
Batch processing manifest with resume capability.

Features:
- Batch-level tracking and metadata
- Resume from partial completion
- Summary statistics and reporting
- Integration with BatchQueue for persistence
"""

import json
import uuid
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_queue import BatchQueue, QueueItem


class BatchManifest:
    """Tracks batch processing progress with resume capability."""

    def __init__(self, batch_id: str, output_dir: Path):
        """
        Initialize batch manifest.

        Args:
            batch_id: Unique identifier for this batch
            output_dir: Directory for output files and manifest
        """
        self.batch_id = batch_id
        self.output_dir = Path(output_dir)
        self.manifest_path = self.output_dir / f"batch_{batch_id}_manifest.json"
        self.queue = BatchQueue(manifest_path=self.manifest_path)
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.metadata: Dict[str, Any] = {}

    def add_files(self, files: List[Path]) -> None:
        """
        Add files to batch.

        Args:
            files: List of file paths to process
        """
        self.queue.add_files(files)
        self.save()

    def start(self) -> None:
        """Mark batch as started."""
        self.start_time = datetime.now()
        self.save()

    def finish(self) -> None:
        """Mark batch as finished."""
        self.end_time = datetime.now()
        self.save()

    def save(self) -> None:
        """Save manifest to disk."""
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Build manifest data
        data = {
            'version': '1.0',
            'batch_id': self.batch_id,
            'output_dir': str(self.output_dir),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'metadata': self.metadata,
            'queue': {
                'items': [item.to_dict() for item in self.queue.items]
            }
        }

        # Write atomically
        temp_path = self.manifest_path.with_suffix('.tmp')
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        temp_path.replace(self.manifest_path)

    @classmethod
    def load(cls, manifest_path: Path) -> 'BatchManifest':
        """
        Resume from existing manifest.

        Args:
            manifest_path: Path to manifest file

        Returns:
            Loaded BatchManifest instance
        """
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, 'r') as f:
            data = json.load(f)

        batch_id = data.get('batch_id')
        output_dir = Path(data.get('output_dir', manifest_path.parent))

        manifest = cls(batch_id=batch_id, output_dir=output_dir)

        # Load timestamps
        if data.get('start_time'):
            manifest.start_time = datetime.fromisoformat(data['start_time'])
        if data.get('end_time'):
            manifest.end_time = datetime.fromisoformat(data['end_time'])

        # Load metadata
        manifest.metadata = data.get('metadata', {})

        # Load queue items
        queue_data = data.get('queue', {})
        manifest.queue.items = [
            QueueItem.from_dict(item_data)
            for item_data in queue_data.get('items', [])
        ]

        # Reset any items stuck in 'processing' state
        manifest.queue.reset_processing_items()

        return manifest

    @classmethod
    def create_new(cls, output_dir: Path, files: Optional[List[Path]] = None) -> 'BatchManifest':
        """
        Create new batch manifest with auto-generated ID.

        Args:
            output_dir: Directory for output files and manifest
            files: Optional list of files to add immediately

        Returns:
            New BatchManifest instance
        """
        # Generate batch ID: batch_YYYYMMDD_HHMMSS_<short-uuid>
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        batch_id = f"{timestamp}_{short_uuid}"

        manifest = cls(batch_id=batch_id, output_dir=output_dir)

        if files:
            manifest.add_files(files)

        return manifest

    def get_summary(self) -> Dict[str, Any]:
        """
        Get batch processing summary.

        Returns:
            Dictionary with batch summary and statistics
        """
        stats = self.queue.get_stats()

        # Calculate duration
        duration_seconds = None
        if self.start_time and self.end_time:
            duration_seconds = (self.end_time - self.start_time).total_seconds()
        elif self.start_time:
            duration_seconds = (datetime.now() - self.start_time).total_seconds()

        summary = {
            'batch_id': self.batch_id,
            'output_dir': str(self.output_dir),
            'manifest_path': str(self.manifest_path),
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': duration_seconds,
            'is_complete': self.queue.is_complete(),
            'statistics': stats,
            'metadata': self.metadata
        }

        return summary

    def get_failed_files(self) -> List[QueueItem]:
        """Get list of failed files."""
        return self.queue.get_failed_items()

    def get_pending_files(self) -> List[QueueItem]:
        """Get list of pending files."""
        return self.queue.get_pending_items()

    def get_complete_files(self) -> List[QueueItem]:
        """Get list of completed files."""
        return self.queue.get_complete_items()

    def should_stop_on_error(self, threshold: float = 0.5) -> bool:
        """
        Check if error rate exceeds threshold.

        Args:
            threshold: Failure rate threshold (0.0 to 1.0)

        Returns:
            True if failure rate exceeds threshold
        """
        stats = self.queue.get_stats()
        if stats['total'] == 0:
            return False

        failure_rate = stats['failure_rate'] / 100.0
        return failure_rate > threshold

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata to manifest.

        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value
        self.save()

    def __repr__(self) -> str:
        """String representation."""
        return f"BatchManifest(batch_id={self.batch_id}, items={len(self.queue)})"
