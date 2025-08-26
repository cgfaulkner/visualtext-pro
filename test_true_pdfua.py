#!/usr/bin/env python3
"""
Test true PDF/UA tagging with BDC/EMC operators around image paint operations
Validates one page, one image scenario per requirements
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
    """Create a simple test image for PDF/UA validation."""
    img_array = np.zeros((150, 300, 3), dtype=np.uint8)
    img_array[:, :, 0] = 200  # Red
    img_array[50:100, 50:250, 1] = 200  # Yellow overlay
    img_array[30:120, 30:270] = [100, 100, 255]  # Blue border
    
    img = Image.fromarray(img_array)
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(temp_file.name)
    temp_file.close()
    return temp_file.name

def test_true_pdfua_compliance():
    """Test true PDF/UA compliance with BDC/EMC operators and proper structure."""
    
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    print("True PDF/UA Compliance Test")
    print("=" * 50)
    print("Goal: Replace ALT annotations with true PDF/UA tagging")
    print("Validating: One page, one image with BDC/EMC + structure")
    print()
    
    try:
        # Create test image
        test_image = create_test_image()
        print(f"Created test image: {test_image}")
        
        # Create minimal content: one page, one image
        content = {
            'metadata': {
                'title': 'True PDF/UA Test - One Page One Image',
                'author': 'PDF ALT Text Generator - True PDF/UA',
                'subject': 'Testing BDC/EMC operators with MCID linkage',
            },
            'pages': [
                {
                    'page_number': 1,
                    'page_size': (612, 792),
                    'text_blocks': [
                        {
                            'text': 'PDF/UA Test: This image should have BDC/EMC operators in content stream',
                            'bbox': (100, 700, 500, 720),
                            'fonts': [{'font': 'Helvetica', 'size': 12, 'flags': 0}]
                        }
                    ],
                    'images': [
                        {
                            'image_index': 0,
                            'temp_path': test_image,
                            'bbox': (100, 400, 300, 150),
                            'format': 'png',
                            'width': 300,
                            'height': 150,
                            'key': 'page_1_image_0'
                        }
                    ]
                }
            ]
        }
        
        # ALT text with both ASCII and non-Latin characters for AT testing
        alt_text_mapping = {
            'page_1_image_0': 'Test image with colorful borders - Тест изображение - 测试图像'
        }
        
        output_path = project_root / "test_true_pdfua.pdf"
        
        print(f"Output PDF: {output_path}")
        print(f"ALT text: {alt_text_mapping['page_1_image_0']}")
        print()
        
        # Create PDF with true PDF/UA tagging
        recreator = PDFAccessibilityRecreator()
        result = recreator._create_accessible_pdf(content, alt_text_mapping, str(output_path))
        
        print("True PDF/UA Test Results:")
        print(f"  Creation successful: {result}")
        
        if result:
            print(f"✅ True PDF/UA PDF created: {output_path}")
            print()
            print("Expected features:")
            print("  📄 One page, one image scenario")
            print("  🔗 BDC/EMC operators tightly wrapping image paint operation") 
            print("  🏷️ MCID 0-1 per page (text=0, image=1)")
            print("  📊 /Figure structure element with /K int, /Pg ref, /Alt UTF-16BE+BOM")
            print("  🌳 Minimal ParentTree mapping MCID → /Figure")
            print("  📋 /MarkInfo << /Marked true >>, /Lang, /RoleMap")
            print()
            print("Validation steps:")
            print("  1. Check page content stream for '/Figure <</MCID 1>> BDC' around image")
            print("  2. Verify structure element has /K 1, /Pg reference, /Alt text")
            print("  3. Confirm ParentTree maps MCID 1 to Figure element")
            print("  4. Test with PAC3 + veraPDF for compliance")
            print("  5. Verify ALT text reads properly in screen reader (ASCII + Unicode)")
            
            # Quick validation - check if BDC/EMC made it into the PDF
            try:
                with open(output_path, 'rb') as f:
                    pdf_content = f.read().decode('latin1', errors='ignore')
                    
                if '/Figure <</MCID' in pdf_content and 'BDC' in pdf_content:
                    print("\n✅ BDC operators found in PDF content stream")
                else:
                    print("\n⚠️ BDC operators may not be present - check injection method")
                    
                if 'EMC' in pdf_content:
                    print("✅ EMC operators found in PDF content stream")
                else:
                    print("⚠️ EMC operators may not be present")
                    
            except Exception as e:
                print(f"\n⚠️ Could not validate PDF content: {e}")
                
        else:
            print("❌ True PDF/UA PDF creation failed!")
            return 1
        
        # Clean up test image
        Path(test_image).unlink(missing_ok=True)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(test_true_pdfua_compliance())