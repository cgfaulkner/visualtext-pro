#!/usr/bin/env python3
"""
Analyze PDF structure to find where BDC/EMC operators should be
"""

import re
from pathlib import Path

def analyze_pdf_structure():
    """Analyze the complete PDF structure."""
    
    pdf_path = Path("test_true_pdfua.pdf")
    if not pdf_path.exists():
        print("❌ Test PDF not found.")
        return
    
    print("Complete PDF Structure Analysis")
    print("=" * 50)
    
    try:
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()
        
        # Try both binary and text analysis
        print("📄 Binary analysis:")
        print(f"  File size: {len(pdf_content):,} bytes")
        
        # Search for BDC/EMC in binary
        bdc_binary = b'BDC'
        emc_binary = b'EMC'
        
        bdc_count = pdf_content.count(bdc_binary)
        emc_count = pdf_content.count(emc_binary)
        
        print(f"  BDC occurrences (binary): {bdc_count}")
        print(f"  EMC occurrences (binary): {emc_count}")
        
        # Find positions and context
        for i, match_start in enumerate(re.finditer(bdc_binary, pdf_content)):
            pos = match_start.start()
            context_start = max(0, pos - 50)
            context_end = min(len(pdf_content), pos + 50)
            context = pdf_content[context_start:context_end]
            try:
                context_str = context.decode('latin1', errors='ignore')
                print(f"  BDC {i+1} at position {pos}: {repr(context_str)}")
            except:
                print(f"  BDC {i+1} at position {pos}: {context}")
        
        print()
        
        # Try text analysis
        print("📄 Text analysis:")
        try:
            pdf_text = pdf_content.decode('latin1', errors='ignore')
            
            # Look for all PDF objects
            obj_pattern = r'(\d+\s+\d+\s+obj.*?endobj)'
            objects = re.findall(obj_pattern, pdf_text, re.DOTALL)
            
            print(f"  Found {len(objects)} PDF objects")
            
            # Analyze each object
            for i, obj in enumerate(objects):
                if 'stream' in obj.lower():
                    print(f"  Object {i+1} contains stream")
                    
                    # Extract stream content
                    stream_match = re.search(r'stream\s*\n(.*?)\nendstream', obj, re.DOTALL)
                    if stream_match:
                        stream_content = stream_match.group(1)
                        
                        # Check for drawing operators
                        drawing_ops = ['BT', 'ET', 'Tj', 'Do', 'Tm', 'drawImage']
                        has_drawing = any(op in stream_content for op in drawing_ops)
                        
                        if has_drawing:
                            print(f"    Contains drawing operators")
                            print(f"    Stream content: {repr(stream_content[:200])}...")
                            
                            if 'BDC' in stream_content:
                                print(f"    ✅ Contains BDC")
                            else:
                                print(f"    ❌ No BDC")
                                
                            if 'EMC' in stream_content:
                                print(f"    ✅ Contains EMC")
                            else:
                                print(f"    ❌ No EMC")
                        else:
                            print(f"    Non-drawing stream")
                    else:
                        print(f"    Could not extract stream content")
                        
                elif any(keyword in obj.lower() for keyword in ['bdc', 'emc', 'mcid', 'figure']):
                    print(f"  Object {i+1} contains BDC/EMC/MCID/Figure keywords")
                    print(f"    Content: {obj[:300]}...")
                    
        except Exception as e:
            print(f"  Text analysis error: {e}")
            
    except Exception as e:
        print(f"❌ Error analyzing PDF: {e}")

if __name__ == "__main__":
    analyze_pdf_structure()