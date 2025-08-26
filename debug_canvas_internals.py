#!/usr/bin/env python3
"""
Debug ReportLab Canvas internals to find the best way to inject BDC/EMC operators
"""

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import letter
import tempfile

def debug_canvas_internals():
    """Debug Canvas internals to find content stream access."""
    
    temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    canvas = Canvas(temp_file.name, pagesize=letter)
    
    print("Canvas Internal Structure Analysis")
    print("=" * 50)
    
    # Analyze canvas object attributes
    print("Canvas attributes containing 'content', 'stream', 'code', 'page':")
    canvas_attrs = dir(canvas)
    relevant_attrs = [attr for attr in canvas_attrs 
                     if any(keyword in attr.lower() 
                           for keyword in ['content', 'stream', 'code', 'page', 'doc'])]
    
    for attr in sorted(relevant_attrs):
        if not attr.startswith('_') or attr in ['_code', '_doc', '_pageContents']:
            try:
                value = getattr(canvas, attr)
                print(f"  canvas.{attr}: {type(value)} - {str(value)[:100]}...")
            except:
                print(f"  canvas.{attr}: <error accessing>")
    
    print()
    
    # Analyze _doc object
    print("Canvas._doc attributes:")
    if hasattr(canvas, '_doc'):
        doc_attrs = [attr for attr in dir(canvas._doc) 
                    if any(keyword in attr.lower() 
                          for keyword in ['content', 'stream', 'page', 'current'])]
        for attr in sorted(doc_attrs):
            try:
                value = getattr(canvas._doc, attr)
                print(f"  canvas._doc.{attr}: {type(value)}")
            except:
                print(f"  canvas._doc.{attr}: <error accessing>")
    
    print()
    
    # Try to draw something and see what gets created
    print("Drawing test content to see what attributes get populated...")
    canvas.drawString(100, 700, "Test text")
    
    # Check if _code exists and what it contains
    if hasattr(canvas, '_code'):
        print(f"canvas._code after drawing: {type(canvas._code)}")
        if hasattr(canvas._code, '__len__'):
            print(f"  Length: {len(canvas._code)}")
            if len(canvas._code) > 0:
                print(f"  Content sample: {canvas._code[-3:]}")
    
    # Check other potential content containers
    for attr in ['_pageContents', '_currentPageContents', '_pageStream']:
        if hasattr(canvas, attr):
            value = getattr(canvas, attr)
            print(f"canvas.{attr}: {type(value)} - {value}")
    
    # Try the getCurrentPageContent method
    try:
        current_content = canvas.getCurrentPageContent()
        print(f"getCurrentPageContent(): {len(current_content)} bytes")
        print(f"  Content: {current_content[:200]}...")
        
        # Try to modify it (this probably won't work but worth testing)
        print("  Trying to inject BDC into current content...")
        modified_content = current_content.replace(b'BT', b'/Figure <</MCID 0>> BDC\nBT')
        print(f"  Modified length: {len(modified_content)}")
        
    except Exception as e:
        print(f"getCurrentPageContent() error: {e}")
    
    canvas.save()
    temp_file.close()
    
    # Check the final PDF content
    print()
    print("Final PDF content analysis:")
    with open(temp_file.name, 'rb') as f:
        pdf_content = f.read().decode('latin1', errors='ignore')
        
    if 'Test text' in pdf_content:
        print("✅ Test text found in PDF")
    
    # Look for the actual content stream structure
    import re
    stream_pattern = r'stream\s*\n(.*?)\nendstream'
    streams = re.findall(stream_pattern, pdf_content, re.DOTALL)
    
    if streams:
        print(f"Found {len(streams)} content streams:")
        for i, stream in enumerate(streams):
            print(f"  Stream {i}: {stream[:100]}...")
    
    print(f"\nTemporary PDF created at: {temp_file.name}")

if __name__ == "__main__":
    debug_canvas_internals()