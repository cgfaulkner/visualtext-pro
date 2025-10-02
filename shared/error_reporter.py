#!/usr/bin/env python3
"""
Standardized Error Reporting for VisualText Pro Processing
===================================================

Consistent error reporting and JSON output across all processors,
integrating with the unified exception hierarchy and providing
user-friendly error messages with actionable guidance.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
try:
    from .processing_exceptions import ProcessingError, log_structured_error
except ImportError:
    from processing_exceptions import ProcessingError, log_structured_error

logger = logging.getLogger(__name__)


class ProcessingResult:
    """
    Standardized result object for all processing operations.

    Provides consistent structure for success/failure reporting,
    metrics tracking, and error details across all processors.
    """

    def __init__(self,
                 operation: str,
                 input_file: Union[str, Path],
                 output_file: Optional[Union[str, Path]] = None):
        """
        Initialize processing result.

        Args:
            operation: Type of operation (e.g., 'pptx_processing', 'docx_processing')
            input_file: Input file path
            output_file: Output file path (if different from input)
        """
        self.operation = operation
        self.input_file = str(input_file)
        self.output_file = str(output_file) if output_file else self.input_file
        self.start_time = time.time()

        # Core result data
        self.success = False
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.metrics: Dict[str, Any] = {}
        self.processing_details: Dict[str, Any] = {}

        # Timing
        self.processing_time: Optional[float] = None

    def add_error(self, error: Union[ProcessingError, Exception, str], **kwargs):
        """
        Add an error to the result.

        Args:
            error: Error object, exception, or error message
            **kwargs: Additional error context
        """
        if isinstance(error, ProcessingError):
            error_data = error.to_dict()
            error_data.update(kwargs)
            self.errors.append(error_data)
            log_structured_error(error, logger)
        elif isinstance(error, Exception):
            error_data = {
                'error_code': 'UNKNOWN_ERROR',
                'category': 'processing',
                'message': str(error),
                'recoverable': False,
                'timestamp': time.time(),
                'cause': type(error).__name__
            }
            error_data.update(kwargs)
            self.errors.append(error_data)
            logger.error(f"Unexpected error: {error}", exc_info=True)
        else:
            # String error message
            error_data = {
                'error_code': 'GENERIC_ERROR',
                'category': 'processing',
                'message': str(error),
                'recoverable': False,
                'timestamp': time.time()
            }
            error_data.update(kwargs)
            self.errors.append(error_data)
            logger.error(f"Error: {error}")

    def add_warning(self, message: str):
        """Add a warning message."""
        self.warnings.append(message)
        logger.warning(message)

    def set_metrics(self, metrics: Dict[str, Any]):
        """Set processing metrics."""
        self.metrics.update(metrics)

    def set_processing_details(self, details: Dict[str, Any]):
        """Set detailed processing information."""
        self.processing_details.update(details)

    def mark_success(self):
        """Mark the operation as successful."""
        self.success = True
        self.processing_time = time.time() - self.start_time

    def mark_failure(self, error: Union[ProcessingError, Exception, str] = None):
        """
        Mark the operation as failed.

        Args:
            error: Optional error to add before marking failure
        """
        if error:
            self.add_error(error)
        self.success = False
        self.processing_time = time.time() - self.start_time

    def get_error_summary(self) -> Dict[str, Any]:
        """Get a summary of errors for user display."""
        if not self.errors:
            return {}

        error_categories = {}
        recoverable_count = 0

        for error in self.errors:
            category = error.get('category', 'unknown')
            if category not in error_categories:
                error_categories[category] = []
            error_categories[category].append(error)

            if error.get('recoverable', False):
                recoverable_count += 1

        return {
            'total_errors': len(self.errors),
            'recoverable_errors': recoverable_count,
            'categories': error_categories,
            'has_recovery_hints': any(e.get('recovery_hint') for e in self.errors)
        }

    def get_user_friendly_summary(self) -> str:
        """Get user-friendly summary of the processing result."""
        if self.success:
            if self.warnings:
                return f"✅ {self.operation} completed successfully with {len(self.warnings)} warning(s)."
            else:
                return f"✅ {self.operation} completed successfully."

        error_summary = self.get_error_summary()
        total_errors = error_summary.get('total_errors', 0)
        recoverable = error_summary.get('recoverable_errors', 0)

        message = f"❌ {self.operation} failed with {total_errors} error(s)."

        if recoverable > 0:
            message += f" {recoverable} error(s) may be recoverable."

        if error_summary.get('has_recovery_hints'):
            message += " See error details for recovery suggestions."

        return message

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization."""
        result = {
            'operation': self.operation,
            'success': self.success,
            'input_file': self.input_file,
            'output_file': self.output_file,
            'processing_time': self.processing_time,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'errors': self.errors,
            'warnings': self.warnings,
            'metrics': self.metrics,
            'processing_details': self.processing_details
        }

        # Add error summary for convenience
        if self.errors:
            result['error_summary'] = self.get_error_summary()

        return result

    def to_json(self, indent: int = 2) -> str:
        """Convert result to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save_to_file(self, file_path: Union[str, Path]):
        """Save result to JSON file."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

        logger.info(f"Processing result saved to: {file_path}")


