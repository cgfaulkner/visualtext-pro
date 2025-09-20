#!/usr/bin/env python3
"""
Smart Recovery Strategies for PDF-Alt Processing
================================================

Leverages Session 1's resource cleanup and Session 2's LLaVA hardening
to provide intelligent error recovery with processor-specific strategies.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union
from contextlib import contextmanager

try:
    from .processing_exceptions import (
        ProcessingError, ResourceError, ServiceError, ProcessingContentError,
        LLaVAConnectionError, LLaVAGenerationError, InsufficientMemoryError,
        InsufficientDiskSpaceError, FileAccessError
    )
    from .resource_manager import ResourceContext, validate_system_resources, get_temp_manager
    from .error_reporter import ProcessingResult
except ImportError:
    from processing_exceptions import (
        ProcessingError, ResourceError, ServiceError, ProcessingContentError,
        LLaVAConnectionError, LLaVAGenerationError, InsufficientMemoryError,
        InsufficientDiskSpaceError, FileAccessError
    )
    from resource_manager import ResourceContext, validate_system_resources, get_temp_manager
    from error_reporter import ProcessingResult

logger = logging.getLogger(__name__)


class RecoveryStrategy:
    """Base class for recovery strategies."""

    def __init__(self, name: str, max_attempts: int = 3):
        self.name = name
        self.max_attempts = max_attempts
        self.attempt_count = 0

    def can_recover(self, error: ProcessingError) -> bool:
        """Check if this strategy can recover from the given error."""
        return error.recoverable and self.attempt_count < self.max_attempts

    def attempt_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        """
        Attempt to recover from the error.

        Args:
            error: The error to recover from
            context: Processing context and state

        Returns:
            True if recovery was successful, False otherwise
        """
        self.attempt_count += 1
        logger.info(f"🔧 Attempting recovery with {self.name} (attempt {self.attempt_count}/{self.max_attempts})")

        try:
            return self._execute_recovery(error, context)
        except Exception as e:
            logger.warning(f"Recovery strategy {self.name} failed: {e}")
            return False

    def _execute_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        """Override this method to implement specific recovery logic."""
        raise NotImplementedError

    def reset(self):
        """Reset attempt counter for reuse."""
        self.attempt_count = 0


class ResourceCleanupStrategy(RecoveryStrategy):
    """Cleanup temporary files and free resources."""

    def __init__(self):
        super().__init__("Resource Cleanup", max_attempts=2)

    def can_recover(self, error: ProcessingError) -> bool:
        return (isinstance(error, (ResourceError, InsufficientDiskSpaceError)) and
                super().can_recover(error))

    def _execute_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        logger.info("🧹 Performing aggressive resource cleanup")

        # Get temp manager and force cleanup
        temp_manager = get_temp_manager()
        if temp_manager:
            cleanup_count = len(temp_manager._temp_files) + len(temp_manager._temp_dirs)
            temp_manager.cleanup_all()
            logger.info(f"   Cleaned up {cleanup_count} temporary items")

        # Force garbage collection
        import gc
        gc.collect()

        # Re-validate resources
        required_memory = context.get('required_memory_mb', 250)
        required_disk = context.get('required_disk_mb', 300)

        validation = validate_system_resources(required_memory, required_disk)
        if validation['sufficient']:
            logger.info("✅ Resource cleanup successful - sufficient resources now available")
            return True
        else:
            logger.warning(f"❌ Resource cleanup insufficient: {'; '.join(validation['errors'])}")
            return False


class LLaVAConnectionRecoveryStrategy(RecoveryStrategy):
    """Recover from LLaVA service connection issues."""

    def __init__(self):
        super().__init__("LLaVA Connection Recovery", max_attempts=3)

    def can_recover(self, error: ProcessingError) -> bool:
        return (isinstance(error, (ServiceError, LLaVAConnectionError)) and
                super().can_recover(error))

    def _execute_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        logger.info("🔌 Attempting LLaVA connection recovery")

        # Progressive backoff delays
        backoff_delays = [2, 5, 10]
        delay = backoff_delays[min(self.attempt_count - 1, len(backoff_delays) - 1)]

        logger.info(f"   Waiting {delay}s before retry...")
        time.sleep(delay)

        # Test LLaVA connectivity
        try:
            llava_connectivity = context.get('llava_connectivity')
            if llava_connectivity:
                if llava_connectivity.test_connectivity():
                    logger.info("✅ LLaVA connection restored")
                    return True
                else:
                    logger.warning("❌ LLaVA still unavailable")
                    return False
            else:
                # Import and test connectivity
                try:
                    try:
                        from .llava_connectivity import LLaVAConnectivity
                    except ImportError:
                        from llava_connectivity import LLaVAConnectivity

                    connectivity = LLaVAConnectivity()
                    if connectivity.test_connectivity():
                        logger.info("✅ LLaVA connection established")
                        context['llava_connectivity'] = connectivity
                        return True
                except ImportError:
                    logger.warning("LLaVA connectivity module not available")
                    return False
        except Exception as e:
            logger.warning(f"LLaVA connectivity test failed: {e}")
            return False


class FileAccessRecoveryStrategy(RecoveryStrategy):
    """Recover from file access issues."""

    def __init__(self):
        super().__init__("File Access Recovery", max_attempts=2)

    def can_recover(self, error: ProcessingError) -> bool:
        return (isinstance(error, FileAccessError) and
                super().can_recover(error))

    def _execute_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        logger.info("📁 Attempting file access recovery")

        file_path = error.details.get('file_path')
        if not file_path:
            return False

        file_path = Path(file_path)

        # Wait briefly in case file is temporarily locked
        time.sleep(1)

        # Check if file exists and is accessible
        try:
            if file_path.exists() and file_path.is_file():
                # Try to open file to test access
                with open(file_path, 'rb') as f:
                    f.read(1)  # Read one byte to test
                logger.info("✅ File access restored")
                return True
            else:
                logger.warning(f"❌ File not accessible: {file_path}")
                return False
        except Exception as e:
            logger.warning(f"❌ File access still denied: {e}")
            return False


class ProcessingRetryStrategy(RecoveryStrategy):
    """Retry processing with adjusted parameters."""

    def __init__(self):
        super().__init__("Processing Retry", max_attempts=2)

    def can_recover(self, error: ProcessingError) -> bool:
        return (isinstance(error, ProcessingContentError) and
                super().can_recover(error))

    def _execute_recovery(self, error: ProcessingError, context: Dict[str, Any]) -> bool:
        logger.info("🔄 Attempting processing retry with adjusted parameters")

        # Adjust processing parameters for retry
        if 'config' in context:
            config = context['config']

            # Reduce memory usage
            if 'generation' in config:
                config['generation']['max_concurrent'] = min(
                    config['generation'].get('max_concurrent', 3), 2
                )
                logger.info("   Reduced concurrent processing")

            # Increase timeouts
            if 'timeouts' in config:
                for key in ['generation', 'connection', 'response']:
                    if key in config['timeouts']:
                        config['timeouts'][key] = int(config['timeouts'][key] * 1.5)
                logger.info("   Increased timeout values")

        logger.info("✅ Processing parameters adjusted for retry")
        return True


class SmartRecoveryManager:
    """
    Manages multiple recovery strategies and applies them intelligently.
    """

    def __init__(self):
        self.strategies: List[RecoveryStrategy] = [
            ResourceCleanupStrategy(),
            LLaVAConnectionRecoveryStrategy(),
            FileAccessRecoveryStrategy(),
            ProcessingRetryStrategy()
        ]
        self.recovery_history: List[Dict[str, Any]] = []

    def attempt_recovery(self, error: ProcessingError,
                        context: Dict[str, Any]) -> bool:
        """
        Attempt to recover from an error using appropriate strategies.

        Args:
            error: The error to recover from
            context: Processing context including config, temp managers, etc.

        Returns:
            True if recovery was successful, False otherwise
        """
        if not error.recoverable:
            logger.info(f"❌ Error {error.error_code} is not recoverable")
            return False

        logger.info(f"🚑 Attempting smart recovery from: {error.error_code}")

        # Find applicable strategies
        applicable_strategies = [
            strategy for strategy in self.strategies
            if strategy.can_recover(error)
        ]

        if not applicable_strategies:
            logger.warning("No applicable recovery strategies found")
            return False

        # Try each strategy
        for strategy in applicable_strategies:
            try:
                if strategy.attempt_recovery(error, context):
                    self._record_successful_recovery(error, strategy)
                    return True
            except Exception as e:
                logger.warning(f"Recovery strategy {strategy.name} threw exception: {e}")

        logger.warning("All recovery strategies failed")
        return False

    def _record_successful_recovery(self, error: ProcessingError, strategy: RecoveryStrategy):
        """Record a successful recovery for future reference."""
        recovery_record = {
            'timestamp': time.time(),
            'error_code': error.error_code,
            'error_category': error.category,
            'strategy_used': strategy.name,
            'attempt_count': strategy.attempt_count
        }
        self.recovery_history.append(recovery_record)
        logger.info(f"✅ Successfully recovered using {strategy.name}")

    def reset_all_strategies(self):
        """Reset all strategy attempt counters."""
        for strategy in self.strategies:
            strategy.reset()

    def get_recovery_stats(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        if not self.recovery_history:
            return {'total_recoveries': 0}

        strategy_counts = {}
        error_category_counts = {}

        for record in self.recovery_history:
            strategy = record['strategy_used']
            category = record['error_category']

            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
            error_category_counts[category] = error_category_counts.get(category, 0) + 1

        return {
            'total_recoveries': len(self.recovery_history),
            'strategy_usage': strategy_counts,
            'error_categories_recovered': error_category_counts,
            'success_rate_by_strategy': {
                strategy: count / len(self.recovery_history)
                for strategy, count in strategy_counts.items()
            }
        }


@contextmanager
def smart_recovery_context(result: ProcessingResult,
                         recovery_manager: Optional[SmartRecoveryManager] = None,
                         **context_kwargs):
    """
    Context manager that provides smart recovery capabilities.

    Args:
        result: ProcessingResult to update with recovery attempts
        recovery_manager: Optional recovery manager (creates one if None)
        **context_kwargs: Additional context for recovery strategies
    """
    if recovery_manager is None:
        recovery_manager = SmartRecoveryManager()

    context = {
        'result': result,
        'start_time': time.time(),
        **context_kwargs
    }

    try:
        yield recovery_manager, context
    except ProcessingError as e:
        # Attempt recovery for ProcessingError
        if recovery_manager.attempt_recovery(e, context):
            result.add_warning(f"Recovered from {e.error_code} using smart recovery")
            # Don't re-raise, let processing continue
        else:
            result.add_error(e)
            raise
    except Exception as e:
        # Convert generic exceptions and attempt recovery
        try:
            from .processing_exceptions import wrap_exception
        except ImportError:
            from processing_exceptions import wrap_exception
        wrapped_error = wrap_exception(e, 'UNEXPECTED_ERROR', category='processing')

        if recovery_manager.attempt_recovery(wrapped_error, context):
            result.add_warning(f"Recovered from unexpected error using smart recovery")
        else:
            result.add_error(wrapped_error)
            raise wrapped_error


def integrate_recovery_with_resource_context(recovery_manager: SmartRecoveryManager,
                                           validate_resources: bool = True,
                                           cleanup_on_exit: bool = True,
                                           **context_kwargs) -> ResourceContext:
    """
    Create a ResourceContext integrated with smart recovery.

    Args:
        recovery_manager: Recovery manager to use
        validate_resources: Whether to validate system resources
        cleanup_on_exit: Whether to cleanup on context exit
        **context_kwargs: Additional context for recovery

    Returns:
        ResourceContext with recovery integration
    """
    # Add recovery manager to context
    context_kwargs['recovery_manager'] = recovery_manager

    return ResourceContext(
        validate_resources=validate_resources,
        cleanup_on_exit=cleanup_on_exit
    )