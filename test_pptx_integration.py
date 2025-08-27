#!/usr/bin/env python3
"""
Test script for PPTX ALT text integration.
Validates that the PPTX processor integrates correctly with existing components.
"""

import logging
import sys
import tempfile
from pathlib import Path
from io import BytesIO

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import modules to test
from config_manager import ConfigManager
from unified_alt_generator import FlexibleAltGenerator
from decorative_filter import is_force_decorative_by_filename, validate_decorative_config

# Test imports for PPTX processing
try:
    from pptx_processor import PPTXAccessibilityProcessor, PPTXImageInfo
    from pptx_batch_processor import PPTXBatchProcessor
    PPTX_AVAILABLE = True
except ImportError as e:
    PPTX_AVAILABLE = False
    PPTX_ERROR = str(e)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PPTXIntegrationTester:
    """Test suite for PPTX integration with existing components."""
    
    def __init__(self):
        """Initialize the test suite."""
        self.config_manager = None
        self.alt_generator = None
        self.pptx_processor = None
        self.batch_processor = None
        self.test_results = []
    
    def run_all_tests(self) -> bool:
        """Run all integration tests."""
        logger.info("Starting PPTX integration tests...")
        
        all_passed = True
        tests = [
            ("PPTX Module Availability", self.test_pptx_availability),
            ("ConfigManager Integration", self.test_config_manager_integration),
            ("ALT Generator Integration", self.test_alt_generator_integration),
            ("Decorative Filter Integration", self.test_decorative_filter_integration),
            ("Medical Prompt Integration", self.test_medical_prompt_integration),
            ("PPTX Processor Initialization", self.test_pptx_processor_init),
            ("Batch Processor Initialization", self.test_batch_processor_init),
            ("Configuration Validation", self.test_configuration_validation)
        ]
        
        for test_name, test_func in tests:
            logger.info(f"\n{'='*20} {test_name} {'='*20}")
            
            try:
                result = test_func()
                status = "PASS" if result else "FAIL"
                logger.info(f"{test_name}: {status}")
                
                self.test_results.append({
                    'name': test_name,
                    'passed': result,
                    'error': None
                })
                
                if not result:
                    all_passed = False
                    
            except Exception as e:
                logger.error(f"{test_name}: ERROR - {e}")
                self.test_results.append({
                    'name': test_name,
                    'passed': False,
                    'error': str(e)
                })
                all_passed = False
        
        self.print_summary()
        return all_passed
    
    def test_pptx_availability(self) -> bool:
        """Test if PPTX modules are available."""
        if not PPTX_AVAILABLE:
            logger.error(f"PPTX modules not available: {PPTX_ERROR}")
            logger.info("Install python-pptx with: pip install python-pptx")
            return False
        
        logger.info("✅ PPTX modules imported successfully")
        return True
    
    def test_config_manager_integration(self) -> bool:
        """Test ConfigManager integration."""
        try:
            self.config_manager = ConfigManager()
            
            # Check if PPTX configuration is present
            pptx_config = self.config_manager.config.get('pptx_processing', {})
            if not pptx_config:
                logger.warning("No PPTX configuration found in config.yaml")
                return False
            
            # Validate key PPTX settings
            required_settings = [
                'skip_decorative_images',
                'decorative_size_threshold',
                'include_slide_notes',
                'include_slide_text'
            ]
            
            for setting in required_settings:
                if setting not in pptx_config:
                    logger.error(f"Missing PPTX config setting: {setting}")
                    return False
            
            logger.info("✅ ConfigManager integration successful")
            logger.info(f"  PPTX decorative threshold: {pptx_config['decorative_size_threshold']}px")
            logger.info(f"  Include slide notes: {pptx_config['include_slide_notes']}")
            logger.info(f"  Include slide text: {pptx_config['include_slide_text']}")
            
            return True
            
        except Exception as e:
            logger.error(f"ConfigManager integration failed: {e}")
            return False
    
    def test_alt_generator_integration(self) -> bool:
        """Test FlexibleAltGenerator integration."""
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            self.alt_generator = FlexibleAltGenerator(self.config_manager)
            
            # Test prompt type support
            prompt_types = ['default', 'anatomical', 'diagnostic', 'unified_medical']
            
            for prompt_type in prompt_types:
                prompt = self.config_manager.get_prompt(prompt_type)
                if not prompt:
                    logger.error(f"No prompt found for type: {prompt_type}")
                    return False
                logger.debug(f"  {prompt_type}: {prompt[:50]}...")
            
            # Test generator status
            stats = self.alt_generator.get_usage_stats()
            logger.info("✅ ALT generator integration successful")
            logger.info(f"  Available providers: {stats['providers_available']}")
            logger.info(f"  Fallback chain: {stats['fallback_chain']}")
            
            return True
            
        except Exception as e:
            logger.error(f"ALT generator integration failed: {e}")
            return False
    
    def test_decorative_filter_integration(self) -> bool:
        """Test decorative filter integration."""
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            # Validate decorative configuration
            is_valid = validate_decorative_config(self.config_manager.config)
            if not is_valid:
                logger.error("Decorative configuration validation failed")
                return False
            
            # Test decorative detection rules
            test_files = [
                ("logo.png", True),           # Should be decorative
                ("watermark.jpg", True),      # Should be decorative
                ("anatomy_chart.png", False), # Should NOT be decorative (never list)
                ("xray_image.jpg", False),    # Should NOT be decorative (never list)
                ("random_image.png", False)   # Should NOT be decorative
            ]
            
            for filename, expected_decorative in test_files:
                result = is_force_decorative_by_filename(filename, self.config_manager.config)
                if result != expected_decorative:
                    logger.error(f"Decorative detection failed for {filename}: expected {expected_decorative}, got {result}")
                    return False
                logger.debug(f"  {filename}: {'decorative' if result else 'not decorative'} ✓")
            
            logger.info("✅ Decorative filter integration successful")
            return True
            
        except Exception as e:
            logger.error(f"Decorative filter integration failed: {e}")
            return False
    
    def test_medical_prompt_integration(self) -> bool:
        """Test medical-specific prompt system."""
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            # Test medical prompt types
            medical_prompts = [
                'anatomical',
                'diagnostic', 
                'clinical_photo',
                'unified_medical'
            ]
            
            for prompt_type in medical_prompts:
                prompt = self.config_manager.get_prompt(prompt_type)
                if not prompt:
                    logger.error(f"Medical prompt not found: {prompt_type}")
                    return False
                
                # Check that prompt contains medical-specific language
                medical_keywords = ['anatomical', 'diagnostic', 'clinical', 'medical', 'image']
                if not any(keyword in prompt.lower() for keyword in medical_keywords):
                    logger.warning(f"Prompt for {prompt_type} may not be medical-specific")
                
                logger.debug(f"  {prompt_type}: {prompt}")
            
            logger.info("✅ Medical prompt integration successful")
            return True
            
        except Exception as e:
            logger.error(f"Medical prompt integration failed: {e}")
            return False
    
    def test_pptx_processor_init(self) -> bool:
        """Test PPTX processor initialization."""
        if not PPTX_AVAILABLE:
            logger.info("Skipping PPTX processor test - modules not available")
            return True
        
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            self.pptx_processor = PPTXAccessibilityProcessor(self.config_manager)
            
            # Test processor configuration
            pptx_config = self.config_manager.config.get('pptx_processing', {})
            expected_threshold = pptx_config.get('decorative_size_threshold', 50)
            
            if self.pptx_processor.decorative_size_threshold != expected_threshold:
                logger.error(f"Threshold mismatch: expected {expected_threshold}, got {self.pptx_processor.decorative_size_threshold}")
                return False
            
            logger.info("✅ PPTX processor initialization successful")
            logger.info(f"  Decorative threshold: {self.pptx_processor.decorative_size_threshold}px")
            logger.info(f"  Skip decorative: {self.pptx_processor.skip_decorative}")
            logger.info(f"  Include notes: {self.pptx_processor.include_slide_notes}")
            logger.info(f"  Include text: {self.pptx_processor.include_slide_text}")
            
            return True
            
        except Exception as e:
            logger.error(f"PPTX processor initialization failed: {e}")
            return False
    
    def test_batch_processor_init(self) -> bool:
        """Test batch processor initialization."""
        if not PPTX_AVAILABLE:
            logger.info("Skipping batch processor test - modules not available")
            return True
        
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            self.batch_processor = PPTXBatchProcessor(self.config_manager)
            
            # Test batch processor configuration
            logger.info("✅ Batch processor initialization successful")
            logger.info(f"  Input folder: {self.batch_processor.input_folder}")
            logger.info(f"  Output folder: {self.batch_processor.output_folder}")
            logger.info(f"  Max workers: {self.batch_processor.max_workers}")
            logger.info(f"  Preserve original: {self.batch_processor.preserve_original}")
            
            return True
            
        except Exception as e:
            logger.error(f"Batch processor initialization failed: {e}")
            return False
    
    def test_configuration_validation(self) -> bool:
        """Test that all configuration is valid for PPTX processing."""
        try:
            if not self.config_manager:
                self.config_manager = ConfigManager()
            
            config = self.config_manager.config
            
            # Check required sections
            required_sections = [
                'ai_providers',
                'prompts', 
                'decorative_overrides',
                'pptx_processing'
            ]
            
            for section in required_sections:
                if section not in config:
                    logger.error(f"Missing required config section: {section}")
                    return False
            
            # Validate AI providers
            providers = config['ai_providers'].get('providers', {})
            if not providers:
                logger.error("No AI providers configured")
                return False
            
            # Validate fallback chain
            fallback_chain = config['ai_providers'].get('fallback_chain', [])
            if not fallback_chain:
                logger.error("No fallback chain configured")
                return False
            
            for provider_name in fallback_chain:
                if provider_name not in providers:
                    logger.error(f"Fallback provider '{provider_name}' not configured")
                    return False
            
            # Validate prompt completeness
            required_prompts = ['default', 'anatomical', 'diagnostic', 'unified_medical']
            prompts = config.get('prompts', {})
            
            for prompt_type in required_prompts:
                if prompt_type not in prompts or not prompts[prompt_type]:
                    logger.error(f"Missing or empty prompt: {prompt_type}")
                    return False
            
            logger.info("✅ Configuration validation successful")
            logger.info(f"  Providers: {list(providers.keys())}")
            logger.info(f"  Fallback chain: {fallback_chain}")
            logger.info(f"  Prompt types: {len(prompts)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            return False
    
    def print_summary(self):
        """Print test results summary."""
        logger.info("\n" + "="*60)
        logger.info("TEST RESULTS SUMMARY")
        logger.info("="*60)
        
        passed = sum(1 for result in self.test_results if result['passed'])
        total = len(self.test_results)
        
        logger.info(f"Tests passed: {passed}/{total}")
        
        for result in self.test_results:
            status = "✅ PASS" if result['passed'] else "❌ FAIL"
            logger.info(f"  {status}: {result['name']}")
            
            if result['error']:
                logger.info(f"    Error: {result['error']}")
        
        overall_status = "✅ ALL TESTS PASSED" if passed == total else f"❌ {total - passed} TESTS FAILED"
        logger.info(f"\nOverall: {overall_status}")
        
        if passed != total:
            logger.info("\nRecommendations:")
            if not PPTX_AVAILABLE:
                logger.info("  - Install python-pptx: pip install python-pptx")
            logger.info("  - Check config.yaml for missing PPTX settings")
            logger.info("  - Ensure AI providers are properly configured")


def main():
    """Run the integration tests."""
    print("PPTX Integration Test Suite")
    print("="*50)
    
    tester = PPTXIntegrationTester()
    success = tester.run_all_tests()
    
    if success:
        print("\n🎉 All integration tests passed!")
        print("The PPTX processor is ready to use with your existing workflow.")
        return 0
    else:
        print("\n💥 Some integration tests failed!")
        print("Please review the errors above and fix configuration issues.")
        return 1


if __name__ == "__main__":
    exit(main())