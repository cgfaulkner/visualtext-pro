"""
LLaVA Connectivity Hardening Module
==================================

Provides robust connectivity validation, smart retry logic, circuit breaker patterns,
and graceful degradation for LLaVA integration.

Key Features:
- Pre-flight health check validation
- Circuit breaker pattern with automatic recovery
- Smart retry logic with exponential backoff
- Service availability detection with timeouts
- Graceful degradation pathways
- Connection pool management
"""

import logging
import time
import threading
import json
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class ServiceState(Enum):
    """Service availability states."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    DOWN = "down"
    RECOVERING = "recovering"


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    service_name: str
    endpoint: str
    status: ServiceState
    response_time_ms: float
    success: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: float = 60.0      # Seconds before attempting recovery
    success_threshold: int = 2          # Successes needed to close circuit
    half_open_max_calls: int = 3        # Max calls in half-open state
    timeout: float = 30.0               # Individual request timeout


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retriable_status_codes: List[int] = field(
        default_factory=lambda: [500, 502, 503, 504, 429]
    )


class ConnectionPool:
    """Manages HTTP connection pooling for LLaVA services."""

    def __init__(self, pool_connections: int = 10, pool_maxsize: int = 10):
        self.session = requests.Session()

        # Configure retry strategy for the session
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=1,
            respect_retry_after_header=True
        )

        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy
        )

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set common headers
        self.session.headers.update({
            'User-Agent': 'pdf-alt-llava-client/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })

    def get(self, url: str, timeout: float = 30.0, **kwargs) -> requests.Response:
        """Make a GET request with connection pooling."""
        return self.session.get(url, timeout=timeout, **kwargs)

    def post(self, url: str, timeout: float = 30.0, **kwargs) -> requests.Response:
        """Make a POST request with connection pooling."""
        return self.session.post(url, timeout=timeout, **kwargs)

    def close(self):
        """Close the connection pool."""
        self.session.close()


class CircuitBreaker:
    """Circuit breaker implementation for service protection."""

    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0
        self.lock = threading.RLock()

    def can_execute(self) -> bool:
        """Check if a request can be executed."""
        with self.lock:
            if self.state == CircuitBreakerState.CLOSED:
                return True

            if self.state == CircuitBreakerState.OPEN:
                # Check if we should transition to half-open
                if time.time() - self.last_failure_time >= self.config.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.half_open_calls = 0
                    self.success_count = 0
                    logger.info(f"Circuit breaker {self.name} transitioning to HALF_OPEN")
                    return True
                return False

            if self.state == CircuitBreakerState.HALF_OPEN:
                return self.half_open_calls < self.config.half_open_max_calls

            return False

    def record_success(self):
        """Record a successful operation."""
        with self.lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    logger.info(f"Circuit breaker {self.name} recovered to CLOSED")
            elif self.state == CircuitBreakerState.CLOSED:
                self.failure_count = 0  # Reset failure count on success

    def record_failure(self):
        """Record a failed operation."""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitBreakerState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitBreakerState.OPEN
                    logger.warning(f"Circuit breaker {self.name} opened after {self.failure_count} failures")

            elif self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.OPEN
                logger.warning(f"Circuit breaker {self.name} failed in HALF_OPEN, returning to OPEN")

    def record_call(self):
        """Record a call attempt in half-open state."""
        with self.lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.half_open_calls += 1

    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state."""
        with self.lock:
            return {
                'name': self.name,
                'state': self.state.value,
                'failure_count': self.failure_count,
                'success_count': self.success_count,
                'half_open_calls': self.half_open_calls,
                'last_failure_time': self.last_failure_time,
                'can_execute': self.can_execute()
            }


