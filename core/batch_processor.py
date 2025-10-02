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
- Auto-generated output folders in Complete/
"""

import os
import sys
import time
import yaml
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.batch_queue import BatchQueue, QueueItem, QueueStatus
from shared.batch_manifest import BatchManifest
from shared.path_validator import sanitize_input_path, SecurityError

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

        # Load config for error thresholds and output settings
        self.stop_on_error_threshold = 0.5  # Default 50%
        self.progress_update_interval = 5  # Default every 5 files
        self.config = {}

        if config_path:
            try:
                with open(config_path) as f:
                    self.config = yaml.safe_load(f) or {}
                    batch_config = self.config.get('batch_processing', {})
                    self.stop_on_error_threshold = batch_config.get('stop_on_error_threshold', 0.5)
                    self.progress_update_interval = batch_config.get('progress_update_interval', 5)
            except Exception as e:
                logger.warning(f"Could not load config: {e}, using defaults")

    def _generate_output_path(self, input_path: Path) -> Path:
        """
        Generate timestamped output folder in Complete/.

        Args:
            input_path: Input directory or first file path

        Returns:
            Path to output folder (Complete/<name>_<timestamp>/)
        """
        # Get folder name from input
        if input_path.is_dir():
            folder_name = input_path.name
        else:
            # For file lists, use "batch" as folder name
            folder_name = "batch"

        # Generate timestamp
        timestamp_format = self.config.get('batch_processing', {}).get(
            'output_timestamp_format',
            '%Y%m%d_%H%M%S'
        )
        timestamp = datetime.now().strftime(timestamp_format)

        # Create output folder name
        output_folder_name = f"{folder_name}_{timestamp}"

        # Get project root and create Complete path
        project_root = Path(__file__).resolve().parents[1]
        complete_folder_name = self.config.get('batch_processing', {}).get(
            'complete_folder_name',
            'Complete'
        )
        complete_dir = project_root / complete_folder_name

        output_path = complete_dir / output_folder_name

        return output_path

    def _get_relative_output_path(
        self,
        input_file: Path,
        input_root: Path,
        output_root: Path
    ) -> Path:
        """
        Calculate output path preserving folder structure.

        Args:
            input_file: Individual file being processed
            input_root: Root input directory
            output_root: Root output directory

        Returns:
            Output path with preserved structure
        """
        try:
            # Get relative path from input root
            relative_path = input_file.relative_to(input_root)
        except ValueError:
            # File is not relative to input_root, use just filename
            relative_path = Path(input_file.name)

        # Recreate in output root
        output_path = output_root / relative_path

        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        return output_path

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
            output_dir: Optional output directory (default: auto-generated in Complete/)
            resume: Resume from existing manifest
            batch_id: Optional batch ID for resume

        Returns:
            Dict with batch results and statistics
        """
        # Determine input_root for preserving structure
        input_root = None
        if resume and batch_id:
            # Load existing manifest to get output_dir and input_root
            manifest = self._load_manifest(batch_id, output_dir)
            output_dir = manifest.output_dir
            input_root = manifest.input_root
            logger.info(f"Resuming batch {manifest.batch_id}")
        else:
            # Determine input_root from input_files
            if input_files:
                if len(input_files) > 1:
                    # Find common parent directory
                    input_root = Path(os.path.commonpath([str(f.parent) for f in input_files]))
                else:
                    input_root = input_files[0].parent
            else:
                raise ValueError("No input files provided")

            # Determine output directory
            if output_dir is None:
                # Auto-generate output path
                input_reference = input_root
                output_dir = self._generate_output_path(input_reference)

        # Validate and setup output directory
        try:
            # Use sanitize_input_path with allow_absolute=True for Complete/ folder
            output_dir = sanitize_input_path(str(output_dir), allow_absolute=True)

            # Create parent directories if needed
            if not output_dir.exists():
                output_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created output directory: {output_dir}")

        except SecurityError as e:
            return {
                'success': False,
                'error': f"Security error with output directory: {e}",
                'statistics': {}
            }
        except OSError as e:
            return {
                'success': False,
                'error': f"Failed to create output directory: {e}",
                'statistics': {}
            }

        # Create manifest if not resuming
        if not resume:
            manifest = self._create_manifest(input_files, output_dir, input_root)
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
                self._process_single_file(item, manifest, output_dir, input_root)

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
        output_dir: Path,
        input_root: Path
    ) -> None:
        """
        Process a single file with error handling and structure preservation.

        Args:
            item: Queue item to process
            manifest: Batch manifest for tracking
            output_dir: Output root directory
            input_root: Input root directory (for preserving structure)
        """
        file_path = item.path_obj
        item.mark_started()
        manifest.save()

        try:
            # Validate input path (allow absolute paths for batch processing)
            try:
                validated_path = sanitize_input_path(str(file_path), allow_absolute=True)
            except SecurityError as e:
                manifest.queue.mark_failed(item, f"Security error: {e}")
                logger.error(f"Security error for {file_path.name}: {e}")
                return

            # Calculate output path preserving structure
            output_path = self._get_relative_output_path(
                file_path,
                input_root,
                output_dir
            )

            # Process file (subprocess handles its own locking)
            if self.dry_run:
                result = self._dry_run_validate(validated_path)
            else:
                result = self._process_file(validated_path, output_path.parent)

            # Mark complete/failed
            if result.get('success'):
                manifest.queue.mark_complete(item, result)
                logger.info(f"✅ Completed: {file_path.name}")
            else:
                error_msg = result.get('error', 'Unknown error')
                manifest.queue.mark_failed(item, error_msg)
                logger.error(f"❌ Failed: {file_path.name} - {error_msg}")

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

        # Build command with global flags BEFORE subcommand
        cmd = [
            sys.executable,
            str(self.processor_path)
        ]

        # Add global flags before subcommand
        if self.config_path:
            cmd.extend(['--config', self.config_path])

        # Now add subcommand and positional arguments
        cmd.extend([
            'process',
            str(file_path)
        ])

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

    def _create_manifest(self, files: List[Path], output_dir: Path, input_root: Path) -> BatchManifest:
        """Create new batch manifest."""
        manifest = BatchManifest.create_new(output_dir=output_dir, input_root=input_root, files=files)
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
