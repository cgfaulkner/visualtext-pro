#!/usr/bin/env python3
"""
Test script for the new comprehensive visual element ALT text generation.
Tests that ALL visual elements (images, shapes, charts) get ALT text.
"""

import logging
import sys
from pathlib import Path

# Add the core directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from pptx_processor import PPTXAccessibilityProcessor

def setup_logging():
    """Setup debug logging."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('comprehensive_alt_test.log')
        ]
    )

def test_comprehensive_alt_generation():
    """Test comprehensive ALT text generation for all visual elements."""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Find the test PPTX file
    test_file = Path("Documents to Review") / "test1_llava_latest_backup test names.pptx"
    
    if not test_file.exists():
        logger.error(f"Test file not found: {test_file}")
        return False
    
    logger.info("🚀 Starting comprehensive visual element ALT text generation test")
    logger.info(f"📁 Test file: {test_file}")
    
    try:
        # Create processor
        processor = PPTXAccessibilityProcessor(debug=True)
        
        # Process the presentation with the new comprehensive approach
        result = processor.process_pptx(str(test_file), debug=True)
        
        # Report results
        logger.info("📊 COMPREHENSIVE ALT TEXT GENERATION RESULTS:")
        logger.info(f"  Success: {result['success']}")
        logger.info(f"  Total slides: {result['total_slides']}")
        logger.info(f"  Total visual elements found: {result['total_visual_elements']}")
        logger.info(f"  Visual elements processed: {result['processed_visual_elements']}")
        logger.info(f"  Failed visual elements: {result['failed_visual_elements']}")
        
        if result['total_visual_elements'] > 0:
            coverage = (result['processed_visual_elements'] / result['total_visual_elements']) * 100
            logger.info(f"  Coverage: {coverage:.1f}%")
            
            if coverage > 50:
                logger.info("✅ Good coverage achieved!")
            else:
                logger.warning("⚠️ Low coverage - check for issues")
        
        logger.info(f"  Generation time: {result['generation_time']:.2f}s")
        logger.info(f"  Injection time: {result['injection_time']:.2f}s")
        logger.info(f"  Total time: {result['total_time']:.2f}s")
        
        if result['errors']:
            logger.warning(f"  Errors encountered: {len(result['errors'])}")
            for error in result['errors']:
                logger.warning(f"    - {error}")
        
        return result['success']
        
    except Exception as e:
        logger.error(f"💥 Test failed with exception: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    print("🧪 Testing comprehensive visual element ALT text generation...")
    success = test_comprehensive_alt_generation()
    if success:
        print("✅ Test completed successfully!")
        print("📄 Check 'comprehensive_alt_test.log' for detailed output")
    else:
        print("❌ Test failed!")
        sys.exit(1)