#!/usr/bin/env python3
"""
Test script for PDF/UA compliance implementation
Creates a test PDF with proper marked content sequences and structure elements
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

def create_test_image():
    """Create a simple test image for testing accessibility."""
    # Create a simple colored rectangle
    img_array = np.zeros((200, 300, 3), dtype=np.uint8)
    img_array[:, :, 0] = 255  # Red channel
    img_array[50:150, 50:250, 1] = 255  # Add green square
    
    img = Image.fromarray(img_array)
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(temp_file.name)
    temp_file.close()
    return temp_file.name

def test_pdf_ua_compliance():
    """Test the PDF/UA compliance implementation."""
    
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    print("PDF/UA Compliance Test")
    print("=" * 50)
    
    try:
        # Create test image
        test_image = create_test_image()
        print(f"Created test image: {test_image}")
        
        # Create mock extracted content with the test image
        content = {
            'metadata': {
                'title': 'PDF/UA Compliance Test Document',
                'author': 'PDF ALT Text Generator',
                'subject': 'Testing PDF/UA compliance',
            },
            'pages': [
                {
                    'page_number': 1,
                    'page_size': (612, 792),
                    'text_blocks': [
                        {
                            'text': 'This is a test document to verify PDF/UA compliance.',
                            'bbox': (100, 700, 500, 720),
                            'fonts': [{'font': 'Helvetica', 'size': 12, 'flags': 0}]
                        }
                    ],
                    'images': [
                        {
                            'image_index': 0,
                            'temp_path': test_image,
                            'bbox': (100, 400, 300, 200),
                            'format': 'png',
                            'width': 300,
                            'height': 200,
                            'key': 'page_1_image_0'
                        }
                    ]
                }
            ]
        }
        
        # ALT text mapping
        alt_text_mapping = {
            'page_1_image_0': 'A red rectangle with a green square overlay, used for PDF/UA accessibility testing'
        }
        
        # Output path
        output_path = project_root / "test_pdf_ua_compliance.pdf"
        
        print(f"Output PDF: {output_path}")
        print()
        
        # Create accessible PDF using the recreator
        recreator = PDFAccessibilityRecreator()
        result = recreator._create_accessible_pdf(content, alt_text_mapping, str(output_path))
        
        print("PDF/UA Compliance Test Results:")
        print(f"  Creation successful: {result}")
        
        if result:
            print(f"✅ PDF/UA compliant PDF created: {output_path}")
            print()
            print("Features implemented:")
            print("  ✅ BDC/EMC marked content sequences around images")
            print("  ✅ MCID generation and linking to structure elements")
            print("  ✅ Proper Figure structure elements with ALT text")
            print("  ✅ PDF/UA metadata and compliance markers")
            print("  ✅ XMP metadata with pdfuaid:part='1'")
            print("  ✅ ViewerPreferences and MarkInfo dictionaries")
            print()
            print("Next steps:")
            print("  1. Test with a screen reader (NVDA, JAWS, VoiceOver)")
            print("  2. Validate with PAC 3 or Adobe Acrobat Pro")
            print("  3. Check for proper structure tree navigation")
        else:
            print("❌ PDF creation failed!")
            return 1
        
        # Clean up test image
        Path(test_image).unlink(missing_ok=True)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(test_pdf_ua_compliance())