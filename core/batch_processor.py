#!/usr/bin/env python3
"""
batch_processor.py
------------------
Production-grade batch processor with queue management, resume capability, and robust error handling.

Features:
- Queue-based batch processing with persistence
- Resume from partial completion
- Dry-run mode for validation
- Graceful error handling (one failure doesn't stop batch)
- File locking integration
- Progress reporting
"""

import sys
import time
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.batch_queue import BatchQueue, QueueItem, QueueStatus
from shared.batch_manifest import BatchManifest
from shared.file_lock_manager import FileLock, LockError
from shared.path_validator import sanitize_input_path, validate_output_path, SecurityError

logger = logging.getLogger(__name__)


class PPTXBatchProcessor:
    """Production batch processor with queue management."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        dry_run: bool = False,
        max_workers: int = 1,
        max_lock_wait: float = 30.0,
        processor_path: Optional[str] = None
    ):
        """
        Initialize batch processor.

        Args:
            config_path: Path to config file
            dry_run: Validate files without processing
            max_workers: Max parallel workers (1=sequential, for Phase 2B.1)
            max_lock_wait: Max seconds to wait for file locks
            processor_path: Path to pptx_alt_processor.py (default: auto-detect)
        """
        self.config_path = config_path
        self.dry_run = dry_run
        self.max_workers = max_workers
        self.max_lock_wait = max_lock_wait

        # Locate processor
        if processor_path:
            self.processor_path = Path(processor_path)
        else:
            # Auto-detect processor path
            possible_paths = [
                Path(__file__).parent.parent / "pptx_alt_processor.py",
                Path(__file__).parent / "pptx_alt_processor.py"
            ]
            self.processor_path = None
            for p in possible_paths:
                if p.exists():
                    self.processor_path = p
                    break

            if not self.processor_path:
                raise FileNotFoundError("Could not locate pptx_alt_processor.py")

        # Load config for error thresholds
        self.stop_on_error_threshold = 0.5  # Default 50%
        self.progress_update_interval = 5  # Default every 5 files

        if config_path:
            try:
                import yaml
                with open(config_path) as f:
                    config = yaml.safe_load(f) or {}
                    batch_config = config.get('batch_processing', {})
                    self.stop_on_error_threshold = batch_config.get('stop_on_error_threshold', 0.5)
                    self.progress_update_interval = batch_config.get('progress_update_interval', 5)
            except Exception as e:
                logger.warning(f"Could not load config: {e}, using defaults")

    def process_batch(
        self,
        input_files: List[Path],
        output_dir: Optional[Path] = None,
        resume: bool = False,
        batch_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process multiple presentations in batch.

        Args:
            input_files: List of PPTX files to process
            output_dir: Directory for output files and manifest
            resume: Resume from existing manifest
            batch_id: Optional batch ID for resume

        Returns:
            Dict with batch results and statistics
        """
        # Validate and setup output directory
        if output_dir is None:
            output_dir = Path.cwd() / "batch_output"

        try:
            output_dir = validate_output_path(str(output_dir), create_parents=True)
        except SecurityError as e:
            return {
                'success': False,
                'error': f"Security error with output directory: {e}",
                'statistics': {}
            }

        # Create or load manifest
        if resume:
            manifest = self._load_manifest(batch_id, output_dir)
            logger.info(f"Resuming batch {manifest.batch_id}")
        else:
            manifest = self._create_manifest(input_files, output_dir)
            logger.info(f"Starting new batch {manifest.batch_id}")

        manifest.start()

        try:
            # Process files sequentially (max_workers=1 for Phase 2B.1)
            files_processed = 0
            start_time = time.time()

            while True:
                # Get next item
                item = manifest.queue.get_next()
                if item is None:
                    break  # All done

                # Check error threshold
                if manifest.should_stop_on_error(self.stop_on_error_threshold):
                    stats = manifest.queue.get_stats()
                    logger.error(
                        f"Stopping batch: failure rate {stats['failure_rate']:.1f}% "
                        f"exceeds threshold {self.stop_on_error_threshold * 100:.1f}%"
                    )
                    break

                # Process single file
                self._process_single_file(item, manifest, output_dir)

                # Progress reporting
                files_processed += 1
                if files_processed % self.progress_update_interval == 0:
                    self._print_progress(manifest, start_time)

            # Final progress
            self._print_progress(manifest, start_time)

            manifest.finish()

            # Return summary
            summary = manifest.get_summary()
            summary['success'] = True

            return summary

        except KeyboardInterrupt:
            logger.warning("Batch processing interrupted by user")
            manifest.save()
            summary = manifest.get_summary()
            summary['success'] = False
            summary['error'] = "Interrupted by user"
            return summary

        except Exception as e:
            logger.error(f"Batch processing failed: {e}", exc_info=True)
            manifest.save()
            summary = manifest.get_summary()
            summary['success'] = False
            summary['error'] = str(e)
            return summary

    def _process_single_file(
        self,
        item: QueueItem,
        manifest: BatchManifest,
        output_dir: Path
    ) -> None:
        """
        Process a single file with error handling.

        Args:
            item: Queue item to process
            manifest: Batch manifest for tracking
            output_dir: Output directory
        """
        file_path = item.path_obj
        item.mark_started()
        manifest.save()

        try:
            # Validate input path
            try:
                validated_path = sanitize_input_path(str(file_path))
            except SecurityError as e:
                manifest.queue.mark_failed(item, f"Security error: {e}")
                logger.error(f"Security error for {file_path.name}: {e}")
                return

            # Try to acquire lock
            try:
                lock = FileLock(validated_path, timeout=self.max_lock_wait)
                lock.acquire(blocking=True)
            except LockError as e:
                manifest.queue.mark_skipped(item, f"File locked: {e}")
                logger.warning(f"Skipping locked file: {file_path.name}")
                return

            try:
                # Process file
                if self.dry_run:
                    result = self._dry_run_validate(validated_path)
                else:
                    result = self._process_file(validated_path, output_dir)

                # Mark complete
                if result.get('success'):
                    manifest.queue.mark_complete(item, result)
                    logger.info(f"✅ Completed: {file_path.name}")
                else:
                    error_msg = result.get('error', 'Unknown error')
                    manifest.queue.mark_failed(item, error_msg)
                    logger.error(f"❌ Failed: {file_path.name} - {error_msg}")

            finally:
                lock.release()

        except Exception as e:
            manifest.queue.mark_failed(item, str(e))
            logger.error(f"❌ Error processing {file_path.name}: {e}", exc_info=True)

    def _dry_run_validate(self, file_path: Path) -> Dict[str, Any]:
        """
        Validate file without processing (dry-run mode).

        Args:
            file_path: Path to file

        Returns:
            Validation result
        """
        # Check file exists and is readable
        if not file_path.exists():
            return {'success': False, 'error': 'File not found'}

        if not file_path.is_file():
            return {'success': False, 'error': 'Not a file'}

        if file_path.suffix.lower() != '.pptx':
            return {'success': False, 'error': 'Not a PPTX file'}

        # Check file is readable
        try:
            with open(file_path, 'rb') as f:
                # Read first few bytes to verify it's a valid ZIP (PPTX is ZIP-based)
                magic = f.read(4)
                if magic != b'PK\x03\x04':
                    return {'success': False, 'error': 'Invalid PPTX file (not a ZIP archive)'}
        except Exception as e:
            return {'success': False, 'error': f'Cannot read file: {e}'}

        return {
            'success': True,
            'dry_run': True,
            'file_size': file_path.stat().st_size,
            'validated_at': datetime.now().isoformat()
        }

    def _process_file(self, file_path: Path, output_dir: Path) -> Dict[str, Any]:
        """
        Process file using pptx_alt_processor.py.

        Args:
            file_path: Path to input file
            output_dir: Output directory

        Returns:
            Processing result
        """
        import subprocess

        # Build command
        cmd = [
            sys.executable,
            str(self.processor_path),
            'process',
            str(file_path)
        ]

        if self.config_path:
            cmd.extend(['--config', self.config_path])

        # Execute processor
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout per file
            )

            if result.returncode == 0:
                return {
                    'success': True,
                    'output': result.stdout,
                    'processed_at': datetime.now().isoformat()
                }
            else:
                return {
                    'success': False,
                    'error': result.stderr or 'Processing failed',
                    'return_code': result.returncode
                }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'Processing timeout (5 minutes)'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Subprocess error: {e}'
            }

    def _create_manifest(self, files: List[Path], output_dir: Path) -> BatchManifest:
        """Create new batch manifest."""
        manifest = BatchManifest.create_new(output_dir=output_dir, files=files)
        manifest.add_metadata('processor', str(self.processor_path))
        manifest.add_metadata('dry_run', self.dry_run)
        manifest.add_metadata('max_workers', self.max_workers)
        return manifest

    def _load_manifest(self, batch_id: Optional[str], output_dir: Path) -> BatchManifest:
        """Load existing manifest for resume."""
        if batch_id:
            manifest_path = output_dir / f"batch_{batch_id}_manifest.json"
        else:
            # Find most recent manifest
            manifests = sorted(
                output_dir.glob("batch_*_manifest.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            if not manifests:
                raise FileNotFoundError(f"No batch manifests found in {output_dir}")
            manifest_path = manifests[0]

        return BatchManifest.load(manifest_path)

    def _print_progress(self, manifest: BatchManifest, start_time: float) -> None:
        """Print progress update."""
        stats = manifest.queue.get_stats()
        elapsed = time.time() - start_time

        # Calculate ETA
        if stats['finished'] > 0:
            avg_time = elapsed / stats['finished']
            eta = avg_time * stats['pending']
        else:
            eta = 0

        print(
            f"\rProgress: {stats['finished']}/{stats['total']} "
            f"({stats['complete']} ✅, {stats['failed']} ❌, {stats['skipped']} ⏭️) "
            f"| Elapsed: {elapsed:.0f}s | ETA: {eta:.0f}s",
            end='',
            flush=True
        )

        # Print newline when complete
        if manifest.queue.is_complete():
            print()
