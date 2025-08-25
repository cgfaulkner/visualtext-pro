#!/usr/bin/env python3
"""
Test script for the PDF recreation workflow
Demonstrates how to use the ReportLab-based accessibility recreation
"""

import logging
import sys
from pathlib import Path

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

from config_manager import ConfigManager
from pdf_processor import PDFAccessibilityProcessor

def test_recreation_workflow():
    """Test the recreation workflow with a sample configuration."""
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    print("PDF Recreation Workflow Test")
    print("=" * 50)
    
    try:
        # Create configuration that enables recreation workflow
        config_manager = ConfigManager()
        
        # Override processing config to use recreation workflow
        if 'pdf_processing' not in config_manager.config:
            config_manager.config['pdf_processing'] = {}
        
        config_manager.config['pdf_processing']['use_recreation_workflow'] = True
        config_manager.config['pdf_processing']['skip_decorative_images'] = True
        config_manager.config['pdf_processing']['decorative_size_threshold'] = 50
        
        print("Configuration:")
        print(f"  Use recreation workflow: True")
        print(f"  Skip decorative images: True")
        print(f"  Decorative size threshold: 50px")
        print()
        
        # Initialize processor with recreation workflow enabled
        processor = PDFAccessibilityProcessor(config_manager)
        
        # Check if sample PDF exists
        sample_pdf = project_root / "Documents to Review" / "test1_demo.pdf"
        if not sample_pdf.exists():
            print("Sample PDF not found. Please provide a PDF file path as argument.")
            print("Usage: python test_recreation_workflow.py [pdf_file]")
            return 1
        
        pdf_path = sys.argv[1] if len(sys.argv) > 1 else str(sample_pdf)
        output_path = f"accessible_{Path(pdf_path).name}"
        
        print(f"Input PDF: {pdf_path}")
        print(f"Output PDF: {output_path}")
        print()
        
        # Process the PDF using recreation workflow
        print("Starting PDF processing with recreation workflow...")
        result = processor.process_pdf(pdf_path, output_path)
        
        # Display results
        print("\nProcessing Results:")
        print(f"  Success: {result['success']}")
        print(f"  Total images: {result['total_images']}")
        print(f"  Processed: {result['processed_images']}")
        print(f"  Decorative (skipped): {result['decorative_images']}")
        print(f"  Failed: {result['failed_images']}")
        print(f"  Generation time: {result['generation_time']:.2f}s")
        print(f"  Processing time: {result['injection_time']:.2f}s")
        print(f"  Total time: {result['total_time']:.2f}s")
        
        if result['errors']:
            print(f"  Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    - {error}")
        
        print()
        if result['success']:
            print("✅ Recreation workflow completed successfully!")
            print(f"Accessible PDF created: {output_path}")
            print()
            print("The recreated PDF should have:")
            print("  - Proper accessibility structure")
            print("  - Screen reader compatible ALT text")
            print("  - No visible ALT text annotations")
        else:
            print("❌ Recreation workflow failed!")
            return 1
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(test_recreation_workflow())