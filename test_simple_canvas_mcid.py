#!/usr/bin/env python3
"""
Simplified test for Canvas+MCID - focus on BDC/EMC operators first
"""

import logging
import sys
import tempfile
from pathlib import Path

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter
from PIL import Image
import numpy as np

def create_simple_test_image():
    """Create a simple test image."""
    img_array = np.zeros((100, 200, 3), dtype=np.uint8)
    img_array[:, :, 2] = 255  # Blue
    img_array[20:80, 20:180, :] = 255  # White center
    
    img = Image.fromarray(img_array)
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    img.save(temp_file.name)
    temp_file.close()
    return temp_file.name

def test_simple_canvas_mcid():
    """Test simple Canvas with BDC/EMC operators."""
    
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    print("Simple Canvas+MCID BDC/EMC Test")
    print("=" * 40)
    
    try:
        # Create test image
        test_image = create_simple_test_image()
        output_path = project_root / "test_simple_canvas_mcid.pdf"
        
        # Create canvas
        canvas = Canvas(str(output_path), pagesize=letter)
        
        # Test addLiteral method for BDC/EMC
        print("Testing Canvas.addLiteral method...")
        
        # Add text with MCID 0
        canvas.addLiteral("/P <</MCID 0>> BDC")
        canvas.drawString(72, 750, "This text should be wrapped in BDC/EMC with MCID 0")
        canvas.addLiteral("EMC")
        
        # Add image with MCID 1
        canvas.addLiteral("/Figure <</MCID 1>> BDC")
        canvas.drawImage(test_image, 72, 600, width=200, height=100)
        canvas.addLiteral("EMC")
        
        # Add another text with MCID 2
        canvas.addLiteral("/P <</MCID 2>> BDC")
        canvas.drawString(72, 550, "Second text element with MCID 2")
        canvas.addLiteral("EMC")
        
        # Save the PDF
        canvas.save()
        
        print(f"✅ Simple Canvas+MCID PDF created: {output_path}")
        print()
        print("To verify BDC/EMC operators:")
        print("  1. Open PDF in text editor")
        print("  2. Search for 'BDC' - should find '/P <</MCID 0>> BDC'")
        print("  3. Search for 'EMC' - should find multiple EMC operators")
        print("  4. Check that image is wrapped with '/Figure <</MCID 1>> BDC'")
        
        # Clean up
        Path(test_image).unlink(missing_ok=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_simple_canvas_mcid()
    exit(0 if success else 1)