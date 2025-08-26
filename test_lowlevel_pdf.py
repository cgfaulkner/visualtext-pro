#!/usr/bin/env python3
"""
Test low-level PDF writing to add BDC/EMC operators
"""

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter

# Create a canvas and test low-level access
canvas = Canvas("test_lowlevel.pdf", pagesize=letter)

print("Exploring canvas._doc structure:")
print(f"canvas._doc type: {type(canvas._doc)}")

# Check if there's a way to access the current page's content stream
if hasattr(canvas._doc, 'currentContents'):
    print("Has currentContents")
elif hasattr(canvas._doc, 'contents'):
    print("Has contents")

# Check for content-related attributes
doc_attrs = [attr for attr in dir(canvas._doc) if 'content' in attr.lower() or 'stream' in attr.lower()]
print(f"Content/stream related attributes: {doc_attrs}")

# Try to understand the Canvas internal structure better
print(f"\nCanvas attributes that might help:")
canvas_attrs = [attr for attr in dir(canvas) if 'content' in attr.lower() or 'stream' in attr.lower() or 'page' in attr.lower()]
for attr in canvas_attrs:
    print(f"  canvas.{attr}")

# Let's try to access the content buffer or stream during drawing
print(f"\nTrying to access canvas content stream...")

# Draw something and see if we can intercept or modify the content
canvas.drawString(72, 750, "Test text")

# Check if there's a way to get the raw content being written
if hasattr(canvas, '_content') or hasattr(canvas, 'content'):
    print("Canvas has content attribute")
    
# Check the doc's page content
if hasattr(canvas._doc, 'getContents'):
    print("Doc has getContents method")

canvas.save()

print("Test completed. Need to find the correct way to inject BDC/EMC operators.")