class HealthChecker:
    """Performs health checks on LLaVA services."""

    def __init__(self, connection_pool: ConnectionPool):
        self.connection_pool = connection_pool

    def check_ollama_health(self, base_url: str, timeout: float = 10.0) -> HealthCheckResult:
        """Check basic Ollama service health."""
        start_time = time.time()

        try:
            # Check /api/tags endpoint for basic health
            tags_url = urljoin(base_url.rstrip('/') + '/', 'api/tags')
            response = self.connection_pool.get(tags_url, timeout=timeout)
            response.raise_for_status()

            response_time = (time.time() - start_time) * 1000

            # Parse response to check if service is functional
            try:
                data = response.json()
                models = data.get('models', [])
                model_count = len(models)
            except (json.JSONDecodeError, KeyError):
                model_count = 0

            return HealthCheckResult(
                service_name="ollama",
                endpoint=tags_url,
                status=ServiceState.HEALTHY,
                response_time_ms=response_time,
                success=True,
                metadata={
                    'model_count': model_count,
                    'status_code': response.status_code
                }
            )

        except requests.exceptions.Timeout:
            return HealthCheckResult(
                service_name="ollama",
                endpoint=base_url,
                status=ServiceState.DOWN,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error="Request timeout"
            )

        except requests.exceptions.ConnectionError as e:
            return HealthCheckResult(
                service_name="ollama",
                endpoint=base_url,
                status=ServiceState.DOWN,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error=f"Connection error: {str(e)}"
            )

        except requests.exceptions.HTTPError as e:
            status = ServiceState.DEGRADED if e.response.status_code >= 500 else ServiceState.FAILING
            return HealthCheckResult(
                service_name="ollama",
                endpoint=base_url,
                status=status,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error=f"HTTP {e.response.status_code}: {str(e)}"
            )

        except Exception as e:
            return HealthCheckResult(
                service_name="ollama",
                endpoint=base_url,
                status=ServiceState.DOWN,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error=f"Unexpected error: {str(e)}"
            )

    def check_model_availability(self, base_url: str, model_name: str, timeout: float = 10.0) -> HealthCheckResult:
        """Check if a specific model is available and loaded."""
        start_time = time.time()

        try:
            # Check model in tags list
            tags_url = urljoin(base_url.rstrip('/') + '/', 'api/tags')
            response = self.connection_pool.get(tags_url, timeout=timeout)
            response.raise_for_status()

            data = response.json()
            models = data.get('models', [])

            # Look for exact or partial model name match
            model_found = False
            model_info = None
            for model in models:
                if model_name in model.get('name', ''):
                    model_found = True
                    model_info = model
                    break

            response_time = (time.time() - start_time) * 1000

            if model_found:
                return HealthCheckResult(
                    service_name="model_check",
                    endpoint=tags_url,
                    status=ServiceState.HEALTHY,
                    response_time_ms=response_time,
                    success=True,
                    metadata={
                        'model_name': model_name,
                        'model_info': model_info,
                        'available_models': [m.get('name') for m in models]
                    }
                )
            else:
                return HealthCheckResult(
                    service_name="model_check",
                    endpoint=tags_url,
                    status=ServiceState.FAILING,
                    response_time_ms=response_time,
                    success=False,
                    error=f"Model '{model_name}' not found",
                    metadata={
                        'available_models': [m.get('name') for m in models]
                    }
                )

        except Exception as e:
            return HealthCheckResult(
                service_name="model_check",
                endpoint=base_url,
                status=ServiceState.DOWN,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error=str(e)
            )

    def check_generation_capability(self, base_url: str, model_name: str, timeout: float = 30.0) -> HealthCheckResult:
        """Test actual generation capability with a minimal request."""
        start_time = time.time()

        try:
            # Use generate endpoint with minimal text prompt
            generate_url = urljoin(base_url.rstrip('/') + '/', 'api/generate')

            test_payload = {
                "model": model_name,
                "prompt": "Test",
                "stream": False,
                "options": {
                    "num_predict": 5,  # Very short response
                    "temperature": 0.0
                }
            }

            response = self.connection_pool.post(
                generate_url,
                json=test_payload,
                timeout=timeout
            )
            response.raise_for_status()

            response_time = (time.time() - start_time) * 1000

            # Verify response format
            try:
                data = response.json()
                generated_text = data.get('response', '').strip()

                if generated_text:
                    status = ServiceState.HEALTHY
                    success = True
                    error = None
                else:
                    status = ServiceState.DEGRADED
                    success = False
                    error = "Empty response from model"

            except json.JSONDecodeError:
                status = ServiceState.DEGRADED
                success = False
                error = "Invalid JSON response"

            return HealthCheckResult(
                service_name="generation_test",
                endpoint=generate_url,
                status=status,
                response_time_ms=response_time,
                success=success,
                error=error,
                metadata={
                    'model_name': model_name,
                    'test_response_length': len(generated_text) if 'generated_text' in locals() else 0
                }
            )

        except requests.exceptions.Timeout:
            return HealthCheckResult(
                service_name="generation_test",
                endpoint=base_url,
                status=ServiceState.DEGRADED,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error="Generation test timeout"
            )

        except Exception as e:
            return HealthCheckResult(
                service_name="generation_test",
                endpoint=base_url,
                status=ServiceState.FAILING,
                response_time_ms=(time.time() - start_time) * 1000,
                success=False,
                error=str(e)
            )


