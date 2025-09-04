"""
Flexible ALT text generator using a local LLaVA model.
"""

import logging
import re
import base64
import json
import psutil
import platform
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from abc import ABC, abstractmethod
import time

from config_manager import ConfigManager

logger = logging.getLogger(__name__)


class BaseAltProvider(ABC):
    """Abstract base class for ALT text providers."""
    
    def __init__(self, provider_name: str, config: Dict[str, Any], config_manager: ConfigManager):
        self.provider_name = provider_name
        self.config = config
        self.config_manager = config_manager
        self.active_prompt_type = 'default'
        
    @abstractmethod
    def generate_alt_text(self, image_path: str, prompt: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Generate ALT text for an image.
        
        Returns:
            Tuple of (alt_text, metadata) where metadata includes token usage, cost, etc.
        """
        pass
    
    def set_prompt_type(self, prompt_type: str):
        """Set the active prompt type."""
        self.active_prompt_type = prompt_type


class LLaVAProvider(BaseAltProvider):
    """LLaVA provider for local inference."""

    def __init__(self, provider_name: str, config: Dict[str, Any], config_manager: ConfigManager):
        """Initialize provider and apply logging configuration."""
        super().__init__(provider_name, config, config_manager)

        self.logging_config = {}
        if hasattr(config_manager, "get_logging_config"):
            self.logging_config = config_manager.get_logging_config()
            level_name = self.logging_config.get("level", "INFO").upper()
            logger.setLevel(getattr(logging, level_name, logging.INFO))
    
    def generate_alt_text(self, image_path: str, prompt: str, image_data: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Any]]:
        """Generate ALT text using LLaVA."""
        import base64
        import requests
        import time

        start_time = time.time()
        metadata = {
            'provider': self.provider_name,
            'model': self.config['model'],
            'tokens_used': 0,
            'cost_estimate': 0.0,  # Local inference is free
            'generation_time': 0.0,
            'success': False
        }
        response_text = None

        try:
            # Handle image data - either from file or directly provided
            if image_data:
                # Image data already provided (base64 encoded)
                logger.debug("Using provided image data")
            else:
                # Load image from file
                image_file = Path(image_path)
                if not image_file.exists():
                    logger.error(f"Image file not found: {image_path}")
                    return None, metadata

                # Encode image
                with open(image_file, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode("utf-8")
                    
            logger.debug("Base64 image size: %s", len(image_data))

            prompt_length = len(prompt)
            if self.logging_config.get('show_prompts', False):
                logger.debug(
                    "Prompt length: %s; preview: %s",
                    prompt_length,
                    prompt[:100],
                )
            else:
                logger.debug("Prompt length: %s", prompt_length)

            # Build minimal payload with only required fields
            payload = {
                "model": self.config['model'],
                "prompt": prompt,
                "images": [image_data],
                "stream": False
            }

            # Prepare endpoint, forcing 127.0.0.1 to avoid localhost resolution issues
            endpoint = self.config['endpoint'].replace('localhost', '127.0.0.1')
            timeout = self.config.get('timeout', 60)
            logger.debug("Endpoint: %s; timeout: %s", endpoint, timeout)
            
            # Enhanced logging based on configuration
            logging_config = self.config_manager.config.get('logging', {})
            
            if logging_config.get('log_request_details', False):
                # Log exact request payload being sent (truncated image data for readability)
                payload_debug = payload.copy()
                if 'images' in payload_debug and payload_debug['images']:
                    payload_debug['images'] = [f"<base64_image_data_length:{len(payload_debug['images'][0])}>"]
                logger.info("🔄 REQUEST: %s", json.dumps(payload_debug, indent=2))
                logger.info("🌐 ENDPOINT: %s", endpoint)
                logger.info("⏱️ TIMEOUT: %ss", timeout)

            # Make request with performance tracking
            request_start = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=timeout
            )
            request_duration = time.time() - request_start
            
            # Enhanced response logging
            response_text = response.text
            
            if logging_config.get('log_request_details', False):
                logger.info("📥 RESPONSE STATUS: %s", response.status_code)
                logger.info("📊 RESPONSE TIME: %.3fs", request_duration)
                logger.info("📄 RESPONSE SIZE: %d bytes", len(response_text))
                
                # Log response headers if interesting
                content_type = response.headers.get('content-type', 'unknown')
                logger.info("📋 CONTENT-TYPE: %s", content_type)
                
                # Log response preview
                if logging_config.get('show_responses', False):
                    logger.info("📝 RESPONSE BODY: %s", response_text[:1000])
                else:
                    logger.info("📝 RESPONSE PREVIEW: %s", response_text[:200])
            
            response.raise_for_status()

            result = response.json()
            alt_text = result.get("response", "").strip()
            
            total_time = time.time() - start_time
            metadata['generation_time'] = total_time
            metadata['request_time'] = request_duration
            metadata['processing_time'] = total_time - request_duration
            metadata['success'] = bool(alt_text)
            
            # Performance logging
            if logging_config.get('log_performance', False):
                logger.info("⚡ PERFORMANCE BREAKDOWN:")
                logger.info("  🌐 Request time: %.3fs", request_duration)
                logger.info("  🔄 Processing time: %.3fs", total_time - request_duration)
                logger.info("  📊 Total time: %.3fs", total_time)
                if alt_text:
                    chars_per_sec = len(alt_text) / total_time if total_time > 0 else 0
                    logger.info("  📝 Generation rate: %.1f chars/sec", chars_per_sec)
            
            # Log successful generation
            if alt_text:
                logger.info("✅ Generated ALT text (%.3fs): %s", total_time, alt_text[:100])
            else:
                logger.warning("⚠️ No ALT text generated despite successful response")
            
            return alt_text if alt_text else None, metadata
            
        except requests.exceptions.RequestException as e:
            metadata['generation_time'] = time.time() - start_time
            metadata['error'] = str(e)
            status_code = getattr(e.response, 'status_code', None)
            if status_code is not None:
                metadata['status_code'] = status_code
            text_preview = None
            if response_text:
                max_length = 1000
                text_preview = response_text[:max_length]
                if len(response_text) > max_length:
                    text_preview += "..."
            logger.error(
                "HTTP request to %s failed with status %s: %s\nResponse text: %s",
                endpoint,
                status_code,
                e,
                text_preview,
                exc_info=True,
            )
            return None, metadata
        except Exception as e:
            metadata['generation_time'] = time.time() - start_time
            metadata['error'] = str(e)
            logger.error(
                "Error with %s: %s", self.provider_name, e, exc_info=True
            )
            return None, metadata


class FlexibleAltGenerator:
    """
    Flexible ALT text generator with configurable provider chains.
    Supports fallbacks, cost tracking, and easy addition of new models.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """Initialize with configuration and set up provider chain."""
        self.config_manager = config_manager or ConfigManager()
        self.providers = {}
        self.fallback_chain = []
        # Detailed failure tracking for smart recovery
        self.provider_failures: Dict[str, Dict[str, Any]] = {}
        self.usage_stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'total_cost': 0.0,
            'provider_usage': {},
            'daily_cost': 0.0,
            'daily_requests': 0
        }

        self._last_provider: Optional[BaseAltProvider] = None
        self._last_image_path: Optional[str] = None

        provider_settings = self.config_manager.config.get('provider_settings', {})

        # Initialize providers and fallback chain
        self._initialize_providers()
        self._setup_cost_tracking()

    def _initialize_providers(self):
        """Initialize all configured providers."""
        providers_config = self.config_manager.config.get('ai_providers', {})
        provider_definitions = providers_config.get('providers', {})

        # Get fallback chain
        self.fallback_chain = providers_config.get('fallback_chain', ['llava'])

        # Initialize all defined providers
        for provider_name, provider_config in provider_definitions.items():
            if not provider_config.get('enabled', True):
                logger.info(f"Provider {provider_name} is disabled, skipping")
                continue

            try:
                provider_type = provider_config.get('type', 'unknown')

                if provider_type == 'llava':
                    provider_instance = LLaVAProvider(
                        provider_name, provider_config, self.config_manager
                    )
                else:
                    logger.warning(f"Unknown provider type: {provider_type} for {provider_name}")
                    continue

                self.providers[provider_name] = provider_instance
                logger.info(f"Initialized provider: {provider_name} ({provider_type})")
                self.usage_stats['provider_usage'][provider_name] = {
                    'requests': 0,
                    'successes': 0,
                    'total_cost': 0.0,
                    'avg_response_time': 0.0
                }

            except Exception as e:
                logger.error(f"Failed to initialize provider {provider_name}: {e}")
                continue

        if not self.providers:
            raise RuntimeError("No providers could be initialized")

        logger.info(f"Initialized {len(self.providers)} providers: {list(self.providers.keys())}")
    
    def _setup_cost_tracking(self):
        """Set up cost tracking and budget monitoring."""
        self.cost_config = self.config_manager.config.get('cost_tracking', {})
        if self.cost_config.get('enabled', False):
            logger.info("Cost tracking enabled")
    
    def set_prompt_type(self, prompt_type: str):
        """Set prompt type for all providers."""
        for provider in self.providers.values():
            provider.set_prompt_type(prompt_type)

    def generate_alt_text(self, image_path: str,
                         prompt_type: Optional[str] = None,
                         context: Optional[str] = None,
                         custom_prompt: Optional[str] = None,
                         force_provider: Optional[str] = None,
                         return_metadata: bool = False) -> Optional[str]:
        """
        Generate ALT text using the provider fallback chain.
        
        Args:
            image_path: Path to image file
            prompt_type: Type of prompt to use
            context: Additional context
            custom_prompt: Custom prompt override
            force_provider: Force use of specific provider
            return_metadata: If True, return (alt_text, metadata) tuple
            
        Returns:
            Generated ALT text or None if all providers fail
            If return_metadata=True, returns (alt_text, metadata) tuple
        """
        self.usage_stats['total_requests'] += 1
        self.usage_stats['daily_requests'] += 1
        
        # Build prompt
        if custom_prompt:
            prompt = custom_prompt
        else:
            use_prompt_type = prompt_type or 'default'
            prompt = self.config_manager.get_prompt(use_prompt_type, context)
        
        # Determine which providers to try with smart retry logic
        if force_provider:
            if force_provider not in self.providers:
                logger.error(f"Forced provider {force_provider} not available")
                return None if not return_metadata else (None, {"error": "Provider not available"})
            providers_to_try = [force_provider]
        else:
            providers_to_try = [p for p in self.fallback_chain if p in self.providers]
        
        # Try providers in order
        max_attempts = self.config_manager.config.get('provider_settings', {}).get('max_fallback_attempts', 3)
        attempts = 0
        final_metadata = {"attempts": [], "successful_provider": None}
        
        for provider_name in providers_to_try:
            if attempts >= max_attempts:
                break

            # Check if provider should be retried based on smart recovery logic
            if not self._should_retry_provider(provider_name):
                failure_info = self.provider_failures.get(provider_name, {})
                next_retry = failure_info.get('next_retry_time', 0)
                wait_time = max(0, int(next_retry - time.time()))
                logger.info(
                    f"Provider {provider_name} in backoff period. "
                    f"Next retry in {wait_time}s. Skipping for now."
                )
                continue

            attempts += 1
            provider = self.providers[provider_name]

            logger.info(f"Attempting ALT text generation with {provider_name} (attempt {attempts})")

            try:
                result, metadata = provider.generate_alt_text(image_path, prompt)

                # Add attempt info to final metadata
                final_metadata["attempts"].append({
                    "provider": provider_name,
                    "model": metadata.get("model", "unknown"),
                    "success": metadata.get("success", False),
                    "error": metadata.get("error"),
                    "generation_time": metadata.get("generation_time", 0),
                    "cost_estimate": metadata.get("cost_estimate", 0),
                    "tokens_used": metadata.get("tokens_used", 0)
                })

                # Update usage statistics
                self._update_usage_stats(provider_name, metadata)

                if result:
                    self.usage_stats['successful_requests'] += 1
                    final_metadata["successful_provider"] = provider_name
                    final_metadata["successful_model"] = metadata.get("model", "unknown")

                    logger.info(f"✅ Successfully generated ALT text with {provider_name} ({metadata.get('model', 'unknown')})")

                    # Record success to reset failure state
                    self._record_success(provider_name)

                    # Apply post-processing if configured
                    self._last_provider = provider
                    self._last_image_path = image_path
                    result = self._post_process_alt_text(result)

                    if return_metadata:
                        return result, final_metadata
                    else:
                        return result
                else:
                    error_message = metadata.get("error", "No result returned")
                    status_code = metadata.get("status_code")
                    # Create a mock exception for failure recording
                    mock_error = Exception(error_message)
                    self._record_failure(provider_name, mock_error, status_code)
                    logger.warning(
                        f"Provider {provider_name} returned no result: {error_message}"
                    )

            except Exception as e:
                err_meta = {"error": str(e)}
                status_code = None
                if hasattr(e, "response") and getattr(e.response, "status_code", None):
                    status_code = e.response.status_code
                    err_meta["status_code"] = status_code
                
                # Record failure with smart recovery logic
                self._record_failure(provider_name, e, status_code)
                
                logger.error(f"Provider {provider_name} failed: {str(e)}")
                final_metadata["attempts"].append({
                    "provider": provider_name,
                    "model": "unknown",
                    "success": False,
                    "error": str(e),
                    "generation_time": 0,
                    "cost_estimate": 0,
                    "tokens_used": 0
                })
                continue
        
        logger.error(f"❌ All providers failed for image: {image_path}")
        final_metadata["successful_provider"] = None

        if return_metadata:
            return None, final_metadata
        else:
            return None

    def _classify_failure(self, error: Exception, status_code: Optional[int] = None) -> str:
        """
        Classify failure as temporary or permanent to determine retry strategy.
        
        Returns:
            'temporary' for retryable failures, 'permanent' for non-retryable failures
        """
        # Check for permanent failures first
        if status_code == 404:
            return 'permanent'  # Model not found
            
        if status_code in [401, 403]:
            return 'permanent'  # Authentication/authorization errors
            
        # Check error message for permanent indicators
        error_str = str(error).lower()
        permanent_indicators = [
            'model not found',
            'invalid model',
            'authentication failed',
            'unauthorized',
            'forbidden'
        ]
        
        for indicator in permanent_indicators:
            if indicator in error_str:
                return 'permanent'
                
        # Temporary failure indicators
        temporary_indicators = [
            'connection refused',
            'timeout',
            'server error', 
            'model runner stopped',
            'service unavailable'
        ]
        
        # Check for server errors (5xx)
        if status_code and 500 <= status_code < 600:
            return 'temporary'
            
        # Check error message for temporary indicators
        for indicator in temporary_indicators:
            if indicator in error_str:
                return 'temporary'
                
        # Default to temporary for unknown errors to allow retry
        return 'temporary'
    
    def _calculate_backoff(self, attempt_count: int) -> int:
        """
        Calculate exponential backoff delay in seconds.
        Pattern: 1s, 2s, 4s, 8s, 16s, then cap at 60s
        """
        base_delay = 1
        max_delay = 60
        delay = base_delay * (2 ** (attempt_count - 1))
        return min(delay, max_delay)
    
    def _should_retry_provider(self, provider_name: str) -> bool:
        """
        Check if a provider should be retried based on failure history.
        """
        if provider_name not in self.provider_failures:
            return True
            
        failure_info = self.provider_failures[provider_name]
        
        # Don't retry permanent failures
        if failure_info.get('failure_type') == 'permanent':
            return False
            
        # Check if backoff period has expired
        next_retry_time = failure_info.get('next_retry_time', 0)
        current_time = time.time()
        
        if current_time >= next_retry_time:
            return True
            
        # Check circuit breaker - stop after too many consecutive failures
        max_consecutive_failures = 5
        if failure_info.get('consecutive_failures', 0) >= max_consecutive_failures:
            # Allow retry after extended break (10 minutes)
            extended_break = 600
            last_failure_time = failure_info.get('last_failure_time', 0)
            if current_time - last_failure_time >= extended_break:
                logger.info(f"Circuit breaker reset for {provider_name} after extended break")
                return True
            return False
            
        return False
    
    def _record_failure(self, provider_name: str, error: Exception, status_code: Optional[int] = None):
        """Record detailed failure information for smart recovery."""
        current_time = time.time()
        failure_type = self._classify_failure(error, status_code)
        
        if provider_name not in self.provider_failures:
            self.provider_failures[provider_name] = {
                'consecutive_failures': 0,
                'total_failures': 0,
                'first_failure_time': current_time
            }
            
        failure_info = self.provider_failures[provider_name]
        failure_info['consecutive_failures'] += 1
        failure_info['total_failures'] += 1
        failure_info['last_failure_time'] = current_time
        failure_info['last_error'] = str(error)
        failure_info['failure_type'] = failure_type
        failure_info['last_status_code'] = status_code
        
        # Calculate next retry time based on exponential backoff
        if failure_type == 'temporary':
            backoff_delay = self._calculate_backoff(failure_info['consecutive_failures'])
            failure_info['next_retry_time'] = current_time + backoff_delay
            logger.warning(
                f"Provider {provider_name} failed (attempt {failure_info['consecutive_failures']}). "
                f"Next retry in {backoff_delay}s: {error}"
            )
        else:
            logger.error(
                f"Provider {provider_name} permanently failed: {error}. "
                f"Manual intervention required."
            )
    
    def _record_success(self, provider_name: str):
        """Clear failure state on successful generation."""
        if provider_name in self.provider_failures:
            failure_info = self.provider_failures[provider_name]
            if failure_info.get('consecutive_failures', 0) > 0:
                logger.info(f"Provider {provider_name} recovered after {failure_info['consecutive_failures']} failures")
            
            # Reset consecutive failures but keep total failure stats
            failure_info['consecutive_failures'] = 0
            failure_info['last_success_time'] = time.time()
            
            # Remove retry restrictions
            failure_info.pop('next_retry_time', None)
            failure_info.pop('failure_type', None)
    
    def reset_failed_providers(self):
        """Clear the record of failed providers so they can be retried."""
        self.provider_failures.clear()
        logger.info("Failed provider cache cleared")
    
    def _update_usage_stats(self, provider_name: str, metadata: Dict[str, Any]):
        """Update usage statistics and cost tracking."""
        stats = self.usage_stats['provider_usage'][provider_name]
        stats['requests'] += 1
        
        if metadata.get('success', False):
            stats['successes'] += 1
            
        # Update cost tracking
        cost = metadata.get('cost_estimate', 0.0)
        if cost > 0:
            stats['total_cost'] += cost
            self.usage_stats['total_cost'] += cost
            self.usage_stats['daily_cost'] += cost
            
            # Check budget alerts
            self._check_budget_alerts()
        
        # Update response time
        response_time = metadata.get('generation_time', 0.0)
        current_avg = stats['avg_response_time']
        stats['avg_response_time'] = (current_avg * (stats['requests'] - 1) + response_time) / stats['requests']
        
        # Log usage if enabled
        if self.cost_config.get('log_token_usage', False):
            tokens = metadata.get('tokens_used', 0)
            logger.info(f"{provider_name}: {tokens} tokens, ${cost:.4f}, {response_time:.2f}s")
    
    def _check_budget_alerts(self):
        """Check if budget limits are exceeded."""
        daily_limit = self.cost_config.get('daily_budget_alert', 0)
        monthly_limit = self.cost_config.get('monthly_budget_alert', 0)
        
        if daily_limit > 0 and self.usage_stats['daily_cost'] > daily_limit:
            logger.warning(f"Daily budget alert: ${self.usage_stats['daily_cost']:.2f} > ${daily_limit:.2f}")
            
        if monthly_limit > 0 and self.usage_stats['total_cost'] > monthly_limit:
            logger.warning(f"Monthly budget alert: ${self.usage_stats['total_cost']:.2f} > ${monthly_limit:.2f}")
    
    def _post_process_alt_text(self, alt_text: str) -> str:
        """Apply post-processing to generated ALT text."""
        # Apply smart truncation if configured
        output_config = self.config_manager.get_output_config()
        if output_config.get("smart_truncate", False):
            max_words = output_config.get("max_summary_words", 30)
            needs_summary = len(alt_text.split()) > max_words or alt_text.strip().endswith("...")
            if needs_summary:
                prompt = self.config_manager.get_smart_truncate_prompt()
                provider = getattr(self, "_last_provider", None)
                image_path = getattr(self, "_last_image_path", None)
                if provider and image_path:
                    try:
                        summary_prompt = f"{prompt}\n\n{alt_text}"
                        summary, _ = provider.generate_alt_text(image_path, summary_prompt)
                        if summary:
                            alt_text = summary.strip()
                        else:
                            alt_text = self._summarize_text_to_sentence(alt_text, max_words)
                    except Exception as e:
                        logger.warning(f"Smart truncation via provider failed: {e}")
                        alt_text = self._summarize_text_to_sentence(alt_text, max_words)
                else:
                    alt_text = self._summarize_text_to_sentence(alt_text, max_words)

        # Apply cleaning if configured
        alt_handling = self.config_manager.config.get('alt_text_handling', {})
        if alt_handling.get('clean_generated_alt_text', True):
            try:
                from alt_cleaner import clean_alt_text
                alt_text = clean_alt_text(alt_text)
            except ImportError:
                logger.warning("alt_cleaner module not found, skipping text cleaning")
        
        return alt_text
    
    def _summarize_text_to_sentence(self, text: str, max_words: int = 30) -> str:
        """Truncate text to a complete sentence within word limit."""
        words = text.strip().split()
        if len(words) <= max_words:
            return text.strip()
        
        # Try to cut at sentence end within limit
        sentence_endings = [m.end() for m in re.finditer(r'\.', text)]
        for end in sentence_endings:
            candidate = text[:end].strip()
            if len(candidate.split()) <= max_words:
                return candidate
        
        # Fallback: truncate at word boundary
        truncated = ' '.join(words[:max_words])
        return truncated.rstrip() + '...'
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get comprehensive usage statistics."""
        return {
            'providers_available': list(self.providers.keys()),
            'fallback_chain': self.fallback_chain,
            'usage_statistics': self.usage_stats,
            'cost_tracking_enabled': self.cost_config.get('enabled', False),
            'provider_failures': self.provider_failures
        }
    
    def get_failure_status(self) -> Dict[str, Any]:
        """Get detailed failure status for all providers."""
        status = {}
        current_time = time.time()
        
        for provider_name in self.providers.keys():
            if provider_name in self.provider_failures:
                failure_info = self.provider_failures[provider_name]
                next_retry = failure_info.get('next_retry_time', 0)
                wait_time = max(0, int(next_retry - current_time))
                
                status[provider_name] = {
                    'status': 'failed' if failure_info.get('failure_type') == 'permanent' else 'backing_off',
                    'consecutive_failures': failure_info.get('consecutive_failures', 0),
                    'total_failures': failure_info.get('total_failures', 0),
                    'last_error': failure_info.get('last_error', ''),
                    'failure_type': failure_info.get('failure_type', ''),
                    'next_retry_in_seconds': wait_time,
                    'can_retry_now': self._should_retry_provider(provider_name)
                }
            else:
                status[provider_name] = {
                    'status': 'healthy',
                    'consecutive_failures': 0,
                    'can_retry_now': True
                }
                
        return status
    
    def _create_test_image(self) -> str:
        """Create a small test image encoded as base64."""
        # Create a minimal PNG image (1x1 red pixel) for testing
        # PNG header + IHDR + IDAT + IEND
        png_data = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChAGA'
            'GUlElgAAAABJRU5ErkJggg=='
        )
        return base64.b64encode(png_data).decode('utf-8')
    
    def _log_system_state(self):
        """Log current system state for debugging."""
        if not self.config_manager.config.get('logging', {}).get('log_system_state', False):
            return
            
        try:
            # System information
            logger.info("=== SYSTEM STATE ===")
            logger.info(f"Platform: {platform.system()} {platform.release()}")
            logger.info(f"Python: {platform.python_version()}")
            
            # Resource usage
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            logger.info(f"Memory: {memory.percent:.1f}% used ({memory.available / 1024**3:.1f}GB available)")
            logger.info(f"Disk: {disk.percent:.1f}% used ({disk.free / 1024**3:.1f}GB available)")
            
            # CPU info
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)
            logger.info(f"CPU: {cpu_count} cores, {cpu_percent:.1f}% usage")
            
        except Exception as e:
            logger.warning(f"Could not log system state: {e}")
    
    def _log_configuration(self):
        """Log current configuration for debugging."""
        if not self.config_manager.config.get('logging', {}).get('log_configuration', False):
            return
            
        logger.info("=== CONFIGURATION ===")
        
        # Provider configuration
        providers_config = self.config_manager.config.get('ai_providers', {})
        for provider_name, provider_config in providers_config.get('providers', {}).items():
            if provider_config.get('enabled', True):
                logger.info(f"Provider {provider_name}:")
                logger.info(f"  Model: {provider_config.get('model', 'unknown')}")
                logger.info(f"  Endpoint: {provider_config.get('endpoint', 'unknown')}")
                logger.info(f"  Timeout: {provider_config.get('timeout', 'default')}s")
        
        # Fallback chain
        fallback_chain = providers_config.get('fallback_chain', [])
        logger.info(f"Fallback chain: {fallback_chain}")
        
        # Performance settings
        provider_settings = self.config_manager.config.get('provider_settings', {})
        logger.info(f"Max attempts: {provider_settings.get('max_fallback_attempts', 3)}")
        logger.info(f"Fail fast: {provider_settings.get('fail_fast', False)}")
    
    def _test_ollama_connectivity(self) -> Dict[str, Any]:
        """Test basic Ollama connectivity."""
        import requests
        
        result = {
            'test': 'ollama_connectivity',
            'success': False,
            'details': {},
            'error': None,
            'duration': 0
        }
        
        try:
            start_time = time.time()
            
            # Get the LLaVA provider config
            llava_config = self.config_manager.config.get('ai_providers', {}).get('providers', {}).get('llava', {})
            if not llava_config:
                raise Exception("LLaVA provider not configured")
                
            # Extract base URL from endpoint
            endpoint = llava_config['endpoint']
            base_url = endpoint.replace('/api/generate', '')
            tags_url = f"{base_url}/api/tags"
            
            logger.info(f"Testing Ollama connectivity at {tags_url}")
            
            # Test basic connectivity
            response = requests.get(tags_url, timeout=10)
            response.raise_for_status()
            
            result['duration'] = time.time() - start_time
            result['details']['status_code'] = response.status_code
            result['details']['endpoint'] = tags_url
            
            # Parse model list
            models_data = response.json()
            models = [model['name'] for model in models_data.get('models', [])]
            result['details']['available_models'] = models
            
            # Check if our model is available
            expected_model = llava_config['model']
            model_available = any(expected_model in model for model in models)
            result['details']['expected_model'] = expected_model
            result['details']['model_available'] = model_available
            
            if not model_available:
                raise Exception(f"Required model '{expected_model}' not found in available models: {models}")
            
            result['success'] = True
            logger.info(f"✅ Ollama connectivity test passed ({result['duration']:.2f}s)")
            logger.info(f"Available models: {models}")
            
        except Exception as e:
            result['error'] = str(e)
            result['duration'] = time.time() - start_time
            logger.error(f"❌ Ollama connectivity test failed: {e}")
            
        return result
    
    def _test_model_generation(self) -> Dict[str, Any]:
        """Test actual image generation with a small sample."""
        result = {
            'test': 'model_generation',
            'success': False,
            'details': {},
            'error': None,
            'duration': 0
        }
        
        try:
            start_time = time.time()
            
            # Get pre-flight config
            pre_flight_config = self.config_manager.config.get('pre_flight', {})
            test_prompt = pre_flight_config.get('test_prompt', 'Describe this test image.')
            
            # Create or use test image
            sample_image_path = pre_flight_config.get('sample_image_path')
            if sample_image_path and Path(sample_image_path).exists():
                with open(sample_image_path, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
                result['details']['image_source'] = 'file'
                result['details']['image_path'] = sample_image_path
            else:
                image_data = self._create_test_image()
                result['details']['image_source'] = 'generated'
            
            result['details']['image_size_bytes'] = len(base64.b64decode(image_data))
            result['details']['test_prompt'] = test_prompt
            
            logger.info(f"Testing model generation with {result['details']['image_source']} image")
            
            # Test generation directly with LLaVA provider
            if 'llava' not in self.providers:
                raise Exception("LLaVA provider not available")
            
            llava_provider = self.providers['llava']
            alt_text, generation_metadata = llava_provider.generate_alt_text(
                image_path="",
                prompt=test_prompt,
                image_data=image_data
            )
            
            result['details']['provider_metadata'] = generation_metadata
            
            result['duration'] = time.time() - start_time
            result['details']['response_length'] = len(alt_text) if alt_text else 0
            result['details']['generated_text'] = alt_text[:100] + "..." if alt_text and len(alt_text) > 100 else alt_text
            
            if alt_text and alt_text.strip():
                result['success'] = True
                logger.info(f"✅ Model generation test passed ({result['duration']:.2f}s)")
                logger.info(f"Generated text: {alt_text}")
            else:
                raise Exception("No text generated by model")
                
        except Exception as e:
            result['error'] = str(e)
            result['duration'] = time.time() - start_time
            logger.error(f"❌ Model generation test failed: {e}")
            
        return result
    
    def run_pre_flight_tests(self) -> Dict[str, Any]:
        """Run comprehensive pre-flight tests to validate LLaVA connectivity."""
        pre_flight_config = self.config_manager.config.get('pre_flight', {})
        
        if not pre_flight_config.get('enabled', True):
            logger.info("Pre-flight tests disabled in configuration")
            return {'enabled': False, 'tests': []}
        
        logger.info("🚀 Starting pre-flight connectivity tests...")
        
        # Log system state and configuration
        self._log_system_state()
        self._log_configuration()
        
        overall_start = time.time()
        test_results = {
            'enabled': True,
            'overall_success': False,
            'total_duration': 0,
            'tests': [],
            'summary': {}
        }
        
        # Test 1: Basic Ollama connectivity
        logger.info("Test 1/2: Ollama connectivity...")
        connectivity_result = self._test_ollama_connectivity()
        test_results['tests'].append(connectivity_result)
        
        # Test 2: Model generation (only if connectivity passed)
        if connectivity_result['success']:
            logger.info("Test 2/2: Model generation...")
            generation_result = self._test_model_generation()
            test_results['tests'].append(generation_result)
        else:
            logger.warning("Skipping model generation test due to connectivity failure")
            test_results['tests'].append({
                'test': 'model_generation',
                'success': False,
                'error': 'Skipped due to connectivity failure',
                'duration': 0
            })
        
        # Calculate overall results
        test_results['total_duration'] = time.time() - overall_start
        test_results['overall_success'] = all(test['success'] for test in test_results['tests'])
        
        # Create summary
        passed_tests = [test['test'] for test in test_results['tests'] if test['success']]
        failed_tests = [test['test'] for test in test_results['tests'] if not test['success']]
        
        test_results['summary'] = {
            'total_tests': len(test_results['tests']),
            'passed': len(passed_tests),
            'failed': len(failed_tests),
            'passed_tests': passed_tests,
            'failed_tests': failed_tests
        }
        
        # Log results
        if test_results['overall_success']:
            logger.info(f"🎉 All pre-flight tests passed! ({test_results['total_duration']:.2f}s total)")
        else:
            logger.error(f"💥 Pre-flight tests failed! Passed: {passed_tests}, Failed: {failed_tests}")
            
            # Show detailed failure information
            for test in test_results['tests']:
                if not test['success']:
                    logger.error(f"  {test['test']}: {test.get('error', 'Unknown error')}")
        
        # Log performance baseline
        if test_results['overall_success']:
            baseline_threshold = pre_flight_config.get('performance_baseline_threshold', 10.0)
            total_time = test_results['total_duration']
            
            if total_time > baseline_threshold:
                logger.warning(f"Performance warning: Pre-flight took {total_time:.2f}s (threshold: {baseline_threshold}s)")
            else:
                logger.info(f"Performance: Pre-flight completed in {total_time:.2f}s (within {baseline_threshold}s threshold)")
        
        return test_results
    
    def reset_daily_stats(self):
        """Reset daily usage statistics (call this daily)."""
        self.usage_stats['daily_cost'] = 0.0
        self.usage_stats['daily_requests'] = 0
        logger.info("Daily usage statistics reset")
    
    def get_provider_performance(self) -> Dict[str, Any]:
        """Get performance metrics for each provider."""
        performance = {}
        for provider_name, stats in self.usage_stats['provider_usage'].items():
            if stats['requests'] > 0:
                success_rate = stats['successes'] / stats['requests']
                avg_cost_per_request = stats['total_cost'] / stats['requests'] if stats['total_cost'] > 0 else 0
                
                performance[provider_name] = {
                    'success_rate': success_rate,
                    'avg_response_time': stats['avg_response_time'],
                    'avg_cost_per_request': avg_cost_per_request,
                    'total_requests': stats['requests'],
                    'total_cost': stats['total_cost']
                }
        
        return performance

    def generate_text_response(self, prompt: str) -> Optional[str]:
        """
        Generate text response without an image (text-only generation).
        For shape elements and other non-image visual elements.
        
        Args:
            prompt: Text prompt for generation
            
        Returns:
            Generated text response or None if generation failed
        """
        try:
            # Use the first available provider for text generation
            # Most providers can handle text-only prompts
            for provider_name in self.fallback_chain:
                if provider_name not in self.providers:
                    continue
                    
                provider = self.providers[provider_name]
                
                # For text-only generation, create a minimal "image" or use provider's text capability
                # Since most vision models can also do text generation, we can send a text prompt
                try:
                    if hasattr(provider, 'generate_text_response'):
                        # If provider has dedicated text method, use it
                        result, metadata = provider.generate_text_response(prompt)
                        if result and result.strip():
                            return result.strip()
                    else:
                        # For LLaVA and similar vision models, we can't do text-only generation
                        # Instead, provide a basic descriptive text based on the prompt
                        logger.debug(f"Provider {provider_name} doesn't support text-only generation")
                        continue
                            
                except Exception as e:
                    logger.debug(f"Provider {provider_name} failed text generation: {e}")
                    continue
            
            # If all providers fail, create a descriptive fallback using prompt information
            logger.warning("All providers failed for text generation, creating fallback description")
            
            # Extract detailed information from the prompt to create a descriptive fallback
            if "shape:" in prompt.lower():
                return self._create_shape_fallback_from_prompt(prompt)
            elif "chart" in prompt.lower():
                return "Chart or graph element"
            elif "text" in prompt.lower():
                return "Text element"
            elif "diagram" in prompt.lower():
                return "Diagram or visual element"
            else:
                return "Visual element"
            
        except Exception as e:
            logger.error(f"Error in generate_text_response: {e}")
            return None
    
    def _create_shape_fallback_from_prompt(self, prompt: str) -> str:
        """
        Create descriptive fallback ALT text for shapes by parsing the prompt information.
        Replaces generic 'PowerPoint shape element' with descriptive text.
        
        Args:
            prompt: The original prompt containing shape information
            
        Returns:
            Descriptive ALT text for the shape
        """
        try:
            # Extract shape description from prompt (format: "Shape: A [element_type] sized WxH pixels...")
            shape_info = ""
            if "shape:" in prompt.lower():
                # Find the line that starts with "Shape:"
                lines = prompt.split('\n')
                for line in lines:
                    if line.strip().lower().startswith('shape:'):
                        shape_info = line.strip()[6:].strip()  # Remove "Shape:" prefix
                        break
            
            if not shape_info:
                return "PowerPoint shape element"
            
            # Parse information from shape description
            shape_type = "shape"
            dimensions = ""
            is_line_type = False
            
            # Extract element type (e.g., "A text_box", "A line", "A auto_shape", "A connector")
            # Handle both " a " (space-separated) and starting with "a " patterns
            shape_info_lower = shape_info.lower()
            if shape_info_lower.startswith("a "):
                # Pattern: "A connector sized..." -> get "connector"
                type_part = shape_info_lower.split()[1]  # Get second word
            elif " a " in shape_info_lower:
                # Pattern: "...contains a text_box..." -> get "text_box" 
                parts = shape_info_lower.split(" a ", 1)
                if len(parts) > 1:
                    type_part = parts[1].split()[0]
            else:
                type_part = None
                
            if type_part:
                # Clean up the type name
                if type_part == "text_box":
                    shape_type = "text box"
                elif type_part == "auto_shape":
                    shape_type = "shape"
                elif type_part == "connector":
                    shape_type = "line"  # Connectors are lines
                    is_line_type = True
                elif type_part == "line":
                    shape_type = "line"
                    is_line_type = True
                else:
                    shape_type = type_part.replace('_', ' ')
            
            # Extract dimensions (pattern: "sized 123x456 pixels" or "123x456 pixels")
            import re
            dimension_pattern = r'(\d+)x(\d+)\s*pixels?'
            match = re.search(dimension_pattern, shape_info, re.IGNORECASE)
            if match:
                width, height = match.groups()
                dimensions = f"({width}x{height}px)"
                
                # Determine line orientation for lines
                if is_line_type and width and height:
                    width_px = int(width)
                    height_px = int(height)
                    if width_px > height_px * 3:  # Much wider than tall
                        shape_type = "horizontal line"
                    elif height_px > width_px * 3:  # Much taller than wide
                        shape_type = "vertical line"
                    elif abs(width_px - height_px) < min(width_px, height_px) * 0.2:  # Roughly equal
                        shape_type = "diagonal line"
            
            # Create descriptive ALT text
            if dimensions:
                return f"This is a PowerPoint shape. It is a {shape_type} {dimensions}".strip()
            else:
                return f"This is a PowerPoint shape. It is a {shape_type}".strip()
                
        except Exception as e:
            logger.debug(f"Error creating shape fallback from prompt: {e}")
            return "PowerPoint shape element"  # Fallback to generic if parsing fails


# Backwards compatibility functions
def generate_alt_text_unified(image_path: str,
                             prompt: Optional[str] = None,
                             provider: Optional[str] = None,
                             config_manager: Optional[ConfigManager] = None,
                             debug: bool = False) -> Optional[str]:
    """Unified ALT text generation function for backwards compatibility."""
    if debug:
        logger.setLevel(logging.DEBUG)
        
    generator = FlexibleAltGenerator(config_manager)
    return generator.generate_alt_text(
        image_path=image_path,
        custom_prompt=prompt,
        force_provider=provider
    )


# Main entry point for testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        print("Flexible ALT Text Generator Test")
        print("=" * 50)
        
        config_manager = ConfigManager()
        generator = FlexibleAltGenerator(config_manager)
        
        # Show configuration
        stats = generator.get_usage_stats()
        print("\nConfiguration:")
        print(f"  Available providers: {stats['providers_available']}")
        print(f"  Fallback chain: {stats['fallback_chain']}")
        print(f"  Cost tracking: {stats['cost_tracking_enabled']}")
        
        # Test with sample image if available
        test_image = "test_image.jpg"
        if Path(test_image).exists():
            print(f"\nTesting with image: {test_image}")
            
            # Test primary provider
            result = generator.generate_alt_text(test_image)
            print(f"Generated ALT text: {result}")
            
            # Show performance stats
            performance = generator.get_provider_performance()
            print(f"\nProvider Performance:")
            for provider, metrics in performance.items():
                print(f"  {provider}: {metrics['success_rate']:.1%} success, "
                      f"${metrics['avg_cost_per_request']:.4f}/request, "
                      f"{metrics['avg_response_time']:.2f}s avg")
        else:
            print(f"\nTest image not found: {test_image}")
            print("Add a test image to run full functionality test.")
            
    except Exception as e:
        print(f"Error: {e}")
        print("\nPlease ensure your config.yaml includes the required AI provider settings.")
        print("Run with --create-config to generate a sample configuration.")
