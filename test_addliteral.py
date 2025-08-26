#!/usr/bin/env python3
"""
Test addLiteral to see if it actually writes to the PDF stream
"""

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter

# Create a canvas and test addLiteral
canvas = Canvas("test_addliteral.pdf", pagesize=letter)

# Add a comment that should be easy to find
canvas.addLiteral("% TEST COMMENT FOR BDC/EMC")

# Add some actual BDC/EMC operators
canvas.addLiteral("/P <</MCID 0>> BDC")
canvas.drawString(72, 750, "Test text with MCID")
canvas.addLiteral("EMC")

canvas.save()

# Check if the content is in the PDF
with open('test_addliteral.pdf', 'rb') as f:
    content = f.read().decode('latin1', errors='ignore')
    
print("Checking PDF content:")
if 'TEST COMMENT' in content:
    print("✅ addLiteral comment found in PDF")
else:
    print("❌ addLiteral comment NOT found in PDF")

if 'BDC' in content:
    print("✅ BDC operator found in PDF") 
    # Find and show BDC lines
    for line in content.split('\n'):
        if 'BDC' in line:
            print(f"  Found: {line.strip()}")
else:
    print("❌ BDC operator NOT found in PDF")

if 'EMC' in content:
    print("✅ EMC operator found in PDF")
else:
    print("❌ EMC operator NOT found in PDF")