class SmartRetryHandler:
    """Handles smart retry logic with exponential backoff and jitter."""

    def __init__(self, config: RetryConfig):
        self.config = config

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt with exponential backoff and jitter."""
        if attempt <= 0:
            return 0.0

        # Exponential backoff
        delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        delay = min(delay, self.config.max_delay)

        # Add jitter to prevent thundering herd
        if self.config.jitter:
            import random
            jitter_range = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_range, jitter_range)

        return max(0.0, delay)

    def should_retry(self, exception: Exception, attempt: int, status_code: Optional[int] = None) -> bool:
        """Determine if an operation should be retried."""
        if attempt >= self.config.max_retries:
            return False

        # Check for retriable status codes
        if status_code and status_code in self.config.retriable_status_codes:
            return True

        # Check for retriable exceptions
        if isinstance(exception, (requests.exceptions.Timeout,
                                 requests.exceptions.ConnectionError)):
            return True

        # HTTP errors with retriable status codes
        if isinstance(exception, requests.exceptions.HTTPError):
            if hasattr(exception, 'response') and exception.response:
                return exception.response.status_code in self.config.retriable_status_codes

        return False

    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with retry logic."""
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return func(*args, **kwargs)

            except Exception as e:
                last_exception = e
                status_code = None

                if hasattr(e, 'response') and e.response:
                    status_code = e.response.status_code

                if not self.should_retry(e, attempt, status_code):
                    break

                if attempt < self.config.max_retries:
                    delay = self.calculate_delay(attempt + 1)
                    logger.debug(f"Retry attempt {attempt + 1}/{self.config.max_retries} "
                               f"after {delay:.2f}s delay: {str(e)}")
                    time.sleep(delay)

        # All retries exhausted
        raise last_exception


