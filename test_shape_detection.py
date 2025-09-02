#!/usr/bin/env python3
"""
Test script for enhanced decorative shape detection in PPTX files.
Tests the new detection methods on slides 4, 5, and 6 with debug logging.
"""

import logging
import sys
from pathlib import Path

# Add the core directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "core"))

from pptx_processor import PPTXAccessibilityProcessor

def setup_logging():
    """Setup detailed debug logging."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('shape_detection_test.log')
        ]
    )

def test_shape_detection():
    """Test shape detection with enhanced logging."""
    # Set up logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Find the test PPTX file
    test_file = Path("Documents to Review") / "test1_llava_latest_backup test names.pptx"
    
    if not test_file.exists():
        logger.error(f"Test file not found: {test_file}")
        return False
    
    logger.info("🚀 Starting enhanced shape detection test")
    logger.info(f"📁 Test file: {test_file}")
    
    try:
        # Create processor with debug enabled
        processor = PPTXAccessibilityProcessor(debug=True)
        
        # Load the presentation to test shape detection
        from pptx import Presentation
        presentation = Presentation(str(test_file))
        
        logger.info(f"📊 Loaded presentation with {len(presentation.slides)} slides")
        
        # Test decorative shape detection with debug logging
        logger.info("🎨 Testing decorative shape detection with enhanced logging...")
        decorative_shapes = processor.detect_decorative_shapes(presentation, debug=True)
        
        logger.info(f"✅ Detection completed. Found {len(decorative_shapes)} potentially decorative shapes")
        
        # Analyze results by slide
        slide_results = {}
        for shape_info in decorative_shapes:
            slide_num = shape_info.slide_idx + 1
            if slide_num not in slide_results:
                slide_results[slide_num] = []
            slide_results[slide_num].append(shape_info)
        
        # Report detailed results
        logger.info("📋 DETECTION SUMMARY BY SLIDE:")
        for slide_num in sorted(slide_results.keys()):
            shapes = slide_results[slide_num]
            logger.info(f"  Slide {slide_num}: {len(shapes)} decorative shapes detected")
            for i, shape_info in enumerate(shapes, 1):
                logger.info(f"    {i}. {shape_info.shape_type_name} ({shape_info.width_px}x{shape_info.height_px}px)")
        
        # Focus on target slides (3, 4, 5, 6)
        target_slides = [3, 4, 5, 6]
        logger.info("🎯 FOCUSING ON TARGET SLIDES:")
        
        for slide_num in target_slides:
            if slide_num in slide_results:
                shapes = slide_results[slide_num]
                logger.info(f"  Slide {slide_num}: {len(shapes)} shapes found")
            else:
                logger.warning(f"  Slide {slide_num}: No decorative shapes detected")
        
        # Specific targets to verify:
        # - Right graph on slide 3
        # - Blue circle on slide 4  
        # - Line on slide 5
        # - Purple hexagon on slide 6
        
        target_shapes = {
            3: "right graph",
            4: "blue circle", 
            5: "line",
            6: "purple hexagon"
        }
        
        logger.info("🔍 VERIFYING SPECIFIC TARGET SHAPES:")
        for slide_num, target_desc in target_shapes.items():
            if slide_num in slide_results:
                shapes = slide_results[slide_num]
                logger.info(f"  Slide {slide_num} ({target_desc}): {len(shapes)} shapes detected")
                for shape_info in shapes:
                    logger.info(f"    - {shape_info.shape_type_name} at ({shape_info.left_px}, {shape_info.top_px})")
            else:
                logger.warning(f"  Slide {slide_num} ({target_desc}): ❌ NO SHAPES DETECTED")
        
        return True
        
    except Exception as e:
        logger.error(f"💥 Test failed with exception: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    print("🧪 Testing enhanced decorative shape detection...")
    success = test_shape_detection()
    if success:
        print("✅ Test completed successfully!")
        print("📄 Check 'shape_detection_test.log' for detailed debug output")
    else:
        print("❌ Test failed!")
        sys.exit(1)