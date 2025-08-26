#!/usr/bin/env python3
"""
Extract and analyze PDF content streams to verify BDC/EMC operators
"""

import re
from pathlib import Path

def extract_content_streams():
    """Extract and analyze PDF content streams."""
    
    pdf_path = Path("test_true_pdfua.pdf")
    if not pdf_path.exists():
        print("❌ Test PDF not found.")
        return
    
    print("PDF Content Stream Analysis")
    print("=" * 50)
    
    try:
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read().decode('latin1', errors='ignore')
        
        print(f"📄 PDF file size: {len(pdf_content):,} bytes")
        print()
        
        # Extract all content streams
        print("🔍 Extracting content streams...")
        
        # Pattern to find content streams
        stream_pattern = r'stream\s*\n(.*?)\nendstream'
        streams = re.findall(stream_pattern, pdf_content, re.DOTALL)
        
        print(f"Found {len(streams)} content streams")
        print()
        
        for i, stream_content in enumerate(streams):
            print(f"📝 Content Stream {i+1}:")
            print(f"   Length: {len(stream_content)} characters")
            
            # Check if this looks like a page content stream (has drawing operators)
            drawing_ops = ['Tj', 'Do', 'BT', 'ET', 'Tm']
            has_drawing = any(op in stream_content for op in drawing_ops)
            
            if has_drawing:
                print(f"   Type: Page content stream (has drawing operators)")
                print(f"   Content: {repr(stream_content)}")
                print()
                
                # Look specifically for BDC/EMC patterns
                if 'BDC' in stream_content:
                    print(f"   ✅ Contains BDC operator")
                    # Find the lines with BDC
                    lines = stream_content.split('\n')
                    for j, line in enumerate(lines):
                        if 'BDC' in line:
                            print(f"   BDC line {j}: {repr(line)}")
                else:
                    print(f"   ❌ No BDC operator found")
                
                if 'EMC' in stream_content:
                    print(f"   ✅ Contains EMC operator")
                    lines = stream_content.split('\n')
                    for j, line in enumerate(lines):
                        if 'EMC' in line:
                            print(f"   EMC line {j}: {repr(line)}")
                else:
                    print(f"   ❌ No EMC operator found")
                
                if 'MCID' in stream_content:
                    print(f"   ✅ Contains MCID")
                    # Extract MCID values
                    mcid_matches = re.findall(r'MCID\s+(\d+)', stream_content)
                    if mcid_matches:
                        print(f"   MCIDs found: {mcid_matches}")
                else:
                    print(f"   ❌ No MCID found")
                
                if 'Figure' in stream_content:
                    print(f"   ✅ Contains Figure tag")
                else:
                    print(f"   ❌ No Figure tag found")
                    
                print()
            else:
                print(f"   Type: Non-page stream (metadata/resources)")
                if len(stream_content) < 200:
                    print(f"   Content: {repr(stream_content)}")
                print()
        
        # Also check if there are any direct BDC/EMC references in the PDF
        print("🔍 Direct BDC/EMC analysis in full PDF:")
        bdc_positions = []
        emc_positions = []
        
        for match in re.finditer(r'BDC', pdf_content):
            pos = match.start()
            context_start = max(0, pos - 50)
            context_end = min(len(pdf_content), pos + 50)
            context = pdf_content[context_start:context_end]
            bdc_positions.append((pos, context))
        
        for match in re.finditer(r'EMC', pdf_content):
            pos = match.start()
            context_start = max(0, pos - 20)
            context_end = min(len(pdf_content), pos + 20)
            context = pdf_content[context_start:context_end]
            emc_positions.append((pos, context))
        
        print(f"BDC occurrences: {len(bdc_positions)}")
        for pos, context in bdc_positions:
            print(f"  Position {pos}: {repr(context)}")
            
        print(f"EMC occurrences: {len(emc_positions)}")
        for pos, context in emc_positions:
            print(f"  Position {pos}: {repr(context)}")
            
    except Exception as e:
        print(f"❌ Error analyzing PDF: {e}")

if __name__ == "__main__":
    extract_content_streams()