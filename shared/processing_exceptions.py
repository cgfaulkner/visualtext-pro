#!/usr/bin/env python3
"""
Unified Exception Hierarchy for PDF-Alt Processing
================================================

Common exception classes for all processors with consistent error codes,
categorization, and structured data for programmatic handling.

Error Categories:
- Resource: Memory, disk space, file access issues
- Service: LLaVA connectivity, API failures
- Processing: Content parsing, generation failures
- Configuration: Invalid settings, missing dependencies
- Validation: Input validation, schema mismatches
"""

from typing import Any, Dict, List, Optional, Union
import logging
import traceback
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    """
    Base exception for all processing errors.

    Provides structured error data, categorization, and recovery hints.
    """

    ERROR_CATEGORIES = {
        'RESOURCE': 'resource',
        'SERVICE': 'service',
        'PROCESSING': 'processing',
        'CONFIGURATION': 'configuration',
        'VALIDATION': 'validation'
    }

    def __init__(self,
                 message: str,
                 error_code: str,
                 category: str = 'processing',
                 details: Optional[Dict[str, Any]] = None,
                 recoverable: bool = False,
                 recovery_hint: Optional[str] = None,
                 cause: Optional[Exception] = None):
        """
        Initialize processing error with structured data.

        Args:
            message: Human-readable error message
            error_code: Unique error code (e.g., 'PPTX_GENERATION_FAILED')
            category: Error category from ERROR_CATEGORIES
            details: Additional error data for programmatic handling
            recoverable: Whether this error can potentially be recovered from
            recovery_hint: Suggested recovery action
            cause: Original exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.category = category
        self.details = details or {}
        self.recoverable = recoverable
        self.recovery_hint = recovery_hint
        self.cause = cause
        self.timestamp = time.time()

        # Capture stack trace
        self.stack_trace = traceback.format_exc()

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for JSON serialization."""
        return {
            'error_code': self.error_code,
            'category': self.category,
            'message': self.message,
            'details': self.details,
            'recoverable': self.recoverable,
            'recovery_hint': self.recovery_hint,
            'timestamp': self.timestamp,
            'cause': str(self.cause) if self.cause else None,
            'stack_trace': self.stack_trace
        }

    def get_user_message(self) -> str:
        """Get user-friendly error message with actionable guidance."""
        if self.recovery_hint:
            return f"{self.message}\n\nSuggested action: {self.recovery_hint}"
        return self.message


# Resource-related exceptions
class ResourceError(ProcessingError):
    """Errors related to system resources (memory, disk, files)."""

    def __init__(self, message: str, error_code: str, **kwargs):
        super().__init__(message, error_code, category='resource', **kwargs)


class InsufficientMemoryError(ResourceError):
    """Insufficient memory for processing."""

    def __init__(self, required_mb: int, available_mb: int, **kwargs):
        message = f"Insufficient memory: need {required_mb}MB, have {available_mb}MB"
        super().__init__(
            message=message,
            error_code='INSUFFICIENT_MEMORY',
            details={'required_mb': required_mb, 'available_mb': available_mb},
            recoverable=True,
            recovery_hint="Close other applications or process smaller files",
            **kwargs
        )


class InsufficientDiskSpaceError(ResourceError):
    """Insufficient disk space for processing."""

    def __init__(self, required_mb: int, available_mb: int, path: Union[str, Path], **kwargs):
        message = f"Insufficient disk space: need {required_mb}MB, have {available_mb}MB at {path}"
        super().__init__(
            message=message,
            error_code='INSUFFICIENT_DISK_SPACE',
            details={'required_mb': required_mb, 'available_mb': available_mb, 'path': str(path)},
            recoverable=True,
            recovery_hint="Free up disk space or use a different output directory",
            **kwargs
        )


class FileAccessError(ResourceError):
    """File access or permission errors."""

    def __init__(self, file_path: Union[str, Path], operation: str, **kwargs):
        message = f"Cannot {operation} file: {file_path}"
        super().__init__(
            message=message,
            error_code='FILE_ACCESS_ERROR',
            details={'file_path': str(file_path), 'operation': operation},
            recoverable=True,
            recovery_hint="Check file permissions and ensure the file is not open in another application",
            **kwargs
        )


