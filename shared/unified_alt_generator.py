"""
Flexible ALT text generator using a local LLaVA model.
"""

# --- repo/package import bootstrap (top of shared/unified_alt_generator.py) ---
from pathlib import Path as _P
import sys as _sys

# Ensure repo root, core/, and shared/ are importable even if CWD is odd
_REPO = _P(__file__).resolve().parents[1]
for p in (_REPO, _REPO / "core", _REPO / "shared"):
    ps = str(p)
    if ps not in _sys.path:
        _sys.path.insert(0, ps)

# Import perceptual hash utilities
try:
    from .perceptual_hash import build_cache_keys, load_pil_image_safely
except Exception:
    from perceptual_hash import build_cache_keys, load_pil_image_safely

# Prefer package-relative imports; fall back to bare for legacy callers
try:
    from .config_manager import ConfigManager
except Exception:
    from config_manager import ConfigManager  # fallback

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
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# Helper functions for Ollama request handling
import requests

def _b64_of_file(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")

def _make_safe_url(base_url: str, endpoint: str) -> str:
    """Safely join base URL and endpoint, handling both path and full URL endpoints."""
    # If endpoint is already a full URL, return it as-is
    if endpoint and (endpoint.startswith('http://') or endpoint.startswith('https://')):
        return endpoint
    
    # Ensure base_url ends with slash and endpoint doesn't start with slash for urljoin
    base = base_url.rstrip('/') + '/'
    ep = (endpoint or '/api/generate').lstrip('/')
    return urljoin(base, ep)

def _build_prompt_text(custom_prompt: str, context: str) -> str:
    # Simple, safe text prompt. /api/generate must receive a STRING, not an object.
    ctx = (context or "").strip()
    if ctx:
        return f"{custom_prompt.strip()}\n\nContext:\n{ctx}\n\nDescribe the image precisely in one concise sentence."
    return f"{custom_prompt.strip()}\n\nDescribe the image precisely in one concise sentence."

# --- compatibility shim: always call unified via a file path ---
from pathlib import Path
import tempfile, base64
from typing import Any

def _ensure_bytes(image_input: Any) -> bytes:
    if image_input is None:
        return b""
    if isinstance(image_input, (bytes, bytearray)):
        return bytes(image_input)
    # If a file path was passed, read it to bytes
    try:
        from os import PathLike
        if isinstance(image_input, (str, PathLike)):
            return Path(image_input).read_bytes()
    except Exception:
        pass
    # If a base64 string was passed
    if isinstance(image_input, str):
        try:
            return base64.b64decode(image_input, validate=True)
        except Exception:
            return image_input.encode("utf-8", errors="ignore")
    return b""

def generate_alt_text(image_bytes_or_path: Any, cfg: dict, context: str = "") -> str:
    """
    Canonical entrypoint for both PPTX and DOCX processors.
    Guarantees generate_alt_text_unified(...) receives a file path (str).
    """
    data = _ensure_bytes(image_bytes_or_path)

    # Write to a temp file (png by default; your unified code only needs a path)
    # Note: delete=False so we can pass the path and remove it after.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        tmp.write(data)
        tmp.flush()
        tmp_path = tmp.name

    try:
        # Your existing function; it expects a path. If it supports context, pass it.
        try:
            result = generate_alt_text_unified(tmp_path, cfg, context=context)
        except TypeError:
            result = generate_alt_text_unified(tmp_path, cfg)

        s = (str(result or "")).strip()
        if s and s[-1] not in ".!?":
            s += "."
        return s
    finally:
        # Cleanup temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
# --- end shim ---


class BaseAltProvider(ABC):
    """Abstract base class for ALT text providers."""
    
    def __init__(self, provider_name: str, config: Dict[str, Any], config_manager: ConfigManager):
        self.provider_name = provider_name
        self.config = config
        self.config_manager = config_manager
        self.active_prompt_type = 'default'
        
    @abstractmethod
    def generate_alt_text(self, image_path: str, prompt: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Generate ALT text for an image.
        
        Returns:
            Tuple of (generation_result, metadata) where:
            - generation_result: {"status": "ok", "text": "..."} or {"status": "fail", "reason": "..."}
            - metadata includes token usage, cost, etc.
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
    
    def generate_alt_text(self, image_path: str, custom_prompt: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Returns (generation_result, metadata). Must NOT send chat objects to /api/generate.
        """
        # Extract configuration
        base_url = self.config.get('base_url', 'http://127.0.0.1:11434')
        model = self.config.get('model', 'llava:latest')
        endpoint_path = self.config.get('endpoint', '/api/generate')
        
        # Safely build the URL
        full = _make_safe_url(base_url, endpoint_path)
        
        # Log the URL once for debugging (only in debug mode)
        if not hasattr(self, '_url_logged'):
            logger.info(f"LLaVA generate URL: {full}")
            self._url_logged = True

        # Build a plain text prompt; /api/generate only accepts strings
        context = getattr(self, 'context', '') or ''
        prompt_text = _build_prompt_text(custom_prompt, context)
        img_b64 = _b64_of_file(image_path)

        # Deterministic settings for reproducible results
        deterministic_options = {
            "temperature": 0.0,      # Deterministic generation
            "top_p": 1.0,            # No nucleus sampling
            "top_k": 1,              # Always pick most likely token
            "num_predict": 100,      # Limit response length
            "repeat_penalty": 1.0,   # No repetition penalty to avoid randomness
        }
        
        # Add seed if supported (for full determinism)
        seed = self.config.get('seed', 42)
        if seed is not None:
            deterministic_options["seed"] = seed

        # Choose payload shape based on endpoint
        if endpoint_path.endswith("/api/chat"):
            # Chat style expects messages (object), so we use chat format here
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert accessibility captioner."},
                    {"role": "user", "content": prompt_text}
                ],
                # Ollama supports images at top-level with chat as of recent versions;
                # if your version requires images inside message content, move it there accordingly.
                "images": [img_b64],
                "stream": False,
                "options": deterministic_options
            }
        else:
            # /api/generate requires a STRING prompt; images go in a separate array
            payload = {
                "model": model,
                "prompt": prompt_text,   # <-- STRING, not object
                "images": [img_b64],     # base64 strings
                "stream": False,
                "options": deterministic_options
            }

        headers = {"Content-Type": "application/json"}
        retries = self.config.get('retries', 5)
        backoff = self.config.get('retry_backoff_sec', 1.0)
        last_err = None

        start_time = time.time()
        
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(full, data=json.dumps(payload), headers=headers, timeout=60)
                # Raise for HTTP-level errors (400, 500...)
                resp.raise_for_status()
                data = resp.json()

                # Parse response shape: Ollama returns {'response': '...'} for generate,
                # and {'message': {'content': '...'}} for chat.
                if endpoint_path.endswith("/api/chat"):
                    content = (data.get("message") or {}).get("content") or ""
                else:
                    content = data.get("response") or ""

                content = (content or "").strip()
                if not content:
                    raise ValueError("Empty response from provider.")

                # Apply normalization to 1-2 complete sentences (no truncation)
                content = self._normalize_to_complete_sentences(content)
                
                generation_result = {"status": "ok", "text": content}
                    
                meta = {
                    "endpoint": endpoint_path, 
                    "model": model, 
                    "length": len(content),
                    "success": True,
                    "generation_time": time.time() - start_time,
                    "provider": self.provider_name,
                    "tokens_used": 0,
                    "cost_estimate": 0.0
                }
                logger.info("✅ Generated ALT text (%.3fs): %s", meta["generation_time"], content[:100])
                return generation_result, meta

            except requests.HTTPError as e:
                # Log full server response for easier debugging
                txt = e.response.text if getattr(e, "response", None) is not None else ""
                last_err = f"{e} | body: {txt}"
                logger.warning(f"HTTP error (attempt {attempt}/{retries}): {last_err}")
                time.sleep(backoff)
            except Exception as e:
                last_err = str(e)
                logger.warning(f"Request failed (attempt {attempt}/{retries}): {last_err}")
                time.sleep(backoff)

        # All attempts failed
        generation_result = {"status": "fail", "reason": "provider_error"}
        meta = {
            "success": False,
            "error": last_err,
            "generation_time": time.time() - start_time,
            "provider": self.provider_name,
            "endpoint": endpoint_path,
            "model": model
        }
        logger.error(f"LLaVA/Ollama call failed after {retries} attempts: {last_err}")
        return generation_result, meta
    
    def _normalize_to_complete_sentences(self, text: str) -> str:
        """
        Normalize ALT text to 1-2 complete sentences without truncation.
        
        This ensures:
        - No truncated sentences (complete thoughts only)
        - Proper punctuation
        - Maximum 2 sentences for conciseness
        """
        if not text or not text.strip():
            return ""
        
        text = text.strip()
        
        # Split into sentences using common sentence endings
        import re
        sentence_pattern = r'[.!?]+(?:\s|$)'
        sentences = re.split(sentence_pattern, text)
        
        # Filter out empty sentences and clean up
        valid_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(sentence) > 3:  # Minimum meaningful sentence length
                # Ensure sentence starts with capital letter
                if sentence[0].islower():
                    sentence = sentence[0].upper() + sentence[1:]
                valid_sentences.append(sentence)
        
        # Take first 1-2 sentences only
        if len(valid_sentences) >= 2:
            result = valid_sentences[0] + ". " + valid_sentences[1]
        elif len(valid_sentences) == 1:
            result = valid_sentences[0]
        else:
            # Fallback: treat entire text as single sentence
            result = text
        
        # Ensure proper terminal punctuation
        result = result.strip()
        if result and result[-1] not in '.!?':
            result += "."
        
        return result
    
    def _process_image_for_retry(self, image_data: bytes, strategy: dict, image_path: str) -> bytes:
        """
        Process image according to retry strategy (format conversion, resizing, quality adjustment).
        
        Args:
            image_data: Original image data
            strategy: Retry strategy configuration
            image_path: Original image path for logging
            
        Returns:
            Processed image data
        """
        try:
            from PIL import Image
            import io
            
            # First attempt - return original data
            if strategy['format'] == 'PNG' and strategy.get('max_size') is None:
                return image_data
            
            # Load image with PIL
            with io.BytesIO(image_data) as img_buffer:
                img = Image.open(img_buffer)
                
                # Convert to RGB if needed (especially for JPEG output)
                if strategy['format'] == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
                    # Convert transparent images to white background for JPEG
                    if img.mode == 'RGBA':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
                        img = background
                    else:
                        img = img.convert('RGB')
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                
                # Resize if requested
                if strategy.get('max_size'):
                    max_size = strategy['max_size']
                    if max(img.size) > max_size:
                        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                        logger.debug(f"Resized image to {img.size} for retry strategy")
                
                # Save with appropriate format and quality
                output_buffer = io.BytesIO()
                save_kwargs = {'format': strategy['format'], 'optimize': True}
                
                if strategy['format'] == 'JPEG' and strategy.get('quality'):
                    save_kwargs['quality'] = strategy['quality']
                
                img.save(output_buffer, **save_kwargs)
                return output_buffer.getvalue()
                
        except Exception as e:
            logger.warning(f"Image processing failed for retry strategy {strategy}: {e}")
            # Fallback to original data
            return image_data


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
                         return_metadata: bool = False,
                         manifest: Optional['AltManifest'] = None,
                         entry_key: Optional[str] = None) -> Optional[str]:
        """
        Generate ALT text using the provider fallback chain with manifest integration.
        
        Args:
            image_path: Path to image file
            prompt_type: Type of prompt to use
            context: Additional context
            custom_prompt: Custom prompt override
            force_provider: Force use of specific provider
            return_metadata: If True, return (alt_text, metadata) tuple
            manifest: Optional ALT manifest for normalization and caching
            entry_key: Optional manifest entry key for recording results
            
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
                generation_result, metadata = provider.generate_alt_text(image_path, prompt)

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

                if generation_result and generation_result.get("status") == "ok":
                    self.usage_stats['successful_requests'] += 1
                    final_metadata["successful_provider"] = provider_name
                    final_metadata["successful_model"] = metadata.get("model", "unknown")

                    logger.info(f"✅ Successfully generated ALT text with {provider_name} ({metadata.get('model', 'unknown')})")

                    # Record success to reset failure state
                    self._record_success(provider_name)

                    # Apply single-pass normalization with manifest integration
                    raw_result = generation_result.get("text", "")
                    if manifest and entry_key:
                        # Use manifest for sentence-safe normalization
                        normalized_result, was_truncated = manifest.normalize_alt_text(raw_result)
                        
                        # Update manifest entry with generation details
                        entry = manifest.get_entry(entry_key)
                        if entry:
                            entry.llm_raw = raw_result
                            entry.final_alt = normalized_result
                            entry.truncated_flag = was_truncated
                            entry.llava_called = True
                            entry.decision_reason = "generated"
                            entry.duration_ms = metadata.get("generation_time", 0) * 1000
                            entry.provider = provider_name
                            entry.prompt_type = prompt_type or "default"
                            manifest.add_entry(entry)
                        
                        result = normalized_result
                    else:
                        # Apply legacy post-processing if no manifest
                        self._last_provider = provider
                        self._last_image_path = image_path
                        result = self._post_process_alt_text(raw_result)

                    if return_metadata:
                        return result, final_metadata
                    else:
                        return result
                else:
                    # Handle failure cases
                    if generation_result and generation_result.get("status") == "fail":
                        error_message = generation_result.get("reason", "Unknown failure")
                    else:
                        error_message = metadata.get("error", "No result returned")
                    
                    status_code = metadata.get("status_code")
                    # Create a mock exception for failure recording
                    mock_error = Exception(error_message)
                    self._record_failure(provider_name, mock_error, status_code)
                    logger.warning(
                        f"Provider {provider_name} failed: {error_message}"
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
    
    def _ensure_terminal_period(self, text: str) -> str:
        if not text:
            return ""
        t = text.strip()
        return t if t[-1] in ".!?" else t + "."

    def _shrink_to_char_limit(self, text: str, limit: int = 125) -> str:
        t = " ".join(text.split())
        if len(t) <= limit:
            return t
        # prefer cutting at sentence boundary or comma/semicolon near the limit
        cut = limit
        for sep in [". ", "; ", ", "]:
            pos = t.rfind(sep, 0, limit)
            if pos >= 60:  # don't create stubs that are too short
                cut = pos + (1 if sep.strip() == "." else len(sep))
                break
        t = t[:cut].strip(" .;,")
        # if still too long, cut at last space before limit
        if len(t) > limit:
            t = t[:limit].rsplit(" ", 1)[0]
        return self._ensure_terminal_period(t)

    def _normalize_generated_result(self, result) -> str:
        """Normalize generation result to text string, handling dict or str formats."""
        if isinstance(result, dict):
            text = result.get("text", "")
        else:
            text = result or ""
        return str(text).strip()
    
    def _post_process_alt_text(self, alt_text) -> str:
        """Apply post-processing to generated ALT text."""
        # Normalize result first
        alt_text = self._normalize_generated_result(alt_text)
        
        # Apply smart truncation if configured
        output_config = self.config_manager.get_output_config()
        if output_config.get("smart_truncate", False):
            max_words = output_config.get("max_summary_words", 30)
            needs_summary = len(alt_text.split()) > max_words or alt_text.endswith("...")
            if needs_summary:
                prompt = self.config_manager.get_smart_truncate_prompt()
                provider = getattr(self, "_last_provider", None)
                image_path = getattr(self, "_last_image_path", None)
                if provider and image_path:
                    try:
                        summary_prompt = f"{prompt}\n\n{alt_text}"
                        summary, _ = provider.generate_alt_text(image_path, summary_prompt)
                        if summary:
                            alt_text = self._normalize_generated_result(summary)
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
                # Dual-path import for alt_cleaner
                try:
                    from .alt_cleaner import clean_alt_text
                except Exception:
                    from alt_cleaner import clean_alt_text
                alt_text = clean_alt_text(alt_text)
            except ImportError:
                logger.warning("alt_cleaner module not found, skipping text cleaning")

        # NEW: hard character limit + terminal punctuation
        char_limit = self.config_manager.config.get('output', {}).get('char_limit', 125)
        alt_text = self._shrink_to_char_limit(alt_text, char_limit)
        return self._ensure_terminal_period(alt_text)
    
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
                
            # Extract base URL properly
            base_url = llava_config.get('base_url', 'http://127.0.0.1:11434')
            tags_url = _make_safe_url(base_url, '/api/tags')
            
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
                        normalized = self._normalize_generated_result(result)
                        if normalized:
                            return normalized
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
