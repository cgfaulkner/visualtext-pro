"""
Configuration Manager for PowerPoint Accessibility Auditor
Handles loading and managing configuration from YAML/JSON files
"""

import os
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration for the accessibility auditor tool."""

    DEFAULT_CONFIG = {
        "alt_text_handling": {
            "mode": "preserve",
            "max_workers": 4,
            "reuse_for_identical_images": True,
            "clean_generated_alt_text": True,
            "detect_concepts_from_notes": True,
            "concepts_file": "concepts.yaml",
            "concept_injection_style": "prompt_block",
            "vague_output_warning": True,
        },
        "paths": {
            "input_folder": "test_pptx",
            "output_folder": "output",
            "thumbnail_folder": "output/thumbnails",
            "temp_folder": "temp",
            "alt_cache": "alt_cache.json"
        },
        "conversion": {
            "wmf_to_png": True
        },
        "tools": {
            "inkscape": "inkscape"
        },
        "ai_providers": {
            "fallback_chain": ["llava"],
            "providers": {
                "llava": {
                    "type": "llava",
                    "model": "llava",
                    "endpoint": "http://localhost:11434/api/generate",
                    "timeout": 60,
                    "max_tokens": 150,
                    "temperature": 0.7,
                    "stream": False,
                    "retry_attempts": 1,
                    "include_slide_notes": True,
                    "include_slide_text": True
                }
            }
        },
        "provider_settings": {
            "max_fallback_attempts": 3,
            "fail_fast": False,
            "comparison_mode": False,
            "save_provider_performance": True,
        },
        "prompts": {
            "default": "Describe this image in one sentence (up to 125 characters). Focus on essential visual content.",
            "anatomical": "Describe this anatomical image in one sentence (up to 125 characters). Mention key structures and orientations.",
            "diagnostic": "Describe this diagnostic image in one sentence (up to 125 characters). Note the imaging type and key findings.",
            "chart": "Describe this chart or graph in one sentence (up to 125 characters). Include axes, trends, or notable values.",
            "diagram": "Describe this diagram in one sentence (up to 125 characters). Highlight main components and relationships.",
            "clinical_photo": "Describe this clinical photo in one sentence (up to 125 characters). Focus on the visible condition or procedure.",
            "unified_medical": "Describe this medical image in one sentence (up to 125 characters). Provide essential educational information."
        },
        "decorative_overrides": {
            "decorative_rules": {
                "contains": ["logo", "watermark", "border", "divider", "separator"],
                "exact": []
            },
            "force_decorative": ["logo", "watermark", "border", "divider", "separator"],
            "force_decorative_scope": "shape_name",
            "never_decorative": ["anatomy", "pathology", "xray", "mri", "ct", "microscopy", "diagram", "chart", "graph"]
        },
        "output": {
            "thumbnail_max_width": 200,
            "include_token_count": True,
            "include_generation_time": True,
            "truncate_at_tokens": True,
            "smart_truncate": True,
            "smart_truncate_prompt": "Summarize the following text in one complete sentence of no more than 30 words:",
            "max_summary_words": 30
        },
        "logging": {
            "level": "INFO",
            "show_prompts": False,
            "show_responses": False,
            "log_to_file": True
        },
        "reinjection": {
            "skip_alt_text_if": [
                "",
                "undefined",
                "(None)",
                "N/A",
                "Not reviewed",
                "n/a"
            ]
        }
    }
    
    # Required configuration paths for validation
    REQUIRED_PATHS = [
        "paths.input_folder",
        "paths.output_folder",
        "decorative_overrides.decorative_rules.contains",
        "ai_providers.providers.llava.model",
        "ai_providers.providers.llava.endpoint",
        "prompts.default"
    ]
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the configuration manager.
        
        Args:
            config_path: Path to configuration file (YAML or JSON)
                        If None, looks for config.yaml or config.json in current directory
        
        Raises:
            ValueError: If required configuration keys are missing
        """
        self.config_path = self._find_config_file(config_path)
        self.config = self._load_config()
        self._ensure_paths_exist()
        self._validate_config()
        
    def _find_config_file(self, config_path: Optional[str]) -> Optional[Path]:
        """Find configuration file if not explicitly provided."""
        if config_path:
            return Path(config_path)
        
        # Look for config files in order of preference
        search_paths = [
            Path("config.yaml"),
            Path("config.yml"),
            Path("config.json"),
            Path("settings.yaml"),
            Path("settings.json")
        ]
        
        for path in search_paths:
            if path.exists():
                logger.info(f"Found configuration file: {path}")
                return path
        
        logger.info("No configuration file found, using defaults")
        return None
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        if not self.config_path or not self.config_path.exists():
            logger.info("Using default configuration")
            return self.DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                if self.config_path.suffix in ['.yaml', '.yml']:
                    user_config = yaml.safe_load(f)
                else:
                    user_config = json.load(f)
            
            # Merge with defaults (user config overrides defaults)
            config = self._deep_merge(self.DEFAULT_CONFIG.copy(), user_config)
            logger.info(f"Loaded configuration from {self.config_path}")
            return config
            
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            logger.info("Falling back to default configuration")
            return self.DEFAULT_CONFIG.copy()
    
    def _deep_merge(self, base: Dict, update: Dict) -> Dict:
        """Deep merge two dictionaries."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base
    
    def _ensure_paths_exist(self):
        """Create directories specified in paths if they don't exist."""
        paths = self.config.get('paths', {})
        for key, path in paths.items():
            if key.endswith('_folder') and path:
                Path(path).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured directory exists: {path}")
    
    def _validate_config(self):
        """
        Validate configuration has all required keys.
        
        Raises:
            ValueError: If required keys are missing
        """
        missing_keys = []
        
        for path in self.REQUIRED_PATHS:
            keys = path.split('.')
            current = self.config
            
            for i, key in enumerate(keys):
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    missing_keys.append('.'.join(keys[:i+1]))
                    break

        if missing_keys:
            error_msg = f"Missing required configuration keys: {', '.join(missing_keys)}"
            logger.error(error_msg)
            
            # Provide helpful error message
            print("\n❌ Configuration Validation Error!")
            print(f"\nThe following required keys are missing from your configuration:")
            for key in missing_keys:
                print(f"  - {key}")
            
            print("\nPlease ensure your config.yaml file includes these sections.")
            print("You can create a sample config file by running:")
            print("  python config_manager.py")
            
            raise ValueError(error_msg)
        
        # Validate other constraints
        llava_cfg = self.config.setdefault('ai_providers', {}).setdefault('providers', {}).setdefault('llava', {})
        if llava_cfg.get('max_tokens', 0) < 1:
            logger.warning("max_tokens must be positive, setting to 150")
            llava_cfg['max_tokens'] = 150

        if llava_cfg.get('timeout', 0) < 1:
            logger.warning("timeout must be positive, setting to 60")
            llava_cfg['timeout'] = 60
        
        logger.info("Configuration validation passed ✓")
    
    def get_paths(self) -> Dict[str, str]:
        """Get all configured paths."""
        return self.config.get('paths', {}).copy()
    
    def get_input_folder(self) -> str:
        """Get the configured input folder path."""
        return self.config['paths']['input_folder']
    
    def get_output_folder(self) -> str:
        """Get the configured output folder path."""
        return self.config['paths']['output_folder']
    
    def get_thumbnail_folder(self) -> str:
        """Get the configured thumbnail folder path."""
        return self.config['paths'].get('thumbnail_folder', 
                                        os.path.join(self.get_output_folder(), 'thumbnails'))
    
    def get_temp_folder(self) -> str:
        """Get the configured temp folder path."""
        return self.config['paths'].get('temp_folder', 'temp')

    def get_alt_cache_path(self) -> str:
        """Get the configured ALT text cache file path."""
        return self.config['paths'].get('alt_cache', 'alt_cache.json')
    
    def get_prompt(self, prompt_type: str = 'default', context: Optional[str] = None) -> str:
        """
        Get a prompt template by type.
        
        Args:
            prompt_type: Type of prompt (e.g., 'anatomical', 'diagnostic')
            context: Optional context to append to prompt
            
        Returns:
            Formatted prompt string
        """
        prompt = self.config['prompts'].get(prompt_type, self.config['prompts'].get('default', ''))
        
        if context:
            prompt = f"{prompt}\n\nContext: {context}"
        
        return prompt
    
    def should_force_decorative(self, image_name: str) -> bool:
        """Check if image should be forced as decorative based on name."""
        image_name_lower = image_name.lower()
        
        # Check new decorative_rules structure
        rules = self.config['decorative_overrides'].get('decorative_rules', {})
        
        # Check exact matches
        for exact in rules.get('exact', []):
            if image_name_lower == exact.lower():
                return True
        
        # Check contains matches
        for pattern in rules.get('contains', []):
            if pattern.lower() in image_name_lower:
                return True
        
        # Also check legacy force_decorative list for backwards compatibility
        for pattern in self.config['decorative_overrides'].get('force_decorative', []):
            if pattern.lower() in image_name_lower:
                return True
        
        return False
    
    def should_never_decorative(self, image_name: str) -> bool:
        """Check if image should never be marked as decorative."""
        image_name_lower = image_name.lower()
        for pattern in self.config['decorative_overrides']['never_decorative']:
            if pattern.lower() in image_name_lower:
                return True
        return False
    
    def get_output_config(self) -> Dict[str, Any]:
        """Get output configuration."""
        return self.config['output'].copy()

    def get_smart_truncate_prompt(self) -> str:
        """Get the prompt used for smart truncation summarization."""
        output_cfg = self.get_output_config()
        return output_cfg.get(
            'smart_truncate_prompt',
            'Summarize the following text in one complete sentence of no more than 30 words:'
        )

    def get_logging_config(self) -> Dict[str, Any]:
        """Get logging configuration."""
        return self.config['logging'].copy()
    
    def update_from_cli(self, args: Dict[str, Any]):
        """
        Update configuration from CLI arguments.
        
        Args:
            args: Dictionary of CLI arguments
        """
        # Update prompt type if specified
        if 'prompt' in args and args['prompt']:
            if args['prompt'] not in self.config['prompts']:
                logger.warning(f"Unknown prompt type: {args['prompt']}, using default")
            else:
                self.config['_active_prompt'] = args['prompt']
        
        # Update max tokens if specified
        if 'max_tokens' in args and args['max_tokens']:
            llava_cfg = self.config.setdefault('ai_providers', {}).setdefault('providers', {}).setdefault('llava', {})
            llava_cfg['max_tokens'] = args['max_tokens']

        # Update logging verbosity
        if 'verbose' in args and args['verbose']:
            self.config['logging']['show_prompts'] = True
            self.config['logging']['show_responses'] = True
            self.config['logging']['level'] = 'DEBUG'

        # Update model if specified
        if 'model' in args and args['model']:
            llava_cfg = self.config.setdefault('ai_providers', {}).setdefault('providers', {}).setdefault('llava', {})
            llava_cfg['model'] = args['model']
    
    def save_config(self, path: Optional[str] = None):
        """
        Save current configuration to file.
        
        Args:
            path: Path to save configuration (uses original path if not specified)
        """
        save_path = Path(path) if path else self.config_path
        if not save_path:
            save_path = Path("config.yaml")
        
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                if save_path.suffix in ['.yaml', '.yml']:
                    yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
                else:
                    json.dump(self.config, f, indent=2)
            logger.info(f"Configuration saved to {save_path}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
    
    def create_sample_config(self, path: str = "config_sample.yaml"):
        """Create a sample configuration file with all options."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(self.DEFAULT_CONFIG, f, sort_keys=False)
            logger.info(f"Sample configuration created at {path}")
            print(f"\n✅ Sample configuration file created: {path}")
            print("Edit this file and rename to config.yaml to use it.")
        except Exception as e:
            logger.error(f"Error creating sample configuration: {e}")


# Example usage and testing
if __name__ == "__main__":
    # Test configuration manager
    print("PowerPoint Accessibility Auditor - Configuration Manager")
    print("=" * 60)
    
    try:
        # Try to load existing config
        config = ConfigManager()
        print("\n✅ Configuration loaded successfully!")
        
        # Show current paths
        print("\nCurrent folder configuration:")
        paths = config.get_paths()
        for key, value in paths.items():
            print(f"  {key}: {value}")
        
    except ValueError as e:
        print("\n❌ No valid configuration found.")
        print("Creating a sample configuration file...")
        
        # Create sample config
        temp_config = ConfigManager.__new__(ConfigManager)
        temp_config.config = ConfigManager.DEFAULT_CONFIG
        temp_config.create_sample_config()
        
        print("\nNext steps:")
        print("1. Edit config_sample.yaml with your preferred settings")
        print("2. Rename it to config.yaml")
        print("3. Run this script again to validate your configuration")