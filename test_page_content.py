#!/usr/bin/env python3
"""
Test getCurrentPageContent and see if we can inject BDC/EMC operators
"""

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter

# Create a canvas and test getCurrentPageContent
canvas = Canvas("test_page_content.pdf", pagesize=letter)

print("Testing getCurrentPageContent method:")

# Draw some initial content
canvas.drawString(72, 750, "Before BDC/EMC injection")

# Try to get current page content
try:
    content_before = canvas.getCurrentPageContent()
    print(f"Current page content length: {len(content_before)}")
    print(f"Content preview: {content_before[:200]}...")
    
    # Try to inject BDC/EMC by manipulating the content stream
    # This is a hack but might work
    canvas_doc = canvas._doc
    
    # Check if we can access the current page stream
    if hasattr(canvas_doc, 'streams') and canvas_doc.streams:
        current_stream = canvas_doc.streams[-1]  # Last stream should be current page
        print(f"Found current stream: {type(current_stream)}")
        
        # Try to add BDC/EMC operators to the stream content
        if hasattr(current_stream, 'content'):
            print("Stream has content attribute")
            # Try to inject our BDC/EMC operators
            bdc_content = b"/Figure <</MCID 0>> BDC\n"
            emc_content = b"EMC\n"
            
            # This is very hacky but let's see if it works
            current_stream.content += bdc_content
    
except Exception as e:
    print(f"Error with getCurrentPageContent: {e}")

# Draw some more content after the injection attempt
canvas.drawString(72, 700, "After BDC/EMC injection attempt")

canvas.save()

# Check if BDC/EMC made it into the final PDF
with open('test_page_content.pdf', 'rb') as f:
    content = f.read().decode('latin1', errors='ignore')
    
if 'BDC' in content:
    print("✅ BDC found in final PDF!")
else:
    print("❌ BDC not found in final PDF")

if 'EMC' in content:
    print("✅ EMC found in final PDF!")  
else:
    print("❌ EMC not found in final PDF")