class StandardizedLogger:
    """
    Standardized logging formatter for consistent output across processors.
    """

    @staticmethod
    def log_processing_start(operation: str, input_file: Union[str, Path],
                           output_file: Optional[Union[str, Path]] = None):
        """Log the start of a processing operation."""
        logger.info(f"🚀 Starting {operation}")
        logger.info(f"   Input: {Path(input_file).name}")
        if output_file and str(output_file) != str(input_file):
            logger.info(f"   Output: {Path(output_file).name}")

    @staticmethod
    def log_processing_complete(result: ProcessingResult):
        """Log the completion of a processing operation."""
        if result.success:
            logger.info(f"✅ {result.operation} completed successfully")
            if result.processing_time:
                logger.info(f"   Processing time: {result.processing_time:.2f}s")

            # Log key metrics
            if result.metrics:
                StandardizedLogger._log_metrics(result.metrics)

            # Log warnings if any
            if result.warnings:
                logger.warning(f"   Warnings: {len(result.warnings)}")
                for warning in result.warnings[:3]:  # Show first 3
                    logger.warning(f"     - {warning}")
                if len(result.warnings) > 3:
                    logger.warning(f"     ... and {len(result.warnings) - 3} more")
        else:
            logger.error(f"❌ {result.operation} failed")
            if result.processing_time:
                logger.error(f"   Processing time: {result.processing_time:.2f}s")

            # Log error summary
            error_summary = result.get_error_summary()
            logger.error(f"   Total errors: {error_summary.get('total_errors', 0)}")

            # Show first few errors with recovery hints
            for error in result.errors[:3]:
                logger.error(f"   - [{error.get('error_code', 'UNKNOWN')}] {error.get('message', 'Unknown error')}")
                if error.get('recovery_hint'):
                    logger.info(f"     💡 {error['recovery_hint']}")

    @staticmethod
    def _log_metrics(metrics: Dict[str, Any]):
        """Log processing metrics in a standardized format."""
        logger.info("📊 Processing Metrics:")

        # Common metric patterns
        for key, value in metrics.items():
            if 'total' in key.lower() and isinstance(value, (int, float)):
                logger.info(f"   {key.replace('_', ' ').title()}: {value}")

        for key, value in metrics.items():
            if 'processed' in key.lower() and isinstance(value, (int, float)):
                logger.info(f"   {key.replace('_', ' ').title()}: {value}")

        for key, value in metrics.items():
            if 'coverage' in key.lower() and isinstance(value, (int, float)):
                logger.info(f"   {key.replace('_', ' ').title()}: {value:.1f}%")


def create_processing_result(operation: str,
                           input_file: Union[str, Path],
                           output_file: Optional[Union[str, Path]] = None) -> ProcessingResult:
    """
    Factory function to create a standardized processing result.

    Args:
        operation: Operation type
        input_file: Input file path
        output_file: Output file path

    Returns:
        ProcessingResult instance
    """
    return ProcessingResult(operation, input_file, output_file)


def handle_processing_exception(result: ProcessingResult,
                               exception: Exception,
                               context: str = "") -> ProcessingResult:
    """
    Handle an exception during processing and update the result appropriately.

    Args:
        result: ProcessingResult to update
        exception: Exception that occurred
        context: Additional context about where the exception occurred

    Returns:
        Updated ProcessingResult
    """
    if isinstance(exception, ProcessingError):
        result.add_error(exception)
    else:
        # Wrap generic exceptions in ProcessingError
        from .processing_exceptions import wrap_exception
        wrapped_error = wrap_exception(
            exception,
            error_code='UNEXPECTED_ERROR',
            additional_message=context
        )
        result.add_error(wrapped_error)

    result.mark_failure()
    return result