class TempFileError(ResourceError):
    """Temporary file creation or cleanup errors."""

    def __init__(self, operation: str, temp_path: Optional[Union[str, Path]] = None, **kwargs):
        message = f"Temporary file {operation} failed"
        if temp_path:
            message += f": {temp_path}"
        super().__init__(
            message=message,
            error_code='TEMP_FILE_ERROR',
            details={'operation': operation, 'temp_path': str(temp_path) if temp_path else None},
            recoverable=True,
            recovery_hint="Check disk space and temp directory permissions",
            **kwargs
        )


# Service-related exceptions
class ServiceError(ProcessingError):
    """Errors related to external services (LLaVA, APIs)."""

    def __init__(self, message: str, error_code: str, **kwargs):
        super().__init__(message, error_code, category='service', **kwargs)


class LLaVAConnectionError(ServiceError):
    """LLaVA service connection or availability errors."""

    def __init__(self, endpoint: str, status_code: Optional[int] = None, **kwargs):
        message = f"LLaVA service unavailable at {endpoint}"
        if status_code:
            message += f" (status: {status_code})"

        recovery_hint = "Check LLaVA service status and network connectivity"
        if status_code == 503:
            recovery_hint = "LLaVA service is temporarily overloaded. Try again in a few minutes."
        elif status_code == 404:
            recovery_hint = "LLaVA endpoint not found. Check configuration."

        super().__init__(
            message=message,
            error_code='LLAVA_CONNECTION_ERROR',
            details={'endpoint': endpoint, 'status_code': status_code},
            recoverable=True,
            recovery_hint=recovery_hint,
            **kwargs
        )


class LLaVAGenerationError(ServiceError):
    """LLaVA ALT text generation failures."""

    def __init__(self, image_key: str, attempt_count: int = 1, **kwargs):
        message = f"LLaVA generation failed for image {image_key}"
        if attempt_count > 1:
            message += f" after {attempt_count} attempts"

        super().__init__(
            message=message,
            error_code='LLAVA_GENERATION_FAILED',
            details={'image_key': image_key, 'attempt_count': attempt_count},
            recoverable=True,
            recovery_hint="Image may be unsuitable for ALT text generation or service may be overloaded",
            **kwargs
        )


# Processing-related exceptions
class ProcessingContentError(ProcessingError):
    """Errors related to content processing and parsing."""

    def __init__(self, message: str, error_code: str, **kwargs):
        super().__init__(message, error_code, category='processing', **kwargs)


class PPTXParsingError(ProcessingContentError):
    """PPTX file parsing or structure errors."""

    def __init__(self, file_path: Union[str, Path], reason: str, **kwargs):
        message = f"Cannot parse PPTX file {file_path}: {reason}"
        super().__init__(
            message=message,
            error_code='PPTX_PARSING_ERROR',
            details={'file_path': str(file_path), 'reason': reason},
            recoverable=False,
            recovery_hint="Ensure the file is a valid PPTX file and not corrupted",
            **kwargs
        )


class DOCXParsingError(ProcessingContentError):
    """DOCX file parsing or structure errors."""

    def __init__(self, file_path: Union[str, Path], reason: str, **kwargs):
        message = f"Cannot parse DOCX file {file_path}: {reason}"
        super().__init__(
            message=message,
            error_code='DOCX_PARSING_ERROR',
            details={'file_path': str(file_path), 'reason': reason},
            recoverable=False,
            recovery_hint="Ensure the file is a valid DOCX file and not corrupted",
            **kwargs
        )


class ImageExtractionError(ProcessingContentError):
    """Image extraction from documents failed."""

    def __init__(self, image_key: str, file_path: Union[str, Path], reason: str, **kwargs):
        message = f"Cannot extract image {image_key} from {file_path}: {reason}"
        super().__init__(
            message=message,
            error_code='IMAGE_EXTRACTION_ERROR',
            details={'image_key': image_key, 'file_path': str(file_path), 'reason': reason},
            recoverable=True,
            recovery_hint="Image may be corrupted or embedded in an unsupported format",
            **kwargs
        )


class InjectionError(ProcessingContentError):
    """ALT text injection into documents failed."""

    def __init__(self, file_path: Union[str, Path], failed_count: int, total_count: int, **kwargs):
        message = f"ALT text injection failed for {failed_count}/{total_count} images in {file_path}"
        super().__init__(
            message=message,
            error_code='ALT_TEXT_INJECTION_ERROR',
            details={'file_path': str(file_path), 'failed_count': failed_count, 'total_count': total_count},
            recoverable=True,
            recovery_hint="Some images may have been processed successfully. Check the output file.",
            **kwargs
        )