class LLaVAConnectivityManager:
    """Main class for managing LLaVA connectivity with hardening features."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connection_pool = ConnectionPool()
        self.health_checker = HealthChecker(self.connection_pool)

        # Initialize circuit breakers for each provider
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Initialize retry handlers
        self.retry_handler = SmartRetryHandler(RetryConfig(
            max_retries=config.get('max_retries', 3),
            base_delay=config.get('retry_base_delay', 1.0),
            max_delay=config.get('retry_max_delay', 60.0)
        ))

        # Health check cache
        self.health_cache: Dict[str, HealthCheckResult] = {}
        self.health_cache_ttl = config.get('health_cache_ttl', 30.0)  # 30 seconds

        # Background health monitoring
        self.monitoring_enabled = config.get('background_monitoring', True)
        self.monitoring_interval = config.get('monitoring_interval', 60.0)  # 1 minute
        self.monitoring_thread = None
        self.stop_monitoring = threading.Event()

        if self.monitoring_enabled:
            self.start_background_monitoring()

    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for provider."""
        if provider_name not in self.circuit_breakers:
            cb_config = CircuitBreakerConfig(
                failure_threshold=self.config.get('circuit_breaker_failure_threshold', 5),
                recovery_timeout=self.config.get('circuit_breaker_recovery_timeout', 60.0),
                success_threshold=self.config.get('circuit_breaker_success_threshold', 2),
                timeout=self.config.get('circuit_breaker_timeout', 30.0)
            )
            self.circuit_breakers[provider_name] = CircuitBreaker(provider_name, cb_config)

        return self.circuit_breakers[provider_name]

    def validate_connectivity(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive pre-flight connectivity validation.

        Returns validation results with service state and recommendations.
        """
        provider_name = provider_config.get('name', 'unknown')
        base_url = provider_config.get('base_url', 'http://127.0.0.1:11434')
        model_name = provider_config.get('model', 'llava:latest')

        validation_start = time.time()
        results = {
            'provider_name': provider_name,
            'overall_status': ServiceState.DOWN,
            'can_process': False,
            'tests': [],
            'recommendations': [],
            'total_time_ms': 0
        }

        logger.info(f"Starting connectivity validation for {provider_name}")

        # Test 1: Basic service health
        logger.debug("Test 1/3: Basic service health")
        health_result = self.health_checker.check_ollama_health(base_url)
        results['tests'].append(health_result)

        if not health_result.success:
            results['recommendations'].append(
                f"Ollama service is not accessible at {base_url}. "
                f"Check if Ollama is running and accessible."
            )
            results['total_time_ms'] = (time.time() - validation_start) * 1000
            return results

        # Test 2: Model availability
        logger.debug("Test 2/3: Model availability")
        model_result = self.health_checker.check_model_availability(base_url, model_name)
        results['tests'].append(model_result)

        if not model_result.success:
            available_models = model_result.metadata.get('available_models', [])
            if available_models:
                results['recommendations'].append(
                    f"Model '{model_name}' not found. Available models: {available_models}. "
                    f"Consider pulling the model with 'ollama pull {model_name}'"
                )
            else:
                results['recommendations'].append(
                    f"No models available. Pull the required model with 'ollama pull {model_name}'"
                )
            results['overall_status'] = ServiceState.FAILING
            results['total_time_ms'] = (time.time() - validation_start) * 1000
            return results

        # Test 3: Generation capability
        logger.debug("Test 3/3: Generation capability")
        generation_result = self.health_checker.check_generation_capability(base_url, model_name)
        results['tests'].append(generation_result)

        # Determine overall status
        if all(test.success for test in results['tests']):
            results['overall_status'] = ServiceState.HEALTHY
            results['can_process'] = True
            logger.info(f"✅ Connectivity validation passed for {provider_name}")
        elif health_result.success and model_result.success:
            results['overall_status'] = ServiceState.DEGRADED
            results['can_process'] = True  # Can try processing with degraded performance
            results['recommendations'].append(
                "Service is accessible but generation test failed. Processing may be slow or unreliable."
            )
            logger.warning(f"⚠️ Connectivity validation shows degraded service for {provider_name}")
        else:
            results['overall_status'] = ServiceState.FAILING
            results['can_process'] = False
            logger.error(f"❌ Connectivity validation failed for {provider_name}")

        results['total_time_ms'] = (time.time() - validation_start) * 1000
        return results

    def execute_with_hardening(self, func: Callable, provider_name: str, *args, **kwargs) -> Any:
        """Execute a function with full connectivity hardening."""
        circuit_breaker = self.get_circuit_breaker(provider_name)

        # Check circuit breaker
        if not circuit_breaker.can_execute():
            raise RuntimeError(f"Circuit breaker is open for {provider_name}")

        # Record the call if in half-open state
        circuit_breaker.record_call()

        try:
            # Execute with retry logic
            result = self.retry_handler.execute_with_retry(func, *args, **kwargs)

            # Record success
            circuit_breaker.record_success()

            return result

        except Exception as e:
            # Record failure
            circuit_breaker.record_failure()
            raise

    def get_cached_health_status(self, provider_name: str, base_url: str) -> Optional[HealthCheckResult]:
        """Get cached health status if still valid."""
        cache_key = f"{provider_name}:{base_url}"

        if cache_key in self.health_cache:
            cached_result = self.health_cache[cache_key]
            age = time.time() - cached_result.timestamp

            if age < self.health_cache_ttl:
                return cached_result
            else:
                # Remove expired cache entry
                del self.health_cache[cache_key]

        return None

    def cache_health_status(self, provider_name: str, base_url: str, result: HealthCheckResult):
        """Cache health check result."""
        cache_key = f"{provider_name}:{base_url}"
        self.health_cache[cache_key] = result

    def start_background_monitoring(self):
        """Start background health monitoring thread."""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return

        self.monitoring_thread = threading.Thread(
            target=self._background_monitor,
            daemon=True
        )
        self.monitoring_thread.start()
        logger.info("Started background health monitoring")

    def stop_background_monitoring(self):
        """Stop background health monitoring."""
        if self.monitoring_thread:
            self.stop_monitoring.set()
            self.monitoring_thread.join(timeout=5.0)
            logger.info("Stopped background health monitoring")

    def _background_monitor(self):
        """Background monitoring loop."""
        while not self.stop_monitoring.wait(self.monitoring_interval):
            try:
                # Monitor each configured provider
                providers_config = self.config.get('providers', {})
                for provider_name, provider_config in providers_config.items():
                    if not provider_config.get('enabled', True):
                        continue

                    base_url = provider_config.get('base_url', 'http://127.0.0.1:11434')

                    # Quick health check
                    health_result = self.health_checker.check_ollama_health(base_url, timeout=5.0)
                    self.cache_health_status(provider_name, base_url, health_result)

                    # Update circuit breaker based on health
                    circuit_breaker = self.get_circuit_breaker(provider_name)
                    if health_result.success:
                        # Don't record success unless we were previously failing
                        if circuit_breaker.state != CircuitBreakerState.CLOSED:
                            circuit_breaker.record_success()
                    else:
                        circuit_breaker.record_failure()

            except Exception as e:
                logger.debug(f"Background monitoring error: {e}")

    def get_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status report."""
        status = {
            'timestamp': time.time(),
            'overall_healthy': True,
            'providers': {},
            'circuit_breakers': {},
            'health_cache_size': len(self.health_cache)
        }

        # Get circuit breaker states
        for name, cb in self.circuit_breakers.items():
            status['circuit_breakers'][name] = cb.get_state()
            if cb.state != CircuitBreakerState.CLOSED:
                status['overall_healthy'] = False

        # Get cached health status
        for cache_key, health_result in self.health_cache.items():
            provider_name = cache_key.split(':', 1)[0]
            status['providers'][provider_name] = {
                'last_health_check': health_result.timestamp,
                'status': health_result.status.value,
                'response_time_ms': health_result.response_time_ms,
                'success': health_result.success,
                'error': health_result.error
            }

            if not health_result.success:
                status['overall_healthy'] = False

        return status

    def force_circuit_breaker_reset(self, provider_name: str):
        """Manually reset a circuit breaker (for testing/recovery)."""
        if provider_name in self.circuit_breakers:
            cb = self.circuit_breakers[provider_name]
            with cb.lock:
                cb.state = CircuitBreakerState.CLOSED
                cb.failure_count = 0
                cb.success_count = 0
                cb.half_open_calls = 0
                logger.info(f"Circuit breaker for {provider_name} manually reset")

    def create_degraded_response(self, context: str, image_info: Optional[Dict] = None) -> str:
        """
        Create a graceful degradation response when LLaVA is unavailable.
        """
        # Build a descriptive fallback based on available context
        fallback_parts = []

        if image_info:
            # Use image metadata if available
            if image_info.get('width') and image_info.get('height'):
                fallback_parts.append(f"Image ({image_info['width']}x{image_info['height']} pixels)")
            else:
                fallback_parts.append("Image")

            if image_info.get('format'):
                fallback_parts.append(f"in {image_info['format']} format")
        else:
            fallback_parts.append("Visual element")

        # Add context if available
        if context and context.strip():
            # Extract meaningful context information
            context_lower = context.lower()
            if "slide" in context_lower:
                fallback_parts.append("from presentation slide")
            elif "chart" in context_lower or "graph" in context_lower:
                fallback_parts.append("containing chart or graph")
            elif "diagram" in context_lower:
                fallback_parts.append("containing diagram")
            elif "text" in context_lower:
                fallback_parts.append("containing text")

        # Create final fallback message
        base_description = " ".join(fallback_parts)
        fallback_message = f"{base_description}. Detailed description unavailable due to service limitations."

        # Ensure proper length and punctuation
        if len(fallback_message) > 125:
            fallback_message = base_description[:100].strip() + "."
        elif not fallback_message.endswith('.'):
            fallback_message += "."

        return fallback_message

    def __del__(self):
        """Cleanup resources."""
        try:
            self.stop_background_monitoring()
            self.connection_pool.close()
        except Exception:
            pass