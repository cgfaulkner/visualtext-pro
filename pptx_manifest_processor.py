#!/usr/bin/env python3
"""
PPTX Manifest Processor - Single Source of Truth
================================================

Final wired implementation using the manifest-based architecture:
- Single manifest.jsonl as SSOT for all ALT text decisions
- No double LLaVA calls - cached and preserve-first logic
- Both PPTX injection and DOCX review read from same manifest
- Complete decision logging for traceability

This solves the "missing ALT" problem by reading actual PPTX ALT text
rather than making assumptions based on thumbnails.
"""

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import path validation module (must come after sys.path setup)
from shared.path_validator import sanitize_input_path, validate_output_path, SecurityError

# Import manifest-based components
from manifest_processor import ManifestProcessor
from manifest_injector import inject_from_manifest, validate_manifest_for_injection
from manifest_docx_builder import generate_review_from_manifest
from alt_manifest import AltManifest
from config_manager import ConfigManager

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main():
    """Manifest-based PPTX processor CLI."""
    parser = argparse.ArgumentParser(
        description='PPTX ALT Text Processor - Manifest-Based (Single Source of Truth)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline: extract -> generate -> inject (preserve mode)
  python pptx_manifest_processor.py process presentation.pptx
  
  # Generate review document only (no injection)
  python pptx_manifest_processor.py process presentation.pptx --review-only
  
  # Both injection and review document
  python pptx_manifest_processor.py process presentation.pptx --review-doc
  
  # Inject only from existing manifest
  python pptx_manifest_processor.py inject presentation.pptx --manifest alt_manifest.jsonl
  
  # Review only from existing manifest
  python pptx_manifest_processor.py review --manifest alt_manifest.jsonl --output review.docx
  
  # Replace mode (overwrite existing ALT text)
  python pptx_manifest_processor.py process presentation.pptx --mode replace

Key Benefits:
- No double LLaVA calls (cached by image hash)
- Preserve existing ALT text by default
- DOCX shows actual PPTX ALT text (not "missing")
- Complete traceability in logs and manifest
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Processing commands')
    
    # Process command - full pipeline
    process_parser = subparsers.add_parser('process', help='Run extraction and generation')
    process_parser.add_argument('input_file', help='Input PPTX file')
    process_parser.add_argument('-o', '--output', help='Output PPTX file (default: overwrite input)')
    process_parser.add_argument('--mode', choices=['preserve', 'replace'], default='preserve',
                               help='ALT text handling mode (default: preserve existing)')
    process_parser.add_argument('--review-doc', action='store_true',
                               help='Generate DOCX review document in addition to injection')
    process_parser.add_argument('--review-only', action='store_true',
                               help='Generate review document only, skip injection')
    process_parser.add_argument('--inject-only', action='store_true',
                               help='Inject into PPTX only, skip review document')
    process_parser.add_argument('--review-out', help='Output path for review document')
    process_parser.add_argument('--manifest', help='Path for manifest file (default: auto-generated)')
    
    # Inject command - from existing manifest
    inject_parser = subparsers.add_parser('inject', help='Inject from existing manifest')
    inject_parser.add_argument('input_file', help='Input PPTX file')
    inject_parser.add_argument('--manifest', required=True, help='Manifest JSONL file')
    inject_parser.add_argument('-o', '--output', help='Output PPTX file')
    inject_parser.add_argument('--mode', choices=['preserve', 'replace'], default='preserve',
                               help='Injection mode')
    
    # Review command - from existing manifest
    review_parser = subparsers.add_parser('review', help='Generate review document from manifest')
    review_parser.add_argument('--manifest', required=True, help='Manifest JSONL file')
    review_parser.add_argument('-o', '--output', required=True, help='Output DOCX file')
    review_parser.add_argument('--title', help='Document title')
    
    # Validate command - check manifest
    validate_parser = subparsers.add_parser('validate', help='Validate manifest file')
    validate_parser.add_argument('manifest', help='Manifest JSONL file to validate')
    
    # Global options
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--force-regenerate', action='store_true',
                       help='Force regeneration even if cache exists')
    parser.add_argument('--no-thumbnails', action='store_true',
                       help='Skip thumbnail generation (faster processing)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    setup_logging(args.verbose)
    
    try:
        if args.command == 'process':
            return cmd_process(args)
        elif args.command == 'inject':
            return cmd_inject(args)
        elif args.command == 'review':
            return cmd_review(args)
        elif args.command == 'validate':
            return cmd_validate(args)
        else:
            parser.print_help()
            return 1
            
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        print(f"💥 Error: {e}")
        return 1


def cmd_process(args) -> int:
    """Handle 'process' command - full pipeline."""
    # Validate input file path
    try:
        validated_input = sanitize_input_path(args.input_file)
        input_path = validated_input
    except SecurityError as e:
        print(f"Security Error (input): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid input path: {e}")
        return 1

    if not input_path.exists():
        print(f"❌ Input file not found: {args.input_file}")
        return 1

    # Validate output path if provided
    if args.output:
        try:
            validated_output = validate_output_path(args.output)
            output_path = str(validated_output)
        except SecurityError as e:
            print(f"Security Error (output): {e}")
            return 1
        except ValueError as e:
            print(f"Invalid output path: {e}")
            return 1
    else:
        output_path = str(input_path)

    # Determine and validate manifest path
    if args.manifest:
        try:
            validated_manifest = validate_output_path(args.manifest)
            manifest_path = validated_manifest
        except SecurityError as e:
            print(f"Security Error (manifest): {e}")
            return 1
        except ValueError as e:
            print(f"Invalid manifest path: {e}")
            return 1
    else:
        manifest_path = input_path.parent / f"{input_path.stem}_alt_manifest.jsonl"
    
    logger.info(f"Processing {input_path.name} with manifest SSOT")
    logger.info(f"Manifest: {manifest_path}")
    logger.info(f"Mode: {args.mode}")

    start_time = time.time()
    run_id = str(uuid.uuid4())
    
    try:
        # Load configuration and ALT generator
        config_manager = ConfigManager(args.config)
        
        from unified_alt_generator import FlexibleAltGenerator
        alt_generator = FlexibleAltGenerator(config_manager)
        
        # Initialize manifest processor  
        processor = ManifestProcessor(config_manager, alt_generator)
        
        # Step 1: Extract and generate ALT text using manifest
        process_result = processor.extract_and_generate(
            input_path,
            manifest_path,
            mode=args.mode,
            generate_thumbnails=not args.no_thumbnails
        )
        
        if not process_result['success']:
            print(f"❌ Processing failed: {process_result.get('error', 'Unknown error')}")
            return 1
        
        # Log processing results
        stats = process_result['statistics']
        print(f"📊 Extraction and Generation Complete:")
        print(f"   Total images: {stats['total_entries']}")
        print(f"   Current ALT found: {stats['with_current_alt']}")
        print(f"   Suggested ALT available: {stats['with_suggested_alt']}")
        print(f"   LLaVA calls made: {stats['llava_calls_made']}")
        print(f"   Source breakdown: Existing={stats['source_existing']}, Generated={stats['source_generated']}, Cached={stats['source_cached']}")
        
        # Step 2: PPTX injection (unless review-only)
        if not args.review_only:
            inject_result = inject_from_manifest(
                str(input_path),
                str(manifest_path),
                output_path,
                mode=args.mode,
                run_id=run_id,
            )
            
            if inject_result['success']:
                inject_stats = inject_result.get('statistics', inject_result)
                print(f"✅ PPTX injection completed!")
                print(f"   Images updated: {inject_stats.get('injected_successfully', 0)}")
                print(f"   Output: {output_path}")
            else:
                print(f"❌ PPTX injection failed: {inject_result.get('error', 'Unknown error')}")
                if not (args.review_doc or args.review_only):
                    return 1
        
        # Step 3: DOCX review document (if requested)
        if args.review_doc or args.review_only:
            # Determine review output path
            if args.review_out:
                review_output = args.review_out
            else:
                review_output = str(input_path.with_suffix('.review.docx'))
            
            title = getattr(args, 'title', None) or input_path.stem
            
            generate_review_from_manifest(
                str(manifest_path),
                review_output,
                title=title,
                portrait=True,
                run_id=run_id,
            )
            
            print(f"📋 Review document generated: {review_output}")
            print(f"   ✅ Shows actual PPTX ALT text (not 'missing')")
            print(f"   ✅ No duplicate LLaVA calls made")
        
        # Show final timing
        total_time = time.time() - start_time
        print(f"⏱️ Total processing time: {total_time:.2f}s")
        
        # Remind about manifest for future use
        print(f"💾 Manifest saved: {manifest_path}")
        print(f"   Use --manifest {manifest_path} for future inject/review operations")
        
        return 0
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        print(f"❌ Processing failed: {e}")
        return 1


def cmd_inject(args) -> int:
    """Handle 'inject' command - inject from existing manifest."""
    # Validate input file path
    try:
        validated_input = sanitize_input_path(args.input_file)
        input_path = validated_input
    except SecurityError as e:
        print(f"Security Error (input): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid input path: {e}")
        return 1

    # Validate manifest path
    try:
        validated_manifest = sanitize_input_path(args.manifest)
        manifest_path = validated_manifest
    except SecurityError as e:
        print(f"Security Error (manifest): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid manifest path: {e}")
        return 1

    if not input_path.exists():
        print(f"❌ Input file not found: {args.input_file}")
        return 1

    if not manifest_path.exists():
        print(f"❌ Manifest file not found: {args.manifest}")
        return 1

    # Validate output path if provided
    if args.output:
        try:
            validated_output = validate_output_path(args.output)
            output_path = str(validated_output)
        except SecurityError as e:
            print(f"Security Error (output): {e}")
            return 1
        except ValueError as e:
            print(f"Invalid output path: {e}")
            return 1
    else:
        output_path = str(input_path)

    logger.info(f"Injecting from manifest: {manifest_path.name}")
    run_id = str(uuid.uuid4())
    
    # Validate manifest first
    validation = validate_manifest_for_injection(str(manifest_path))
    if not validation['valid']:
        print(f"❌ Manifest validation failed: {validation['error']}")
        return 1
    
    print(f"📊 Manifest validation:")
    print(f"   Total entries: {validation['total_entries']}")
    print(f"   Injectable entries: {validation['injectable_entries']}")
    print(f"   LLaVA calls in manifest: {validation['llava_calls_in_manifest']}")
    
    # Perform injection
    result = inject_from_manifest(
        str(input_path),
        str(manifest_path),
        output_path,
        mode=args.mode,
        run_id=run_id,
    )
    
    if result['success']:
        stats = result.get('statistics', result)
        print(f"✅ ALT text injection completed!")
        print(f"   Images updated: {stats.get('injected_successfully', 0)}")
        print(f"   Output: {output_path}")
        return 0
    else:
        print(f"❌ Injection failed: {result.get('error', 'Unknown error')}")
        return 1


def cmd_review(args) -> int:
    """Handle 'review' command - generate review document from manifest."""
    # Validate manifest path
    try:
        validated_manifest = sanitize_input_path(args.manifest)
        manifest_path = validated_manifest
    except SecurityError as e:
        print(f"Security Error (manifest): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid manifest path: {e}")
        return 1

    # Validate output path
    try:
        validated_output = validate_output_path(args.output)
    except SecurityError as e:
        print(f"Security Error (output): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid output path: {e}")
        return 1

    if not manifest_path.exists():
        print(f"❌ Manifest file not found: {args.manifest}")
        return 1
    
    logger.info(f"Generating review document from manifest")
    run_id = str(uuid.uuid4())
    
    try:
        generate_review_from_manifest(
            str(manifest_path),
            str(validated_output),
            title=args.title,
            portrait=True,
            run_id=run_id,
        )
        
        print(f"✅ Review document generated: {args.output}")
        print(f"   ✅ Shows actual ALT text from manifest SSOT")
        print(f"   ✅ No LLaVA calls made during review generation")
        return 0
        
    except Exception as e:
        logger.error(f"Review generation failed: {e}", exc_info=True)
        print(f"❌ Review generation failed: {e}")
        return 1


def cmd_validate(args) -> int:
    """Handle 'validate' command - validate manifest file."""
    manifest_path = Path(args.manifest)
    
    if not manifest_path.exists():
        print(f"❌ Manifest file not found: {args.manifest}")
        return 1
    
    try:
        # Load and validate manifest
        manifest = AltManifest(manifest_path)
        entries = manifest.get_all_entries()
        stats = manifest.get_statistics()
        
        print(f"📊 Manifest Validation: {manifest_path}")
        print(f"   Total entries: {len(entries)}")
        print(f"   With current ALT: {stats['with_current_alt']}")
        print(f"   With suggested ALT: {stats['with_suggested_alt']}")
        print(f"   Source breakdown:")
        print(f"     - Existing (preserved): {stats['source_existing']}")
        print(f"     - Generated (LLaVA): {stats['source_generated']}")
        print(f"     - Cached (reused): {stats['source_cached']}")
        print(f"   LLaVA calls made: {stats['llava_calls_made']}")
        
        # Check for injection readiness
        validation = validate_manifest_for_injection(str(manifest_path))
        if validation['valid']:
            print(f"✅ Manifest is valid for injection")
            print(f"   Injectable entries: {validation['injectable_entries']}")
        else:
            print(f"❌ Manifest issues: {validation['error']}")
            
        return 0
        
    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        print(f"❌ Validation failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())