#!/usr/bin/env python3
"""
Synchronized Pipeline Test
==========================

Comprehensive test script for the synchronized PPT/DOCX pipeline.
Demonstrates that PPT injector and DOCX builder outputs are perfectly aligned
using the ALT manifest as single source of truth.

Usage:
    python test_synchronized_pipeline.py <input.pptx>

This script will:
1. Extract all visual elements (pictures, shapes, lines, etc.) to manifest
2. Generate ALT text with single-pass LLaVA calls + sentence-safe normalization  
3. Inject ALT text into PPTX using manifest final_alt field only
4. Build DOCX review using manifest final_alt field only
5. Validate that PPTX and DOCX outputs are perfectly synchronized
6. Generate comprehensive validation report
"""

import sys
import logging
import time
from pathlib import Path

# Add shared directory to path for imports
sys.path.insert(0, str(Path(__file__).parent / "shared"))

def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('synchronized_pipeline_test.log')
        ]
    )

def main():
    """Run the synchronized pipeline test."""
    if len(sys.argv) != 2:
        print("Usage: python test_synchronized_pipeline.py <input.pptx>")
        sys.exit(1)
    
    input_pptx = Path(sys.argv[1])
    if not input_pptx.exists():
        print(f"Error: Input file not found: {input_pptx}")
        sys.exit(1)
    
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Starting Synchronized Pipeline Test")
    logger.info(f"Input PPTX: {input_pptx}")
    
    # Setup output paths
    base_name = input_pptx.stem
    output_dir = input_pptx.parent / f"{base_name}_synchronized_test"
    output_dir.mkdir(exist_ok=True)
    
    manifest_path = output_dir / "alt_manifest.jsonl"
    output_pptx = output_dir / f"{base_name}_with_alt.pptx"
    output_docx = output_dir / f"{base_name}_review.docx"
    validation_report = output_dir / "synchronization_validation.json"
    
    logger.info(f"Output directory: {output_dir}")
    
    try:
        # Step 1: Extract and Generate with Manifest Processor
        logger.info("\n" + "="*60)
        logger.info("📋 STEP 1: MANIFEST PROCESSING")
        logger.info("="*60)
        
        from manifest_processor import ManifestProcessor
        from unified_alt_generator import FlexibleAltGenerator
        from config_manager import ConfigManager
        
        config_manager = ConfigManager()
        alt_generator = FlexibleAltGenerator(config_manager)
        processor = ManifestProcessor(config_manager, alt_generator)
        
        # Run pre-flight tests
        pre_flight_results = alt_generator.run_pre_flight_tests()
        if not pre_flight_results.get('overall_success', False):
            logger.error("❌ Pre-flight tests failed - cannot proceed with generation")
            logger.error(f"Failed tests: {pre_flight_results.get('summary', {}).get('failed_tests', [])}")
            return False
        
        logger.info("✅ Pre-flight tests passed")
        
        # Process with manifest
        start_time = time.time()
        processing_results = processor.extract_and_generate(
            input_pptx, 
            manifest_path,
            mode="preserve",  # Use preserve mode to test synchronization
            generate_thumbnails=True
        )
        processing_time = time.time() - start_time
        
        if not processing_results['success']:
            logger.error(f"❌ Manifest processing failed: {processing_results.get('error')}")
            return False
        
        logger.info(f"✅ Manifest processing completed in {processing_time:.2f}s")
        logger.info(f"   Total entries: {processing_results['total_entries']}")
        logger.info(f"   LLaVA calls made: {processing_results['llava_calls_made']}")
        logger.info(f"   With suggested ALT: {processing_results['with_suggested_alt']}")
        
        # Step 2: PPT Injection from Manifest
        logger.info("\n" + "="*60)
        logger.info("💉 STEP 2: PPTX ALT TEXT INJECTION")
        logger.info("="*60)
        
        from manifest_injector import inject_from_manifest, validate_manifest_for_injection
        
        # Validate manifest first
        validation = validate_manifest_for_injection(str(manifest_path))
        if not validation['valid']:
            logger.error(f"❌ Manifest validation failed: {validation.get('error')}")
            return False
        
        logger.info(f"✅ Manifest validation passed")
        logger.info(f"   Total entries: {validation['total_entries']}")
        logger.info(f"   Injectable entries: {validation['injectable_entries']}")
        logger.info(f"   By shape type: {validation['by_shape_type']}")
        logger.info(f"   By decision reason: {validation['by_decision_reason']}")
        
        # Perform injection
        start_time = time.time()
        injection_results = inject_from_manifest(
            str(input_pptx),
            str(manifest_path),
            str(output_pptx),
            mode="preserve"
        )
        injection_time = time.time() - start_time
        
        if not injection_results['success']:
            logger.error(f"❌ PPTX injection failed: {injection_results.get('error')}")
            return False
        
        logger.info(f"✅ PPTX injection completed in {injection_time:.2f}s")
        logger.info(f"   Elements updated: {injection_results['injected_successfully']}")
        logger.info(f"   Output PPTX: {output_pptx}")
        
        # Step 3: DOCX Review Generation from Manifest
        logger.info("\n" + "="*60)
        logger.info("📄 STEP 3: DOCX REVIEW GENERATION")
        logger.info("="*60)
        
        from manifest_docx_builder import generate_review_from_manifest
        
        start_time = time.time()
        docx_path = generate_review_from_manifest(
            str(manifest_path),
            str(output_docx),
            title=f"ALT Text Review - {base_name}",
            portrait=True
        )
        docx_time = time.time() - start_time
        
        logger.info(f"✅ DOCX review generated in {docx_time:.2f}s")
        logger.info(f"   Output DOCX: {docx_path}")
        
        # Step 4: Synchronization Validation
        logger.info("\n" + "="*60)
        logger.info("🔍 STEP 4: SYNCHRONIZATION VALIDATION")
        logger.info("="*60)
        
        from sync_validator import validate_ppt_docx_synchronization, print_validation_summary
        
        start_time = time.time()
        validation_results = validate_ppt_docx_synchronization(
            str(manifest_path),
            str(output_pptx),
            str(output_docx),
            str(validation_report)
        )
        validation_time = time.time() - start_time
        
        logger.info(f"✅ Synchronization validation completed in {validation_time:.2f}s")
        
        # Print detailed validation summary
        print_validation_summary(validation_results)
        
        # Step 5: Final Summary
        logger.info("\n" + "="*60)
        logger.info("📊 PIPELINE SUMMARY")
        logger.info("="*60)
        
        total_time = processing_time + injection_time + docx_time + validation_time
        synchronized = validation_results.get('synchronized', False)
        
        logger.info(f"✅ Synchronized Pipeline Test Complete")
        logger.info(f"   Total execution time: {total_time:.2f}s")
        logger.info(f"   Synchronization status: {'✅ SYNCHRONIZED' if synchronized else '❌ NOT SYNCHRONIZED'}")
        logger.info(f"   Perfect matches: {validation_results.get('perfect_matches', 0)}/{validation_results.get('total_entries', 0)}")
        
        # Performance breakdown
        logger.info(f"\n⏱️  Performance Breakdown:")
        logger.info(f"   Manifest processing: {processing_time:.2f}s")
        logger.info(f"   PPTX injection: {injection_time:.2f}s") 
        logger.info(f"   DOCX generation: {docx_time:.2f}s")
        logger.info(f"   Validation: {validation_time:.2f}s")
        
        # Output file summary
        logger.info(f"\n📁 Generated Files:")
        logger.info(f"   Manifest: {manifest_path}")
        logger.info(f"   PPTX with ALT: {output_pptx}")
        logger.info(f"   DOCX review: {output_docx}")
        logger.info(f"   Validation report: {validation_report}")
        logger.info(f"   Log file: synchronized_pipeline_test.log")
        
        if synchronized:
            logger.info("\n🎉 SUCCESS: PPT and DOCX outputs are perfectly synchronized!")
            logger.info("   The single source of truth (ALT manifest) successfully eliminated all discrepancies.")
            logger.info("   Both outputs now show identical ALT text for all elements.")
        else:
            high_severity = validation_results.get('high_severity_issues', 0)
            logger.warning(f"\n⚠️  WARNING: Found {high_severity} high-severity synchronization issues")
            logger.warning("   Check the validation report for detailed discrepancy analysis.")
            logger.warning("   The manifest approach should eliminate these issues - investigation needed.")
        
        return synchronized
        
    except Exception as e:
        logger.error(f"❌ Pipeline test failed with exception: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)