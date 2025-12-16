#!/usr/bin/env python3
"""
Clean PPTX ALT Processor - Pipeline Architecture
===============================================

Implementation of the clean three-phase pipeline:
- Phase 1: Scan (visual_index + current_alt_by_key)
- Phase 2: Generate (generated_alt_by_key)  
- Phase 3: Resolve (final_alt_map)

Consumers (decoupled):
- PPTX injection: uses final_alt_map.json
- DOCX review: uses visual_index.json + current_alt_by_key.json + final_alt_map.json
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, Literal

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import path validation module (must come after sys.path setup)
from shared.path_validator import sanitize_input_path, validate_output_path, SecurityError

# Import clean pipeline components
from pipeline_artifacts import RunArtifacts, normalize_final_alt_map
from pipeline_phases import run_pipeline
from docx_review_builder import generate_alt_review_doc
from config_manager import ConfigManager

logger = logging.getLogger(__name__)


def inject_from_map(
    pptx_path: str,
    final_alt_map_path: str,
    mode: Literal["preserve", "replace"] = "preserve",
) -> Dict[str, Any]:
    """Inject ALT text from final_alt_map.json into the PPTX file."""
    logger.info("Injecting ALT text into %s (mode: %s)", pptx_path, mode)
    try:
        with open(final_alt_map_path, "r", encoding="utf-8") as f:
            raw_final_alt_map = json.load(f)

        final_alt_map = normalize_final_alt_map(raw_final_alt_map)

        if not final_alt_map:
            logger.warning("No ALT text mappings found in final_alt_map")
            return {
                "success": True,
                "injected_successfully": 0,
                "total_mappings": 0,
                "skipped_existing": 0,
                "errors": [],
            }

        from core.pptx_alt_injector import PPTXAltTextInjector
        from shared.config_manager import ConfigManager

        config_manager = ConfigManager()
        if mode != "preserve":
            config_manager.override_alt_mode(mode)
        injector = PPTXAltTextInjector(config_manager)

        enriched_mapping = {}
        available_entries = 0

        for key, record in final_alt_map.items():
            existing_alt = (record.get("existing_alt") or "").strip()
            generated_alt = (record.get("generated_alt") or "").strip()
            final_alt = (record.get("final_alt") or "").strip()

            if existing_alt or generated_alt or final_alt:
                available_entries += 1

            enriched_mapping[key] = {
                "existing_alt": existing_alt,
                "generated_alt": generated_alt,
                "final_alt": final_alt or None,
                "decision": record.get("decision"),
                "source_existing": record.get("source_existing"),
                "source_generated": record.get("source_generated"),
                "existing_meaningful": bool(existing_alt),
            }

        if available_entries == 0:
            logger.warning("No ALT text available in final_alt_map for injection")
            return {
                "success": True,
                "injected_successfully": 0,
                "total_mappings": len(final_alt_map),
                "skipped_existing": 0,
                "errors": [],
            }

        result = injector.inject_alt_text_from_mapping(
            pptx_path, enriched_mapping, pptx_path, mode=mode
        )

        if result["success"]:
            stats = result.get("statistics", {})
            logger.info(
                "Injection complete: %s images updated",
                stats.get("injected_successfully", 0),
            )
        else:
            logger.error(
                "Injection failed: %s", result.get("error", "Unknown error")
            )

        return result

    except Exception as e:  # pragma: no cover - pipeline errors
        logger.error("ALT text injection failed: %s", e, exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "injected_successfully": 0,
            "total_mappings": 0,
        }


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def main():
    """Clean pipeline CLI interface."""
    parser = argparse.ArgumentParser(
        description='Clean PPTX ALT Text Processor - Three-Phase Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline: scan -> generate -> resolve -> inject
  python pptx_clean_processor.py process presentation.pptx
  
  # Generate review document only (no injection)
  python pptx_clean_processor.py process presentation.pptx --review-doc-only
  
  # Both injection and review document
  python pptx_clean_processor.py process presentation.pptx --review-doc
  
  # Inject from existing final_alt_map.json
  python pptx_clean_processor.py inject presentation.pptx --alt-map final_alt_map.json
  
  # Build review document from existing artifacts
  python pptx_clean_processor.py review --visual-index visual_index.json 
                                        --current-alt current_alt_by_key.json 
                                        --final-alt final_alt_map.json 
                                        --output review.docx
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Processing commands')
    
    # Process command - full pipeline
    process_parser = subparsers.add_parser('process', help='Run full pipeline')
    process_parser.add_argument('input_file', help='Input PPTX file')
    process_parser.add_argument('-o', '--output', help='Output PPTX file (default: overwrite input)')
    process_parser.add_argument('--review-doc', action='store_true', 
                               help='Generate DOCX review document in addition to injection')
    process_parser.add_argument('--review-doc-only', action='store_true',
                               help='Generate only review document, skip injection')
    process_parser.add_argument('--review-out', help='Output path for review document')
    process_parser.add_argument('--mode', choices=['preserve', 'replace'], default='preserve',
                               help='Injection mode (default: preserve existing ALT text)')
    
    # Inject command - from existing final_alt_map
    inject_parser = subparsers.add_parser('inject', help='Inject from final ALT map')
    inject_parser.add_argument('input_file', help='Input PPTX file')
    inject_parser.add_argument('--alt-map', required=True, help='final_alt_map.json file')
    inject_parser.add_argument('-o', '--output', help='Output PPTX file')
    inject_parser.add_argument('--mode', choices=['preserve', 'replace'], default='preserve',
                               help='Injection mode')
    
    # Review command - from existing artifacts
    review_parser = subparsers.add_parser('review', help='Generate review document from artifacts')
    review_parser.add_argument('--visual-index', required=True, help='visual_index.json file')
    review_parser.add_argument('--current-alt', required=True, help='current_alt_by_key.json file')  
    review_parser.add_argument('--final-alt', required=True, help='final_alt_map.json file')
    review_parser.add_argument('-o', '--output', required=True, help='Output DOCX file')
    review_parser.add_argument('--title', help='Document title')
    
    # Global options
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--force-regenerate', action='store_true',
                       help='Force regeneration even if cache exists')
    parser.add_argument('--mode', choices=['preserve', 'replace'],
                       help='Whether to preserve or replace existing ALT text in PPTX (overrides config)')

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
        else:
            parser.print_help()
            return 1
            
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        print(f"💥 Error: {e}")
        return 1


def cmd_process(args) -> int:
    """Handle 'process' command - run full pipeline."""
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
    
    logger.info(f"Processing {input_path.name} with clean pipeline")
    start_time = time.time()
    
    try:
        # Load configuration
        config_manager = ConfigManager(args.config)

        # Apply CLI mode override if provided
        if args.mode:
            config_manager.override_alt_mode(args.mode)
            logger.info(f"🛠️ ALT mode overridden to: {args.mode}")

        # Log the active ALT mode
        active_mode = config_manager.get_alt_mode()
        logger.info(f"🔧 Active ALT mode: {active_mode}")

        # Get ALT text generator
        # Import here to avoid circular dependencies
        from unified_alt_generator import FlexibleAltGenerator
        alt_generator = FlexibleAltGenerator(config_manager)
        
        # Run three-phase pipeline
        # Disable automatic cleanup - we'll handle it manually after DOCX generation
        artifacts = run_pipeline(
            input_path, 
            config_manager.config,
            alt_generator,
            force_regenerate=args.force_regenerate,
            cleanup_on_exit=False
        )
        
        pipeline_time = time.time() - start_time
        logger.info(f"Pipeline completed in {pipeline_time:.2f}s")
        
        # PPTX injection (unless review-doc-only)
        if not args.review_doc_only:
            inject_result = inject_from_map(
                output_path,
                str(artifacts.final_alt_map_path),
                mode=args.mode
            )
            
            if inject_result['success']:
                stats = inject_result.get('statistics', inject_result)
                print(f"✅ PPTX injection completed!")
                print(f"   Images updated: {stats.get('injected_successfully', 0)}")
                print(f"   Output: {output_path}")
            else:
                print(f"❌ PPTX injection failed: {inject_result.get('error', 'Unknown error')}")
                if not (args.review_doc or args.review_doc_only):
                    return 1
        
        # DOCX review document (if requested)
        review_doc_requested = args.review_doc or args.review_doc_only
        if review_doc_requested:
            # Determine output path for review document
            if args.review_out:
                review_output = args.review_out
            else:
                review_output = str(input_path.with_suffix('.docx'))
                if review_output == str(input_path):  # Avoid overwriting if same extension
                    review_output = str(input_path.with_suffix('.review.docx'))
            
            # Generate review document
            title = getattr(args, "title", None) or input_path.stem
            generate_alt_review_doc(
                str(artifacts.visual_index_path),
                str(artifacts.current_alt_by_key_path),
                str(artifacts.final_alt_map_path),
                review_output,
                portrait=True,
                title=title,
                config_manager=config_manager
            )
            
            print(f"📋 Review document generated: {review_output}")
        
        # Cleanup temporary artifacts (keep finals)
        # Preserve thumbnails if review doc was requested (they're needed for DOCX generation)
        artifacts.cleanup(keep_finals=True, preserve_thumbnails=review_doc_requested)
        
        total_time = time.time() - start_time
        print(f"⏱️ Total processing time: {total_time:.2f}s")
        return 0
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        print(f"❌ Processing failed: {e}")
        return 1


def cmd_inject(args) -> int:
    """Handle 'inject' command - inject from existing final_alt_map."""
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

    # Validate ALT map path
    try:
        validated_alt_map = sanitize_input_path(args.alt_map)
        alt_map_path = validated_alt_map
    except SecurityError as e:
        print(f"Security Error (ALT map): {e}")
        return 1
    except ValueError as e:
        print(f"Invalid ALT map path: {e}")
        return 1

    if not input_path.exists():
        print(f"❌ Input file not found: {args.input_file}")
        return 1

    if not alt_map_path.exists():
        print(f"❌ ALT map file not found: {args.alt_map}")
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
    
    logger.info(f"Injecting ALT text from {alt_map_path.name} into {input_path.name}")
    
    result = inject_from_map(output_path, str(alt_map_path), mode=args.mode)
    
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
    """Handle 'review' command - generate review document from artifacts."""
    # Validate and check all required files
    try:
        validated_visual_index = sanitize_input_path(args.visual_index)
        validated_current_alt = sanitize_input_path(args.current_alt)
        validated_final_alt = sanitize_input_path(args.final_alt)
    except SecurityError as e:
        print(f"Security Error: {e}")
        return 1
    except ValueError as e:
        print(f"Invalid path: {e}")
        return 1

    for path, path_name in [
        (validated_visual_index, 'visual index'),
        (validated_current_alt, 'current ALT'),
        (validated_final_alt, 'final ALT')
    ]:
        if not path.exists():
            print(f"❌ {path_name} file not found: {path}")
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
    
    logger.info(f"Generating review document from existing artifacts")

    # Load configuration for mode information
    from shared.config_manager import ConfigManager
    config_manager = ConfigManager(args.config)

    # Apply CLI mode override if provided
    if args.mode:
        config_manager.override_alt_mode(args.mode)

    try:
        generate_alt_review_doc(
            str(validated_visual_index),
            str(validated_current_alt),
            str(validated_final_alt),
            str(validated_output),
            portrait=True,
            title=args.title,
            config_manager=config_manager
        )
        
        print(f"✅ Review document generated: {args.output}")
        return 0
        
    except Exception as e:
        logger.error(f"Review document generation failed: {e}", exc_info=True)
        print(f"❌ Review generation failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())