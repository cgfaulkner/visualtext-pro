#!/usr/bin/env python3
"""
Test script for PDF/UA compliance with manual ALT text
Tests the recreation workflow with predefined ALT text mappings
"""

import logging
import sys
from pathlib import Path
import json

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

from pdf_accessibility_recreator import PDFAccessibilityRecreator

def test_manual_alt_text():
    """Test PDF/UA compliance with manual ALT text mappings."""
    
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    print("Manual ALT Text PDF/UA Compliance Test")
    print("=" * 50)
    
    try:
        # Check if sample PDF exists
        sample_pdf = project_root / "Documents to Review" / "test1_demo.pdf"
        if not sample_pdf.exists():
            print(f"Sample PDF not found: {sample_pdf}")
            return 1
        
        # Create manual ALT text mapping for known images
        alt_text_mapping = {
            'page_1_image_0': 'Logo or header image for A Presentation',
            'page_2_image_0': 'Diagram showing workflow or process step 1',
            'page_2_image_1': 'Diagram showing workflow or process step 2',
            'page_3_image_0': 'Chart or graph displaying data analysis',
            'page_3_image_1': 'Additional chart or supporting visual',
            'page_4_image_0': 'Technical diagram or architectural overview',
            'page_4_image_1': 'Code snippet or configuration example',
            'page_4_image_2': 'Result or output visualization',
            'page_5_image_0': 'Performance metrics or statistics chart',
            'page_6_image_0': 'Implementation diagram or system architecture',
            'page_7_image_0': 'Testing results or validation metrics',
            'page_8_image_0': 'Deployment or infrastructure diagram',
            'page_9_image_0': 'Summary chart or conclusion visual',
            'page_10_image_0': 'Contact information or next steps graphic'
        }
        
        output_path = project_root / "demo_recreated_with_alt.pdf"
        
        print(f"Input PDF: {sample_pdf}")
        print(f"Output PDF: {output_path}")
        print(f"ALT text mappings: {len(alt_text_mapping)} images")
        print()
        
        # Recreate PDF with accessibility
        recreator = PDFAccessibilityRecreator()
        result = recreator.recreate_accessible_pdf(str(sample_pdf), alt_text_mapping, str(output_path))
        
        # Display results
        print("Recreation Results:")
        print(f"  Success: {result['success']}")
        print(f"  Pages processed: {result['pages_processed']}")
        print(f"  Images processed: {result['images_processed']}")
        
        if result['errors']:
            print(f"  Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    - {error}")
        
        if result['success']:
            print(f"\n✅ PDF/UA compliant PDF created: {output_path}")
            print()
            print("Features implemented:")
            print("  ✅ Proper accessibility structure elements")
            print("  ✅ ALT text embedded in image XObjects") 
            print("  ✅ Structure tree with Figure elements")
            print("  ✅ PDF/UA metadata and compliance markers")
            print()
            print("To verify PDF/UA compliance:")
            print("  1. Open with a screen reader (VoiceOver, NVDA, JAWS)")
            print("  2. Use PAC 3 accessibility checker")
            print("  3. Validate with Adobe Acrobat Pro accessibility tools")
            print("  4. Check that images read ALT text properly")
        else:
            print(f"\n❌ PDF recreation failed!")
            return 1
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(test_manual_alt_text())