import base64
import logging
import time
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from config_manager import ConfigManager

logger = logging.getLogger(__name__)

class LLaVAAltGenerator:
    """Enhanced LLaVA ALT text generator with configuration support."""

    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the generator with optional configuration.

        Args:
            config_manager: ConfigManager instance (creates default if None)
        """
        self.config_manager = config_manager or ConfigManager()
        self.llava_config = self.config_manager.get_llava_config()
        self.active_prompt_type = 'default'

        # Set up logging based on config
        logging_config = self.config_manager.get_logging_config()
        if logging_config['level'] == 'DEBUG':
            logger.setLevel(logging.DEBUG)

    def set_prompt_type(self, prompt_type: str):
        """Set the active prompt type for generation."""
        if prompt_type in self.config_manager.config['prompts']:
            self.active_prompt_type = prompt_type
            logger.info(f"Set prompt type to: {prompt_type}")
        else:
            logger.warning(f"Unknown prompt type: {prompt_type}, using default")
            self.active_prompt_type = 'default'

    def generate_alt_text(self, image_path: str, 
                         prompt_type: Optional[str] = None,
                         context: Optional[str] = None,
                         custom_prompt: Optional[str] = None) -> Optional[str]:
        """
        Generate ALT text for an image using LLaVA with configuration support.

        Args:
            image_path: Path to the image file
            prompt_type: Override prompt type (uses active_prompt_type if None)
            context: Additional context to append to prompt
            custom_prompt: Completely override prompt with custom text

        Returns:
            Generated ALT text or None on error
        """
        start_time = time.time()

        # Get the prompt
        if custom_prompt:
            prompt = custom_prompt
        else:
            use_prompt_type = prompt_type or self.active_prompt_type
            prompt = self.config_manager.get_prompt(use_prompt_type, context)

        # Log prompt if configured
        if self.config_manager.get_logging_config()['show_prompts']:
            logger.debug(f"Prompt: {prompt}")

        try:
            # Read and encode image
            image_file = Path(image_path)
            if not image_file.exists():
                logger.error(f"Image file not found: {image_path}")
                return None

            with open(image_file, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            # Build request payload
            payload = {
                "model": self.llava_config['model'],
                "prompt": prompt,
                "images": [image_data],
                "stream": self.llava_config['stream'],
                "options": {
                    "temperature": self.llava_config.get('temperature', 0.7),
                    "num_predict": self.llava_config['max_tokens']
                }
            }

            # Make request
            response = requests.post(
                self.llava_config['endpoint'],
                json=payload,
                timeout=self.llava_config['timeout']
            )
            response.raise_for_status()

            # Parse response
            result = response.json()
            raw_text = result.get("response", "").strip()

            # Smart truncate if enabled
            output_config = self.config_manager.get_output_config()
            if output_config.get("smart_truncate", False):
                max_words = output_config.get("max_summary_words", 20)
                raw_text = summarize_text_to_sentence(raw_text, max_words)

            # Log response if configured
            if self.config_manager.get_logging_config()['show_responses']:
                logger.debug(f"Response: {raw_text}")

            # Truncate by token limit if needed
            if self.config_manager.get_output_config()['truncate_at_tokens']:
                raw_text = self._truncate_to_tokens(raw_text, self.llava_config['max_tokens'])

            # Log timing if configured
            generation_time = time.time() - start_time
            if self.config_manager.get_output_config()['include_generation_time']:
                logger.info(f"Generation time: {generation_time:.2f}s")

            return raw_text if raw_text else None

        except requests.exceptions.Timeout:
            logger.error(f"Timeout after {self.llava_config['timeout']}s")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            return None
        except Exception as ex:
            logger.error(f"Unexpected error: {ex}")
            return None

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """
        Truncate text to approximately max_tokens.
        Note: This is a simple word-based approximation.
        """
        # Simple approximation: ~1.3 tokens per word
        max_words = int(max_tokens / 1.3)
        words = text.split()

        if len(words) <= max_words:
            return text

        truncated = ' '.join(words[:max_words])
        logger.debug(f"Truncated response from {len(words)} to {max_words} words")
        return truncated + "..."

    def get_stats(self) -> Dict[str, Any]:
        """Get current configuration stats."""
        return {
            'model': self.llava_config['model'],
            'max_tokens': self.llava_config['max_tokens'],
            'active_prompt': self.active_prompt_type,
            'timeout': self.llava_config['timeout']
        }

# Backwards compatibility wrapper
def generate_alt_text_with_llava(image_path: str,
                                 prompt: Optional[str] = None,
                                 model: str = "llava",
                                 config_manager: Optional[ConfigManager] = None,
                                 debug: bool = False) -> Optional[str]:
    """
    Generates ALT text using LLaVA with optional config and prompt.

    Args:
        image_path: Path or bytes of the image
        prompt: Prompt text to use for generation
        model: Optional override for model name
        config: Optional full config dictionary (YAML-parsed)
        debug: Enables debug logging

    Returns:
        ALT text string or None
    """

    # Create generator with provided or default config
    if config_manager:
        generator = LLaVAAltGenerator(config_manager=config_manager)
    else:
        generator = LLaVAAltGenerator()

    # Override model if specified
    if model and model != generator.llava_config.get('model'):
        generator.llava_config['model'] = model

    # Enable debugging if requested
    if debug:
        logger.setLevel(logging.DEBUG)
        generator.config_manager.config['logging']['show_responses'] = True

    # Apply prompt
    if prompt:
        context = prompt
    elif config_manager:
        context = config_manager.get_prompt("concise_summary")
    else:
        context = "Describe this image in a single, complete sentence using no more than 20 words."

    return generator.generate_alt_text(image_path, context=context)

# Example usage and testing
if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test with configuration
    config_manager = ConfigManager()
    generator = LLaVAAltGenerator(config_manager)
    
    # Show available prompts
    print("Available prompt types:")
    for prompt_type in config_manager.config['prompts'].keys():
        print(f"  - {prompt_type}")
    
    # Test with different prompt types
    test_image = "test_image.jpg"  # Replace with actual test image
    
    if Path(test_image).exists():
        # Test different prompt types
        for prompt_type in ['brief_medical', 'student_friendly']:
            print(f"\nTesting {prompt_type}:")
            generator.set_prompt_type(prompt_type)
            result = generator.generate_alt_text(test_image)
            print(f"Result: {result}")
        
        # Test with custom prompt
        print("\nTesting custom prompt:")
        custom = "Describe this image in exactly one sentence."
        result = generator.generate_alt_text(test_image, custom_prompt=custom)
        print(f"Result: {result}")
    else:
        print(f"\nTest image not found: {test_image}")
        print("Creating sample configuration file...")
        config_manager.create_sample_config()

def summarize_text_to_sentence(text: str, max_words: int = 20) -> str:
    """
    Smartly truncate text to a complete sentence within a word limit.

    Args:
        text: Full text to summarize.
        max_words: Max words allowed in output.

    Returns:
        A single-sentence summary or truncated version.
    """
    import re

    words = text.strip().split()
    if len(words) <= max_words:
        return text.strip()

    # Try to cut at full stop within limit
    sentence_endings = [m.end() for m in re.finditer(r'\.', text)]
    for end in sentence_endings:
        candidate = text[:end].strip()
        if len(candidate.split()) <= max_words:
            return candidate

    # If no full stop, just truncate
    truncated = ' '.join(words[:max_words])
    return truncated.rstrip() + '...'
