#!/usr/bin/env python3
"""
Validate PDF/UA content to verify BDC/EMC operators and structure elements
"""

import re
from pathlib import Path

def validate_pdfua_content():
    """Validate the PDF/UA content for proper BDC/EMC and structure elements."""
    
    pdf_path = Path("test_true_pdfua.pdf")
    if not pdf_path.exists():
        print("❌ Test PDF not found. Run test_true_pdfua.py first.")
        return
    
    print("PDF/UA Content Validation")
    print("=" * 40)
    
    try:
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read().decode('latin1', errors='ignore')
        
        print(f"📄 PDF file size: {len(pdf_content):,} bytes")
        print()
        
        # 1. Check for BDC operators
        print("🔍 Checking for BDC operators...")
        bdc_patterns = [
            r'/Figure\s*<<\s*/MCID\s+\d+\s*>>\s*BDC',
            r'/Figure.*MCID.*BDC',
            r'BDC'
        ]
        
        bdc_found = False
        for pattern in bdc_patterns:
            matches = re.findall(pattern, pdf_content, re.IGNORECASE)
            if matches:
                print(f"  ✅ Found BDC pattern '{pattern}': {len(matches)} matches")
                for match in matches[:3]:  # Show first 3 matches
                    print(f"    - {match}")
                bdc_found = True
            else:
                print(f"  ❌ No matches for pattern '{pattern}'")
        
        if not bdc_found:
            # Try to find any BDC-like content
            bdc_context = []
            lines = pdf_content.split('\n')
            for i, line in enumerate(lines):
                if 'BDC' in line or 'MCID' in line:
                    start = max(0, i-2)
                    end = min(len(lines), i+3)
                    context = '\n'.join(lines[start:end])
                    bdc_context.append(f"Line {i}: {context}")
            
            if bdc_context:
                print("  📝 Found BDC/MCID context:")
                for ctx in bdc_context[:3]:
                    print(f"    {ctx}")
        
        print()
        
        # 2. Check for EMC operators
        print("🔍 Checking for EMC operators...")
        emc_count = pdf_content.count('EMC')
        if emc_count > 0:
            print(f"  ✅ Found {emc_count} EMC operators")
        else:
            print("  ❌ No EMC operators found")
        
        print()
        
        # 3. Check for structure elements
        print("🔍 Checking for structure elements...")
        struct_patterns = [
            r'/Type\s*/StructElem',
            r'/S\s*/Figure',
            r'/Alt\s*\(',
            r'/K\s+\d+',
            r'StructTreeRoot'
        ]
        
        for pattern in struct_patterns:
            matches = re.findall(pattern, pdf_content)
            if matches:
                print(f"  ✅ Found structure pattern '{pattern}': {len(matches)} matches")
            else:
                print(f"  ❌ No matches for structure pattern '{pattern}'")
        
        print()
        
        # 4. Check for PDF/UA metadata
        print("🔍 Checking for PDF/UA compliance markers...")
        compliance_patterns = [
            r'/Marked\s+true',
            r'/Lang\s*\(',
            r'/RoleMap',
            r'ParentTree',
            r'pdfuaid:part'
        ]
        
        for pattern in compliance_patterns:
            matches = re.findall(pattern, pdf_content, re.IGNORECASE)
            if matches:
                print(f"  ✅ Found compliance marker '{pattern}': {len(matches)} matches")
            else:
                print(f"  ❌ No matches for compliance marker '{pattern}'")
        
        print()
        
        # 5. Check for MCID values
        print("🔍 Checking for MCID values...")
        mcid_pattern = r'/MCID\s+(\d+)'
        mcid_matches = re.findall(mcid_pattern, pdf_content)
        if mcid_matches:
            mcids = [int(m) for m in mcid_matches]
            print(f"  ✅ Found MCIDs: {sorted(set(mcids))}")
            
            # Check if MCIDs start at 0 and are sequential per page
            expected_mcids = list(range(max(mcids) + 1))
            if sorted(set(mcids)) == expected_mcids:
                print("  ✅ MCIDs are properly sequential starting from 0")
            else:
                print(f"  ⚠️ MCID sequence may have gaps. Expected: {expected_mcids}")
        else:
            print("  ❌ No MCID values found")
        
        print()
        
        # 6. Overall assessment
        print("📊 Overall Assessment:")
        
        has_bdc = bdc_found
        has_emc = emc_count > 0
        has_structure = '/StructTreeRoot' in pdf_content
        has_alt = '/Alt' in pdf_content
        has_marked = '/Marked' in pdf_content
        
        score = sum([has_bdc, has_emc, has_structure, has_alt, has_marked])
        
        print(f"  BDC operators: {'✅' if has_bdc else '❌'}")
        print(f"  EMC operators: {'✅' if has_emc else '❌'}")
        print(f"  Structure tree: {'✅' if has_structure else '❌'}")
        print(f"  ALT text: {'✅' if has_alt else '❌'}")
        print(f"  Marked info: {'✅' if has_marked else '❌'}")
        print(f"  Score: {score}/5")
        
        if score >= 4:
            print("\n🎉 PDF/UA compliance looks good!")
        elif score >= 2:
            print(f"\n⚠️ Partial PDF/UA compliance ({score}/5)")
        else:
            print(f"\n❌ Low PDF/UA compliance ({score}/5)")
            
    except Exception as e:
        print(f"❌ Error validating PDF content: {e}")

if __name__ == "__main__":
    validate_pdfua_content()