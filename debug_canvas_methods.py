#!/usr/bin/env python3
"""
Debug Canvas methods to find the correct way to add BDC/EMC operators
"""

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter

# Create a canvas and inspect its methods
canvas = Canvas("debug.pdf", pagesize=letter)

print("Canvas methods that might be useful for adding raw PDF operators:")
print("=" * 60)

methods = [method for method in dir(canvas) if not method.startswith('_')]
literal_methods = [method for method in methods if 'literal' in method.lower()]
add_methods = [method for method in methods if 'add' in method.lower()]
write_methods = [method for method in methods if 'write' in method.lower()]

print("Methods containing 'literal':")
for method in literal_methods:
    print(f"  {method}")

print("\nMethods containing 'add':")
for method in add_methods:
    print(f"  {method}")

print("\nMethods containing 'write':")
for method in write_methods:
    print(f"  {method}")

print("\nTesting addLiteral method:")
try:
    # Test if addLiteral exists and how it works
    canvas.addLiteral("% This is a test comment")
    print("✅ addLiteral method exists and accepts string")
except Exception as e:
    print(f"❌ addLiteral error: {e}")

# Check the canvas._doc object for low-level access
print("\nCanvas._doc attributes:")
doc_attrs = [attr for attr in dir(canvas._doc) if not attr.startswith('_')]
for attr in doc_attrs[:10]:  # Show first 10
    print(f"  {attr}")

canvas.save()