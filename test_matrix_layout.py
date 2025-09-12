#!/usr/bin/env python3
"""
Demo script to test the new matrix-style approval document layout.
Creates a sample report to verify formatting and styling.
"""

import sys
from pathlib import Path

# Add the project root to path
sys.path.insert(0, str(Path(__file__).parent))

from approval.docx_alt_review import generate_alt_review_doc

def create_sample_data():
    """Create sample processed_images data for testing."""
    return [
        {
            "slide_number": 1,
            "image_number": 1,
            "image_path": None,  # No thumbnail for this test
            "current_alt": "A medical diagram showing the heart",
            "suggested_alt": "A medical diagram showing the heart anatomy with labeled chambers",
            "image_key": "slide_1_shapeid_123_hash_abc12345",
            "slide_title": "Introduction to Cardiology",
            "slide_notes": "This slide introduces basic heart anatomy"
        },
        {
            "slide_number": 1,
            "image_number": 2,
            "image_path": None,
            "current_alt": "",  # Missing current ALT (will be processed)
            "suggested_alt": "Graph showing heart rate variability over time",
            "image_key": "slide_1_shapeid_124_hash_def67890",
            "slide_title": "Introduction to Cardiology",
            "slide_notes": ""
        },
        {
            "slide_number": 2,
            "image_number": 1,
            "image_path": None,
            "current_alt": "Logo image",  # Will mirror to suggested
            "suggested_alt": "Different suggestion",
            "image_key": "slide_2_shapeid_125_hash_ghi11111",
            "slide_title": "Methodology",
            "slide_notes": "Study methodology and approach"
        },
        {
            "slide_number": 2,
            "image_number": 2,
            "image_path": None,
            "current_alt": "undefined",  # Skip value - will generate
            "suggested_alt": "Bar chart comparing patient outcomes",
            "image_key": "slide_2_shapeid_126_hash_jkl22222",
            "slide_title": "Methodology",
            "slide_notes": ""
        },
        {
            "slide_number": 3,
            "image_number": 1,
            "image_path": None,
            "current_alt": "Chart showing patient outcomes across different treatment groups with statistical significance indicators",
            "suggested_alt": "Different generated suggestion",
            "image_key": "slide_3_shapeid_127_hash_mno33333",
            "slide_title": "Results",
            "slide_notes": "Key findings from the clinical trial"
        }
    ]

def main():
    """Generate a sample matrix-style approval document."""
    print("🔄 Generating sample matrix-style approval document...")
    
    # Create sample data
    sample_data = create_sample_data()
    
    # Generate the document
    output_path = "sample_matrix_approval_report.docx"
    lecture_title = "Cardiology Research Presentation"
    
    try:
        generated_path = generate_alt_review_doc(
            processed_images=sample_data,
            lecture_title=lecture_title,
            output_path=output_path,
            original_pptx_path=None  # No source PPTX for this test
        )
        
        print(f"✅ Sample approval document generated: {generated_path}")
        print("\n📋 Document features:")
        print("  • PORTRAIT orientation with 0.75\" margins (enforced at start & end)")
        print("  • Opens in Print Layout mode (110% zoom)")
        print("  • Professional header with title and timestamp")
        print("  • Footer with filename and page numbers")
        print("  • Summary statistics bar with improved ALT text logic")
        print("  • Fixed-width table perfectly fitting portrait (7.3\" exactly):")
        print("    - Slide # (0.4\" - centered, bold)")
        print("    - Image # (0.5\" - centered, bold)")
        print("    - Thumbnail (0.9\" - max 1.05\" x 0.85\", vertically centered)")
        print("    - Current ALT Text (1.8\" - yellow highlight if missing)")
        print("    - Suggested ALT Text (1.8\" - mirrors current when valid)")
        print("    - Decorative? (1.2\" - ☐ NEVER WRAPS TO LETTERS)")
        print("    - Review Notes (0.7\" - with image key at bottom)")
        print("  • Total width: 7.3\" = exact fit for 8.5\" page with 0.6\" margins")
        print("  • Smart ALT processing: mirrors existing ALT when valid")
        print("  • Skip set logic: handles '', 'undefined', '(None)', 'N/A', etc.")
        print("  • Zebra striping on alternating rows")
        print("  • Header repeats on every page")
        print("  • Fixed table width: autofit = False")
        print("  • Calibri 10.5-11pt font with 1.0 line spacing")
        print("  • Top-left cell alignment, 6pt space-after")
        
        print(f"\n📖 Open '{generated_path}' in Microsoft Word to review the layout!")
        
    except Exception as e:
        print(f"❌ Error generating document: {e}")
        raise

if __name__ == "__main__":
    main()