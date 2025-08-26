#!/usr/bin/env python3
"""
Test script for Canvas+MCID PDF/UA compliance implementation
Tests the new Canvas-based approach with proper BDC/EMC and MCID linking
"""

import logging
import sys
import tempfile
from pathlib import Path

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

from pdf_accessibility_recreator import PDFAccessibilityRecreator
from PIL import Image
import numpy as np

def create_simple_test_image():
    """Create a simple test image for MCID testing."""
    # Create a simple blue rectangle with white text area
    img_array = np.zeros((100, 200, 3), dtype=np.uint8)
    img_array[:, :, 2] = 255  # Blue channel
    img_array[20:80, 20:180, :] = 255  # White rectangle in middle
    
    img = Image.fromarray(img_array)
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(temp_file.name)
    temp_file.close()
    return temp_file.name

def test_canvas_mcid_implementation():
    """Test the Canvas+MCID implementation with a simple single-page PDF."""
    
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    print("Canvas+MCID PDF/UA Compliance Test")
    print("=" * 50)
    
    try:
        # Create simple test image
        test_image = create_simple_test_image()
        print(f"Created test image: {test_image}")
        
        # Create mock extracted content with single page and single image
        content = {
            'metadata': {
                'title': 'Canvas+MCID Test Document',
                'author': 'PDF ALT Text Generator - Canvas Test',
                'subject': 'Testing Canvas+MCID PDF/UA implementation',
            },
            'pages': [
                {
                    'page_number': 1,
                    'page_size': (612, 792),
                    'text_blocks': [
                        {
                            'text': 'This document tests Canvas+MCID implementation for PDF/UA compliance.',
                            'bbox': (100, 700, 500, 720),
                            'fonts': [{'font': 'Helvetica', 'size': 12, 'flags': 0}]
                        },
                        {
                            'text': 'Each element should have proper BDC/EMC markers with MCID references.',
                            'bbox': (100, 650, 500, 670),
                            'fonts': [{'font': 'Helvetica', 'size': 12, 'flags': 0}]
                        }
                    ],
                    'images': [
                        {
                            'image_index': 0,
                            'temp_path': test_image,
                            'bbox': (100, 400, 200, 100),
                            'format': 'png',
                            'width': 200,
                            'height': 100,
                            'key': 'page_1_image_0'
                        }
                    ]
                }
            ]
        }
        
        # ALT text mapping
        alt_text_mapping = {
            'page_1_image_0': 'Blue rectangle with white center area for Canvas+MCID testing'
        }
        
        # Output path
        output_path = project_root / "test_canvas_mcid.pdf"
        
        print(f"Output PDF: {output_path}")
        print()
        
        # Create accessible PDF using Canvas+MCID approach
        recreator = PDFAccessibilityRecreator()
        result = recreator._create_accessible_pdf(content, alt_text_mapping, str(output_path))
        
        print("Canvas+MCID Test Results:")
        print(f"  Creation successful: {result}")
        
        if result:
            print(f"✅ Canvas+MCID PDF created: {output_path}")
            print()
            print("Expected PDF features:")
            print("  ✅ BDC/EMC marked content sequences in page content streams")
            print("  ✅ MCID numbers linking page content to structure elements")
            print("  ✅ Structure tree with Figure and P elements")
            print("  ✅ ParentTree mapping MCIDs back to structure elements")
            print("  ✅ /MarkInfo << /Marked true >> in document catalog")
            print("  ✅ PDF/UA XMP metadata with pdfuaid:part='1'")
            print()
            print("To verify BDC/EMC operators:")
            print("  1. Open PDF in text editor and search for 'BDC' and 'EMC'")
            print("  2. Look for '/Figure <</MCID n>> BDC' patterns")
            print("  3. Check structure tree has proper K arrays with MCID refs")
            print("  4. Test with screen reader for proper ALT text reading")
        else:
            print("❌ Canvas+MCID PDF creation failed!")
            return 1
        
        # Clean up test image
        Path(test_image).unlink(missing_ok=True)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(test_canvas_mcid_implementation())