# Configuration-related exceptions
class ConfigurationError(ProcessingError):
    """Configuration or setup related errors."""

    def __init__(self, message: str, error_code: str, **kwargs):
        super().__init__(message, error_code, category='configuration', **kwargs)


class MissingDependencyError(ConfigurationError):
    """Required dependency not available."""

    def __init__(self, dependency: str, install_hint: str, **kwargs):
        message = f"Required dependency not found: {dependency}"
        super().__init__(
            message=message,
            error_code='MISSING_DEPENDENCY',
            details={'dependency': dependency, 'install_hint': install_hint},
            recoverable=True,
            recovery_hint=install_hint,
            **kwargs
        )


class InvalidConfigError(ConfigurationError):
    """Configuration validation failed."""

    def __init__(self, config_key: str, reason: str, **kwargs):
        message = f"Invalid configuration for '{config_key}': {reason}"
        super().__init__(
            message=message,
            error_code='INVALID_CONFIG',
            details={'config_key': config_key, 'reason': reason},
            recoverable=True,
            recovery_hint="Check configuration file and ensure all required settings are valid",
            **kwargs
        )


# Validation-related exceptions
class ValidationError(ProcessingError):
    """Input validation and schema errors."""

    def __init__(self, message: str, error_code: str, **kwargs):
        super().__init__(message, error_code, category='validation', **kwargs)


class UnsupportedFileTypeError(ValidationError):
    """File type not supported for processing."""

    def __init__(self, file_path: Union[str, Path], supported_types: List[str], **kwargs):
        message = f"Unsupported file type: {file_path}. Supported types: {', '.join(supported_types)}"
        super().__init__(
            message=message,
            error_code='UNSUPPORTED_FILE_TYPE',
            details={'file_path': str(file_path), 'supported_types': supported_types},
            recoverable=False,
            recovery_hint=f"Convert file to one of: {', '.join(supported_types)}",
            **kwargs
        )


class ManifestValidationError(ValidationError):
    """Manifest file validation failed."""

    def __init__(self, manifest_path: Union[str, Path], validation_errors: List[str], **kwargs):
        message = f"Manifest validation failed: {manifest_path}"
        super().__init__(
            message=message,
            error_code='MANIFEST_VALIDATION_ERROR',
            details={'manifest_path': str(manifest_path), 'validation_errors': validation_errors},
            recoverable=True,
            recovery_hint="Fix manifest validation errors or regenerate the manifest",
            **kwargs
        )


# Utility functions
def create_processing_error(category: str, error_code: str, message: str, **kwargs) -> ProcessingError:
    """
    Factory function to create appropriate exception type based on category.
    """
    error_classes = {
        'resource': ResourceError,
        'service': ServiceError,
        'processing': ProcessingContentError,
        'configuration': ConfigurationError,
        'validation': ValidationError
    }

    error_class = error_classes.get(category, ProcessingError)
    return error_class(message=message, error_code=error_code, **kwargs)


def wrap_exception(original_exception: Exception,
                  error_code: str,
                  category: str = 'processing',
                  additional_message: str = "",
                  **kwargs) -> ProcessingError:
    """
    Wrap an existing exception in a ProcessingError with additional context.
    """
    message = str(original_exception)
    if additional_message:
        message = f"{additional_message}: {message}"

    return create_processing_error(
        category=category,
        error_code=error_code,
        message=message,
        cause=original_exception,
        **kwargs
    )


def log_structured_error(error: ProcessingError, logger: logging.Logger):
    """
    Log a structured error with appropriate level and formatting.
    """
    error_data = error.to_dict()

    # Choose log level based on recoverability
    if error.recoverable:
        log_level = logging.WARNING
    else:
        log_level = logging.ERROR

    logger.log(log_level, f"[{error.error_code}] {error.message}")

    if error.details:
        logger.debug(f"Error details: {error.details}")

    if error.recovery_hint:
        logger.info(f"Recovery hint: {error.recovery_hint}")

    if error.cause:
        logger.debug(f"Caused by: {error.cause}", exc_info=error.cause)