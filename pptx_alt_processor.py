#!/usr/bin/env python3
"""
PPTX ALT Text Processor - Simple Integration Script
Combines all components for easy PPTX ALT text processing:
- Extract images from PPTX
- Generate medical-specific ALT text
- Inject ALT text back into PPTX 
- Optional PDF export and validation

This script demonstrates the complete integration of:
- ConfigManager and existing settings
- PPTXAccessibilityProcessor for generation
- PPTXAltTextInjector for robust injection
- PowerPoint automation for PDF export
"""

import logging
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Optional
import json

# Setup paths
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import path validation, file locking, and artifact management modules (must come after sys.path setup)
from shared.path_validator import sanitize_input_path, validate_output_path, SecurityError
from shared.file_lock_manager import FileLock, LockError
from shared.pipeline_artifacts import RunArtifacts

# Import system components
from config_manager import ConfigManager
from pptx_processor import PPTXAccessibilityProcessor
from pptx_alt_injector import PPTXAltTextInjector
from resource_manager import ResourceContext, validate_system_resources
from processing_exceptions import (
    ProcessingError, InsufficientMemoryError, InsufficientDiskSpaceError,
    PPTXParsingError, FileAccessError
)
from error_reporter import ProcessingResult, StandardizedLogger, handle_processing_exception
from recovery_strategies import SmartRecoveryManager, smart_recovery_context

# Set up enhanced logging (will be replaced by enhanced config if enabled)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Try to import enhanced logging config
try:
    from logging_config import setup_enhanced_logging, integrate_with_processor
    ENHANCED_LOGGING_AVAILABLE = True
except ImportError:
    ENHANCED_LOGGING_AVAILABLE = False

logger = logging.getLogger(__name__)


class PPTXAltProcessor:
    """
    Simple integration script that combines all PPTX ALT text components.
    Provides an easy-to-use interface for complete PPTX accessibility processing.
    """
    
    def __init__(self, config_path: Optional[str] = None, verbose: bool = False, debug: bool = False,
                 enable_file_logging: bool = True, fallback_policy_override: Optional[str] = None,
                 mode_override: Optional[str] = None, use_artifacts: bool = True):
        """
        Initialize the PPTX ALT text processor.

        Args:
            config_path: Optional path to configuration file
            verbose: Enable verbose logging
            debug: Enable detailed debug logging for generation attempts
            enable_file_logging: Enable enhanced file logging with rotation
            fallback_policy_override: Override fallback policy from CLI (none|doc-only|ppt-gated)
            use_artifacts: Enable artifact directory creation for intermediate files (default: True)
        """
        # Setup enhanced logging if available and requested
        self.log_config = None
        if enable_file_logging and ENHANCED_LOGGING_AVAILABLE:
            try:
                console_level = "DEBUG" if verbose else "INFO"
                self.log_config = setup_enhanced_logging(console_level=console_level)
                logger.info("Enhanced file logging enabled")
            except Exception as e:
                logger.warning(f"Failed to setup enhanced logging: {e}")
        elif verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Initialize core components
        self.config_manager = ConfigManager(config_path)
        
        # Apply CLI fallback policy override if provided
        if fallback_policy_override:
            logger.info(f"Overriding fallback policy to: {fallback_policy_override}")
            self.config_manager.config.setdefault('alt_text_handling', {})['fallback_policy'] = fallback_policy_override

        # Apply CLI mode override if provided
        if mode_override:
            self.config_manager.override_alt_mode(mode_override)
            logger.info(f"🛠️ ALT mode overridden to: {mode_override}")

        # Log the active fallback policy at startup
        active_policy = self.config_manager.get_fallback_policy()
        logger.info(f"🔧 Active fallback policy: {active_policy}")

        # Log the active ALT mode
        active_mode = self.config_manager.get_alt_mode()
        logger.info(f"🔧 Active ALT mode: {active_mode}")
        
        self.pptx_processor = PPTXAccessibilityProcessor(self.config_manager, debug=debug)
        self.alt_injector = PPTXAltTextInjector(self.config_manager)
        self.debug = debug
        
        # Integrate enhanced logging with processor if available
        if self.log_config:
            try:
                integrate_with_processor(self.pptx_processor, self.log_config)
                logger.info("Enhanced logging integrated with processor")
            except Exception as e:
                logger.warning(f"Failed to integrate enhanced logging: {e}")
        
        # Setup failed generation logging
        self.failed_generations = []

        # Store artifact management settings
        self.use_artifacts = use_artifacts
        self._current_artifacts = None  # Will hold RunArtifacts instance during processing

        logger.info("PPTX ALT Text Processor initialized")
        logger.info(f"Configuration: {self.config_manager.config_path or 'default'}")
        if debug:
            logger.info("🔍 DEBUG mode enabled - detailed generation logging active")
    
    def process_single_file(self, input_file: str, output_file: Optional[str] = None,
                          export_pdf: bool = False, generate_coverage_report: bool = True) -> dict:
        """
        Process a single PPTX file with complete ALT text workflow and smart error recovery.

        Args:
            input_file: Path to input PPTX file
            output_file: Optional output path (defaults to overwriting input)
            export_pdf: Whether to export to PDF after processing
            generate_coverage_report: Whether to generate detailed coverage report

        Returns:
            Dictionary with processing results
        """
        input_path = Path(input_file)
        if output_file is None:
            output_file = str(input_path)
        output_path = Path(output_file)

        # Create standardized result object
        result_obj = ProcessingResult("PPTX Processing", input_path, output_path)
        StandardizedLogger.log_processing_start("PPTX Processing", input_path, output_path)

        # Validate input file
        if not input_path.exists():
            error = FileAccessError(input_path, "read")
            result_obj.mark_failure(error)
            return result_obj.to_dict()

        # Pre-flight resource validation with structured errors
        validation_result = validate_system_resources(required_memory_mb=250, required_disk_mb=300)
        if not validation_result['sufficient']:
            if 'memory' in '; '.join(validation_result['errors']).lower():
                error = InsufficientMemoryError(250, 0)  # Approximate values
            else:
                error = InsufficientDiskSpaceError(300, 0, output_path.parent)
            result_obj.mark_failure(error)
            return result_obj.to_dict()

        # Get file locking configuration
        lock_config = self.config_manager.config.get("file_locking", {})
        locking_enabled = lock_config.get("enabled", True)
        lock_timeout = lock_config.get("timeout_seconds", 30)

        # Wrap processing with file locking to prevent concurrent access corruption
        try:
            if locking_enabled:
                lock = FileLock(input_path, timeout=lock_timeout)
                lock.acquire(blocking=True)
            else:
                lock = None
        except LockError as e:
            error_msg = f"File locked by another process (timeout after {lock_timeout}s)"
            logger.warning(f"File locked, cannot process: {input_path.name}")
            result_obj.mark_failure(error_msg)
            return result_obj.to_dict()

        # Determine if we should use artifacts
        artifact_config = self.config_manager.config.get('artifact_management', {})
        cleanup_on_exit = artifact_config.get('auto_cleanup', True)
        should_use_artifacts = self.use_artifacts

        # Use enhanced resource context with smart recovery
        recovery_manager = SmartRecoveryManager()

        # Wrap processing with RunArtifacts if enabled
        if should_use_artifacts:
            artifacts = RunArtifacts.create_for_run(input_path, cleanup_on_exit=cleanup_on_exit)
            artifacts.__enter__()
            self._current_artifacts = artifacts
        else:
            artifacts = None
            self._current_artifacts = None

        try:
            with smart_recovery_context(
                result_obj,
                recovery_manager,
                config=self.config_manager.config,
                required_memory_mb=250,
                required_disk_mb=300,
                llava_connectivity=getattr(self.pptx_processor, 'llava_connectivity', None)
            ) as (recovery_mgr, context):

                with ResourceContext(validate_resources=False, cleanup_on_exit=True) as (temp_manager, resource_monitor):
                    try:
                        # Clear previous failed generations
                        self.failed_generations = []

                        # Process with the existing processor
                        processor_result = self.pptx_processor.process_pptx(
                            str(input_path),
                            str(output_path),
                            failed_generation_callback=self._log_failed_generation,
                            debug=self.debug
                        )

                        # Convert processor result to standardized format
                        self._populate_result_from_processor(result_obj, processor_result)

                        if processor_result['success']:
                            # Generate and log coverage report
                            coverage_report = self._generate_coverage_report(processor_result)
                            result_obj.set_processing_details({'coverage_report': coverage_report})

                            # Set metrics
                            result_obj.set_metrics({
                                'total_images': processor_result.get('total_images', 0),
                                'processed_images': processor_result.get('processed_images', 0),
                                'coverage_percent': coverage_report.get('coverage_percent', 0),
                                'failed_generations': len(self.failed_generations)
                            })

                            # Log coverage statistics with new format
                            self._log_coverage_report(coverage_report)

                            # Generate coverage report file if requested
                            if generate_coverage_report:
                                self._save_coverage_report_file(coverage_report, input_path, output_path)

                            # Optional PDF export
                            if export_pdf:
                                pdf_result = self._export_to_pdf(output_path)
                                result_obj.processing_details['pdf_export'] = pdf_result
                                if not pdf_result['success']:
                                    result_obj.add_warning(f"PDF export failed: {pdf_result.get('error', 'Unknown error')}")

                            # Log session data if available
                            self._handle_session_logging(result_obj)

                            result_obj.mark_success()

                        else:
                            # Processing failed - add errors from processor result
                            for error_msg in processor_result.get('errors', []):
                                result_obj.add_error(error_msg)
                            result_obj.mark_failure()

                    except ProcessingError as e:
                        # Let smart recovery handle this
                        raise
                    except Exception as e:
                        # Convert to ProcessingError for recovery
                        if "parse" in str(e).lower() or "xml" in str(e).lower():
                            structured_error = PPTXParsingError(input_path, str(e))
                        else:
                            from processing_exceptions import wrap_exception
                            structured_error = wrap_exception(e, 'PPTX_PROCESSING_ERROR')
                        raise structured_error

        except ProcessingError as e:
            # Error was not recovered
            result_obj.mark_failure(e)
        except Exception as e:
            # Unexpected error that couldn't be converted
            result_obj.mark_failure(f"Unexpected error: {str(e)}")
        finally:
            # Mark success and cleanup artifacts if enabled
            if artifacts is not None:
                # Mark success if processing succeeded
                if result_obj.success:
                    artifacts.mark_success()
                # Exit artifact context (triggers cleanup)
                artifacts.__exit__(None, None, None)
                self._current_artifacts = None

            # Always release the lock
            if lock is not None:
                lock.release()

        # Log final result
        StandardizedLogger.log_processing_complete(result_obj)

        # Convert to legacy format for backward compatibility
        return self._convert_to_legacy_format(result_obj)
    
    def process_directory(self, input_dir: str, output_dir: Optional[str] = None,
                         pattern: str = "*.pptx", export_pdf: bool = False) -> dict:
        """
        Process all PPTX files in a directory.
        
        Args:
            input_dir: Directory containing PPTX files
            output_dir: Optional output directory
            pattern: File pattern to match (default: *.pptx)
            export_pdf: Whether to export processed files to PDF
            
        Returns:
            Dictionary with batch processing results
        """
        input_path = Path(input_dir)
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")
        
        if output_dir is None:
            output_path = input_path
        else:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

        # Pre-flight resource validation for batch processing
        validation_result = validate_system_resources(required_memory_mb=400, required_disk_mb=500)
        if not validation_result['sufficient']:
            error_msg = "Insufficient system resources for batch processing: " + "; ".join(validation_result['errors'])
            logger.error(error_msg)
            return {
                'success': False,
                'total_files': 0,
                'processed_files': 0,
                'failed_files': 0,
                'files': [],
                'errors': [error_msg]
            }

        # Find PPTX files
        pptx_files = list(input_path.glob(pattern))
        if not pptx_files:
            logger.warning(f"No PPTX files found matching pattern: {pattern}")
            return {
                'success': True,
                'total_files': 0,
                'processed_files': 0,
                'failed_files': 0,
                'files': []
            }
        
        logger.info(f"Found {len(pptx_files)} PPTX files to process")
        
        # Process each file
        results = {
            'success': True,
            'total_files': len(pptx_files),
            'processed_files': 0,
            'failed_files': 0,
            'total_processing_time': 0,
            'files': []
        }
        
        for pptx_file in pptx_files:
            try:
                # Determine output file path
                if output_dir:
                    output_file = output_path / pptx_file.name
                else:
                    output_file = pptx_file  # Overwrite original
                
                # Process file
                file_result = self.process_single_file(
                    str(pptx_file), 
                    str(output_file),
                    export_pdf
                )
                
                results['files'].append(file_result)
                results['total_processing_time'] += file_result.get('processing_time', 0)
                
                if file_result['success']:
                    results['processed_files'] += 1
                else:
                    results['failed_files'] += 1
                    results['success'] = False
                    
            except Exception as e:
                logger.error(f"Failed to process {pptx_file.name}: {e}")
                results['failed_files'] += 1
                results['success'] = False
                results['files'].append({
                    'success': False,
                    'input_file': str(pptx_file),
                    'errors': [str(e)]
                })
        
        # Log summary
        logger.info(f"Batch processing completed:")
        logger.info(f"   Total files: {results['total_files']}")
        logger.info(f"   Successfully processed: {results['processed_files']}")
        logger.info(f"   Failed: {results['failed_files']}")
        logger.info(f"   Total time: {results['total_processing_time']:.2f}s")
        
        # Generate batch coverage report
        batch_coverage = self._generate_batch_coverage_report(results)
        results['batch_coverage'] = batch_coverage
        logger.info("📊 Batch Coverage Summary:")
        logger.info(f"   Total images processed: {batch_coverage['total_images']}")
        logger.info(f"   Descriptive ALT text: {batch_coverage['descriptive_images']} ({batch_coverage['descriptive_coverage_percent']:.1f}%)")
        logger.info(f"   Decorative images: {batch_coverage['decorative_images'] + batch_coverage['fallback_decorative_images']} ({batch_coverage['decorative_coverage_percent']:.1f}%)")
        logger.info(f"   TOTAL COVERAGE: {batch_coverage['total_coverage_percent']:.1f}%")
        
        return results
    
    def extract_images_only(self, pptx_file: str, output_file: Optional[str] = None) -> dict:
        """
        Extract images and identifiers from PPTX without processing.
        Useful for manual ALT text workflows.
        
        Args:
            pptx_file: Path to PPTX file
            output_file: Optional JSON output file for extracted data
            
        Returns:
            Dictionary with extracted image information
        """
        pptx_path = Path(pptx_file)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_file}")
        
        logger.info(f"Extracting images from: {pptx_path.name}")
        
        try:
            # Extract images with identifiers
            extracted_images = self.alt_injector.extract_images_with_identifiers(str(pptx_path))
            
            # Convert to JSON-serializable format
            serializable_data = {}
            for key, info in extracted_images.items():
                serializable_data[key] = {
                    'image_key': info['image_key'],
                    'slide_idx': info['slide_idx'],
                    'shape_idx': info['shape_idx'],
                    'shape_name': info['shape_name'],
                    'existing_alt_text': info['existing_alt_text'],
                    'filename': info['filename']
                }
            
            # Save to file if requested
            if output_file:
                import json
                output_path = Path(output_file)
                with open(output_path, 'w') as f:
                    json.dump(serializable_data, f, indent=2)
                logger.info(f"Extracted data saved to: {output_path}")
            
            logger.info(f"✅ Successfully extracted {len(extracted_images)} images")
            
            return {
                'success': True,
                'pptx_file': str(pptx_path),
                'images_extracted': len(extracted_images),
                'extracted_data': serializable_data,
                'output_file': output_file
            }
            
        except Exception as e:
            error_msg = f"Image extraction failed: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'pptx_file': str(pptx_path),
                'error': error_msg
            }
    
    def inject_alt_text_from_file(self, pptx_file: str, alt_text_file: str, 
                                output_file: Optional[str] = None) -> dict:
        """
        Inject ALT text from a JSON file into PPTX.
        
        Args:
            pptx_file: Path to PPTX file
            alt_text_file: Path to JSON file with ALT text mappings
            output_file: Optional output file path
            
        Returns:
            Dictionary with injection results
        """
        pptx_path = Path(pptx_file)
        alt_text_path = Path(alt_text_file)
        
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_file}")
        if not alt_text_path.exists():
            raise FileNotFoundError(f"ALT text file not found: {alt_text_file}")
        
        if output_file is None:
            output_file = str(pptx_path)
        
        logger.info(f"Injecting ALT text into: {pptx_path.name}")
        logger.info(f"ALT text source: {alt_text_path.name}")
        
        try:
            # Load ALT text mappings
            import json
            with open(alt_text_path, 'r') as f:
                alt_text_mapping = json.load(f)
            
            # Inject ALT text using robust injector
            result = self.alt_injector.inject_alt_text_from_mapping(
                str(pptx_path),
                alt_text_mapping, 
                output_file
            )
            
            if result['success']:
                stats = result['statistics']
                logger.info(f"✅ ALT text injection completed:")
                logger.info(f"   Successfully injected: {stats['injected_successfully']}")
                logger.info(f"   Total images: {stats['total_images']}")
            else:
                logger.error("❌ ALT text injection failed")
                for error in result.get('errors', []):
                    logger.error(f"   - {error}")
            
            return result
            
        except Exception as e:
            error_msg = f"ALT text injection failed: {str(e)}"
            logger.error(error_msg)
            return {
                'success': False,
                'pptx_file': str(pptx_path),
                'alt_text_file': str(alt_text_path),
                'error': error_msg
            }
    
    def test_pdf_export_survival(self, pptx_file: str) -> dict:
        """
        Test ALT text survival in PDF export.
        
        Args:
            pptx_file: Path to PPTX file with ALT text
            
        Returns:
            Dictionary with survival test results
        """
        pptx_path = Path(pptx_file)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_file}")
        
        logger.info(f"Testing ALT text survival for: {pptx_path.name}")
        
        return self.alt_injector.test_pdf_export_alt_text_survival(str(pptx_path))
    
    def _test_new_pipeline_dry_run(self, pptx_file: str, 
                                  llava_include_shapes: str = "smart",
                                  max_shapes_per_slide: int = 5,
                                  min_shape_area: str = "1%") -> dict:
        """
        Test the new pipeline implementation without modifying files.
        
        Args:
            pptx_file: Path to PPTX file to test
            llava_include_shapes: Shape inclusion strategy 
            max_shapes_per_slide: Max shapes per slide
            min_shape_area: Minimum shape area threshold
            
        Returns:
            Dictionary with test results
        """
        pptx_path = Path(pptx_file)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_file}")
        
        logger.info(f"Testing new pipeline with: {pptx_path.name}")

        try:
            from shared.manifest_processor import ManifestProcessor
            from shared.alt_manifest import AltManifest, MANIFEST_SCHEMA_VERSION
            from shared.pipeline_artifacts import RunArtifacts
            import time

            start_time = time.time()

            # Create test artifacts with automatic cleanup
            # For dry-run, we always cleanup after
            with RunArtifacts.create_for_run(pptx_path, cleanup_on_exit=True) as artifacts:
                # Initialize processor with new configuration
                processor = ManifestProcessor(
                    config_manager=self.config_manager,
                    alt_generator=None,  # Skip generation for dry run
                    llava_include_shapes=llava_include_shapes,
                    max_shapes_per_slide=max_shapes_per_slide,
                    min_shape_area=min_shape_area
                )

                # Initialize manifest
                manifest = AltManifest(artifacts.get_manifest_path())

                # Phase 1: Discovery and Classification
                logger.info("Running Phase 1: Discovery and Classification")
                phase1_result = processor.phase1_discover_and_classify(pptx_path, manifest)

                if not phase1_result['success']:
                    return {
                        'success': False,
                        'phase': 'discovery',
                        'error': phase1_result.get('error', 'Unknown error'),
                        'errors': [phase1_result.get('error', 'Unknown error')]
                    }

                # Phase 2: Rendering and Crops (for testing, we'll simulate this)
                logger.info("Running Phase 2: Rendering and Thumbnails (simulated for dry-run)")
                # In a real run, this would call processor.phase2_render_and_generate_crops
                # For dry-run, we'll simulate by setting placeholder paths
                for entry in manifest.get_all_entries():
                    entry.crop_path = f"crops/{entry.instance_key}.png"  # Placeholder
                    entry.thumb_path = f"thumbs/{entry.instance_key}.jpg"  # Placeholder
                    manifest.add_entry(entry)

                # Phase 3: Inclusion Policy and Caching
                logger.info("Running Phase 3: Inclusion Policy and Caching")
                phase3_result = processor.phase3_inclusion_policy_and_caching(manifest, mode="preserve")

                if not phase3_result['success']:
                    return {
                        'success': False,
                        'phase': 'inclusion_policy',
                        'error': phase3_result.get('error', 'Unknown error'),
                        'errors': [phase3_result.get('error', 'Unknown error')]
                    }

                # Phase 4: LLaVA Generation (skipped for dry-run unless explicitly requested)
                logger.info("Phase 4: LLaVA Generation (skipped for dry-run)")
                phase4_result = {
                    'success': True,
                    'generated_count': 0,
                    'skipped_count': phase3_result.get('needs_generation_count', 0),
                    'message': 'Skipped for dry-run mode'
                }

                # Save manifest after all phases
                manifest.save()

                processing_time = time.time() - start_time

                # Get manifest statistics
                stats = manifest.get_statistics()

                result = {
                    'success': True,
                    'schema_version': MANIFEST_SCHEMA_VERSION,
                    'pptx_file': str(pptx_path),
                    'manifest_path': str(artifacts.get_manifest_path()),
                    'processing_time': processing_time,
                    # Phase 1 results
                    'discovered_elements': phase1_result['discovered_elements'],
                    'classified_elements': phase1_result['classified_elements'],
                    'include_strategy': phase1_result['include_strategy'],
                    'min_area_threshold': phase1_result['min_area_threshold'],
                    # Phase 3 results
                    'preserved_count': phase3_result['preserved_count'],
                    'cached_count': phase3_result['cached_count'],
                    'needs_generation_count': phase3_result['needs_generation_count'],
                    'excluded_count': phase3_result['excluded_count'],
                    # Phase 4 results
                    'generated_count': phase4_result['generated_count'],
                    # Manifest statistics
                    'manifest_stats': stats,
                    'total_entries': stats['total_entries'],
                    'with_existing_alt': stats['with_current_alt']
                }

                logger.info(f"✅ Dry run completed successfully in {processing_time:.2f}s")
                logger.info(f"   Schema version: {MANIFEST_SCHEMA_VERSION}")
                logger.info(f"   Elements discovered: {phase1_result['discovered_elements']}")
                logger.info(f"   Elements classified: {phase1_result['classified_elements']}")
                logger.info(f"   Strategy: {phase1_result['include_strategy']}")
                logger.info(f"   Threshold: {phase1_result['min_area_threshold']:.0f} sq pts")
                logger.info(f"   With existing ALT: {stats['with_current_alt']}")
                logger.info(f"   Manifest: {artifacts.get_manifest_path()}")

                return result
            # Context manager automatically cleans up here
            
        except Exception as e:
            error_msg = f"Dry run failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'pptx_file': str(pptx_path),
                'processing_time': time.time() - start_time,
                'error': error_msg,
                'errors': [error_msg]
            }
    
    def _export_to_pdf(self, pptx_file: Path) -> dict:
        """
        Export PPTX to PDF with multiple fallback methods.
        
        Args:
            pptx_file: Path to PPTX file
            
        Returns:
            Dictionary with export results
        """
        pdf_path = pptx_file.with_suffix('.pdf')
        
        # Try LibreOffice first (cross-platform)
        try:
            import subprocess
            
            cmd = [
                "libreoffice",
                "--headless", 
                "--convert-to", "pdf",
                "--outdir", str(pptx_file.parent),
                str(pptx_file)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0 and pdf_path.exists():
                return {
                    'success': True,
                    'pdf_file': str(pdf_path),
                    'method': 'LibreOffice'
                }
            else:
                logger.warning(f"LibreOffice export failed: {result.stderr}")
                
        except FileNotFoundError:
            logger.debug("LibreOffice not found, trying platform-specific methods")
        except Exception as e:
            logger.warning(f"LibreOffice export error: {e}")
        
        # Try platform-specific methods
        import platform
        
        if platform.system() == "Darwin":
            # macOS - try AppleScript
            try:
                applescript = f'''
                tell application "Microsoft PowerPoint"
                    open POSIX file "{pptx_file.absolute()}"
                    save active presentation in POSIX file "{pdf_path.absolute()}" as save as PDF
                    close active presentation
                end tell
                '''
                
                result = subprocess.run(
                    ["osascript", "-e", applescript],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0 and pdf_path.exists():
                    return {
                        'success': True,
                        'pdf_file': str(pdf_path),
                        'method': 'macOS AppleScript'
                    }
                else:
                    logger.warning(f"AppleScript export failed: {result.stderr}")
                    
            except Exception as e:
                logger.warning(f"AppleScript export error: {e}")
        
        elif platform.system() == "Windows":
            # Windows - try COM automation
            try:
                import win32com.client
                
                ppt = win32com.client.Dispatch("PowerPoint.Application")
                ppt.Visible = 1
                
                presentation = ppt.Presentations.Open(str(pptx_file.absolute()))
                presentation.SaveAs(str(pdf_path.absolute()), 32)  # ppSaveAsPDF = 32
                
                presentation.Close()
                ppt.Quit()
                
                if pdf_path.exists():
                    return {
                        'success': True,
                        'pdf_file': str(pdf_path),
                        'method': 'Windows COM'
                    }
                    
            except Exception as e:
                logger.warning(f"Windows COM export error: {e}")
        
        # All methods failed
        return {
            'success': False,
            'error': 'No PDF export method available. Install LibreOffice, or ensure PowerPoint is available.',
            'method': 'none'
        }
    
    def _log_failed_generation(self, image_key: str, image_info: dict, error: str):
        """
        Log a failed generation attempt for manual review.
        
        Args:
            image_key: Unique identifier for the image
            image_info: Image information dictionary
            error: Error message or reason for failure
        """
        failed_entry = {
            'image_key': image_key,
            'slide_idx': image_info.get('slide_idx', 'unknown'),
            'shape_idx': image_info.get('shape_idx', 'unknown'),
            'filename': image_info.get('filename', 'unknown'),
            'dimensions': f"{image_info.get('width_px', '?')}x{image_info.get('height_px', '?')}",
            'error': error,
            'slide_text': image_info.get('slide_text', '')[:100]  # First 100 chars
        }
        self.failed_generations.append(failed_entry)
        
        logger.warning(f"Failed generation logged: {image_key} - {error}")
    
    def _generate_coverage_report(self, result: dict) -> dict:
        """
        Generate accurate coverage report using injector statistics as canonical source.

        Args:
            result: Processing result dictionary with injector_statistics

        Returns:
            Coverage report dictionary with accurate metrics that match reality
        """
        # Use injector statistics as the canonical source of truth
        injector_stats = result.get('injector_statistics', {})

        if injector_stats:
            # Get accurate counts from injector (what actually happened)
            total_images = injector_stats.get('total_images', 0)
            preserved = injector_stats.get('skipped_existing', 0)
            generated = injector_stats.get('injected_successfully', 0)
            failed_injection = injector_stats.get('failed_injection', 0)
            skipped_invalid = injector_stats.get('skipped_invalid', 0)

            # Calculate coverage based on actual injection results
            successfully_processed = preserved + generated
            coverage_percent = (successfully_processed / total_images * 100) if total_images > 0 else 0

            # Map to new structure with clear categories
            needs_alt = failed_injection + skipped_invalid  # Images that need manual attention
            decorative_skipped = 0  # This would come from preprocessing, not injector
            fallback_injected = 0   # Not tracked separately in current injector
            covered = successfully_processed

        else:
            # Fallback to legacy structure if injector stats not available
            total_images = result.get('total_images', 0)
            processed_images = result.get('processed_images', 0)
            decorative_images = result.get('decorative_images', 0)
            failed_images = result.get('failed_images', 0)
            fallback_decorative = result.get('fallback_decorative', 0)

            # Map legacy to new structure with best approximation
            preserved = 0  # Cannot distinguish from legacy data
            generated = processed_images
            decorative_skipped = decorative_images + fallback_decorative
            needs_alt = failed_images
            fallback_injected = 0
            total = total_images
            covered = generated
            coverage_percent = (covered / total * 100) if total > 0 else 0
        
        # Build accurate coverage report
        total = total_images  # Use actual count, not calculated sum

        return {
            # Canonical metrics - what actually happened
            'total_elements': total,
            'preserved': preserved,
            'generated': generated,
            'needs_alt': needs_alt,
            'fallback_injected': fallback_injected,
            'decorative_skipped': decorative_skipped,
            'covered_elements': covered,
            'coverage_percent': coverage_percent,
            'failed_generations_count': len(getattr(self, 'failed_generations', [])),

            # Legacy fields for compatibility - but use accurate numbers
            'total_images': total,
            'descriptive_images': generated,
            'decorative_images': decorative_skipped,
            'failed_images': needs_alt,
            'descriptive_coverage_percent': (generated / total * 100) if total > 0 else 0,
            'decorative_coverage_percent': (decorative_skipped / total * 100) if total > 0 else 0,
            'total_coverage_percent': coverage_percent
        }
    
    def _log_coverage_report(self, coverage_report: dict):
        """
        Log the accurate coverage report with clear, non-confusing metrics.

        Args:
            coverage_report: Coverage report dictionary
        """
        total = coverage_report['total_elements']
        covered = coverage_report['covered_elements']
        preserved = coverage_report['preserved']
        generated = coverage_report['generated']
        needs_alt = coverage_report['needs_alt']
        decorative = coverage_report['decorative_skipped']

        logger.info("📊 ALT Text Processing Report:")
        logger.info(f"   Total images found: {total}")

        if total > 0:
            logger.info(f"   Successfully processed: {covered} ({coverage_report['coverage_percent']:.1f}%)")

            if preserved > 0:
                logger.info(f"     - Preserved existing ALT text: {preserved}")
            if generated > 0:
                logger.info(f"     - Generated new ALT text: {generated}")
            if decorative > 0:
                logger.info(f"     - Decorative (no ALT needed): {decorative}")
            if needs_alt > 0:
                logger.warning(f"   ⚠️  Need manual attention: {needs_alt}")

            # Show overall success clearly
            if needs_alt == 0:
                logger.info(f"   ✅ All images have appropriate ALT text!")
            else:
                completion_rate = ((total - needs_alt) / total * 100)
                logger.info(f"   📈 Completion rate: {completion_rate:.1f}% ({total - needs_alt}/{total})")

        if coverage_report['failed_generations_count'] > 0:
            logger.warning(f"   🔍 Failed generation attempts: {coverage_report['failed_generations_count']} (see coverage report file)")
    
    def _save_coverage_report_file(self, coverage_report: dict, input_path: Path, output_path: Path):
        """
        Save detailed coverage report to JSON file.
        
        Args:
            coverage_report: Coverage report dictionary
            input_path: Input file path
            output_path: Output file path
        """
        try:
            # Create detailed report
            detailed_report = {
                'input_file': str(input_path),
                'output_file': str(output_path),
                'processing_timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'coverage_summary': coverage_report,
                'failed_generations': self.failed_generations
            }
            
            # Save to file
            report_path = output_path.parent / f"{output_path.stem}_coverage_report.json"
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(detailed_report, f, indent=2, ensure_ascii=False)
            
            logger.info(f"📋 Coverage report saved: {report_path}")
            
        except Exception as e:
            logger.warning(f"Failed to save coverage report: {e}")
    
    def _generate_batch_coverage_report(self, batch_results: dict) -> dict:
        """
        Generate coverage report for batch processing.
        
        Args:
            batch_results: Batch processing results
            
        Returns:
            Batch coverage report
        """
        total_images = 0
        total_descriptive = 0
        total_decorative = 0
        total_fallback_decorative = 0
        total_failed = 0
        total_failed_generations = 0
        
        for file_result in batch_results.get('files', []):
            if 'coverage_report' in file_result:
                report = file_result['coverage_report']
                total_images += report['total_images']
                total_descriptive += report['descriptive_images']
                total_decorative += report['decorative_images']
                total_fallback_decorative += report['fallback_decorative_images']
                total_failed += report['failed_images']
                total_failed_generations += report['failed_generations_count']
        
        # Calculate batch percentages
        descriptive_pct = (total_descriptive / total_images * 100) if total_images > 0 else 0
        decorative_pct = ((total_decorative + total_fallback_decorative) / total_images * 100) if total_images > 0 else 0
        total_coverage_pct = ((total_descriptive + total_decorative + total_fallback_decorative) / total_images * 100) if total_images > 0 else 0
        
        return {
            'total_files': batch_results.get('total_files', 0),
            'total_images': total_images,
            'descriptive_images': total_descriptive,
            'decorative_images': total_decorative,
            'fallback_decorative_images': total_fallback_decorative,
            'failed_images': total_failed,
            'descriptive_coverage_percent': descriptive_pct,
            'decorative_coverage_percent': decorative_pct,
            'total_coverage_percent': total_coverage_pct,
            'total_failed_generations': total_failed_generations
        }
    
    def _log_failed_generations_summary(self):
        """Log summary of failed generations for manual review."""
        if not self.failed_generations:
            return
        
        logger.warning(f"🚨 {len(self.failed_generations)} failed ALT text generations require manual review:")
        for failed in self.failed_generations:
            logger.warning(f"   - {failed['image_key']} (slide {failed['slide_idx']}, {failed['dimensions']}): {failed['error']}")
            if failed['slide_text']:
                logger.warning(f"     Context: {failed['slide_text'][:50]}...")
        
        logger.warning("   See coverage report file for complete details.")

    def _populate_result_from_processor(self, result_obj: ProcessingResult, processor_result: dict):
        """
        Populate standardized result object from processor output.

        Args:
            result_obj: StandardizedResult to populate
            processor_result: Output from pptx_processor
        """
        # Get accurate counts from injector statistics (canonical source)
        injector_stats = processor_result.get('injector_statistics', {})
        if injector_stats:
            processed_images = (
                injector_stats.get('injected_successfully', 0) +
                injector_stats.get('skipped_existing', 0)
            )
            total_images = injector_stats.get('total_images', 0)
        else:
            # Fallback to processor counts if injector stats not available
            processed_images = processor_result.get('processed_visual_elements', 0)
            total_images = processor_result.get('total_visual_elements', 0)

        # Update processor result with accurate counts
        processor_result['processed_images'] = processed_images
        processor_result['total_images'] = total_images

    def _handle_session_logging(self, result_obj: ProcessingResult):
        """
        Handle enhanced session logging if available.

        Args:
            result_obj: Result object to update with session info
        """
        if not self.log_config:
            return

        try:
            # Update processing stats
            self.log_config.update_processing_stats({
                'processing_time': result_obj.processing_time,
                'input_file': result_obj.input_file,
                'output_file': result_obj.output_file,
                'success': result_obj.success
            })

            # Export logs and data
            self.log_config.export_session_data()

            # Get and log session summary
            summary = self.log_config.get_session_summary()
            session_details = {
                'session_id': self.log_config.session_id,
                'total_alt_texts': summary['total_alt_texts'],
                'total_failures': summary['total_failures'],
                'success_rate': summary['success_rate']
            }
            result_obj.set_processing_details({'session_summary': session_details})

            logger.info(f"📊 Session Summary:")
            logger.info(f"   ALT texts generated: {summary['total_alt_texts']}")
            logger.info(f"   Failed generations: {summary['total_failures']}")
            logger.info(f"   Success rate: {summary['success_rate']:.1f}%")
            logger.info(f"   Session logs saved to: logs/{self.log_config.session_id}*")

        except Exception as e:
            result_obj.add_warning(f"Failed to export session data: {e}")

    def _convert_to_legacy_format(self, result_obj: ProcessingResult) -> dict:
        """
        Convert standardized result back to legacy format for backward compatibility.

        Args:
            result_obj: StandardizedResult object

        Returns:
            Dictionary in legacy format
        """
        legacy_result = {
            'success': result_obj.success,
            'input_file': result_obj.input_file,
            'output_file': result_obj.output_file,
            'processing_time': result_obj.processing_time or 0,
        }

        # Add metrics
        if result_obj.metrics:
            legacy_result.update(result_obj.metrics)

        # Add processing details
        if result_obj.processing_details:
            legacy_result.update(result_obj.processing_details)

        # Convert errors to legacy format
        if result_obj.errors:
            legacy_result['errors'] = [
                error.get('message', str(error)) for error in result_obj.errors
            ]
        else:
            legacy_result['errors'] = []

        # Add failed generations if available
        if self.failed_generations:
            legacy_result['failed_generations'] = self.failed_generations

        return legacy_result


def main():
    """Command-line interface for PPTX ALT text processing."""
    parser = argparse.ArgumentParser(
        description='PPTX ALT Text Processor - Complete workflow integration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single file with ALT text generation
  python pptx_alt_processor.py process presentation.pptx
  
  # Process with PDF export
  python pptx_alt_processor.py process presentation.pptx --export-pdf
  
  # Process directory of PPTX files
  python pptx_alt_processor.py batch-process slides_folder/
  
  # Extract images only (for manual workflow)
  python pptx_alt_processor.py extract presentation.pptx --output images.json
  
  # Inject ALT text from JSON file
  python pptx_alt_processor.py inject presentation.pptx --alt-text-file mappings.json
  
  # Test ALT text survival
  python pptx_alt_processor.py test-survival presentation.pptx
        """
    )
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Processing commands')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process single PPTX file')
    process_parser.add_argument('input_file', help='Input PPTX file')
    process_parser.add_argument('-o', '--output', help='Output PPTX file')
    process_parser.add_argument('--export-pdf', action='store_true', help='Export to PDF after processing')
    process_parser.add_argument('--generate-approval-documents', action='store_true', help='Generate Word review document in addition to normal PPT injection')
    process_parser.add_argument('--approval-doc-only', action='store_true', help='Generate only the review document; skip injection')
    process_parser.add_argument('--approval-out', help='Specific path for approval document output')
    
    # LLaVA shape processing flags
    process_parser.add_argument('--llava-include-shapes', choices=['off', 'smart', 'all'], default='smart',
                               help='Shape inclusion strategy: off=pictures only, smart=shapes above threshold, all=all shapes (default: smart)')
    process_parser.add_argument('--max-shapes-per-slide', type=int, default=5,
                               help='Maximum shapes to process per slide (default: 5)')
    process_parser.add_argument('--min-shape-area', default='1%', 
                               help='Minimum shape area threshold, as percentage (e.g., "1%") or pixels (e.g., "100px") (default: 1%%)')
    
    # Pipeline control flags  
    process_parser.add_argument('--skip-injection', action='store_true', 
                               help='Skip ALT text injection (generate only)')
    process_parser.add_argument('--dry-run', action='store_true',
                               help='Dry run mode - process and generate manifest but do not modify files')
    
    # Batch process command
    batch_parser = subparsers.add_parser('batch-process', help='Process directory of PPTX files')
    batch_parser.add_argument('input_dir', help='Input directory')
    batch_parser.add_argument('-o', '--output-dir', help='Output directory')
    batch_parser.add_argument('--pattern', default='*.pptx', help='File pattern (default: *.pptx)')
    batch_parser.add_argument('--export-pdf', action='store_true', help='Export to PDF after processing')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract images without processing')
    extract_parser.add_argument('input_file', help='Input PPTX file')
    extract_parser.add_argument('-o', '--output', help='Output JSON file')
    
    # Inject command
    inject_parser = subparsers.add_parser('inject', help='Inject ALT text from JSON file')
    inject_parser.add_argument('input_file', help='Input PPTX file')
    inject_parser.add_argument('--alt-text-file', required=True, help='JSON file with ALT text mappings')
    inject_parser.add_argument('-o', '--output', help='Output PPTX file')
    
    # Test survival command
    survival_parser = subparsers.add_parser('test-survival', help='Test ALT text survival')
    survival_parser.add_argument('input_file', help='Input PPTX file with ALT text')
    
    # Global options
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--debug', action='store_true', help='Enable detailed debug logging for generation attempts and failures')
    parser.add_argument('--fallback-policy', choices=['none', 'doc-only', 'ppt-gated'],
                       help='Override fallback policy for this run (none|doc-only|ppt-gated)')
    parser.add_argument('--mode', choices=['preserve', 'replace'],
                       help='Whether to preserve or replace existing ALT text in PPTX (overrides config)')
    parser.add_argument('--no-artifacts', action='store_true',
                       help='Disable artifact directory creation (no intermediate files saved)')

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        # Validate config path if provided
        config_path = args.config
        if config_path:
            try:
                validated_config = sanitize_input_path(config_path)
                config_path = str(validated_config)
            except SecurityError as e:
                print(f"Security Error (config): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid config path: {e}")
                return 1

        # Initialize processor
        processor = PPTXAltProcessor(
            config_path,
            args.verbose,
            args.debug,
            fallback_policy_override=args.fallback_policy,
            mode_override=args.mode,
            use_artifacts=not args.no_artifacts
        )

        if args.command == 'process':
            # Validate input file path (allow absolute paths for batch processing)
            try:
                validated_input = sanitize_input_path(args.input_file, allow_absolute=True)
                input_pptx = str(validated_input)
            except SecurityError as e:
                print(f"Security Error (input): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid input path: {e}")
                return 1

            # Validate output path if provided
            output_path = None
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
            
            # Handle new flags
            dry_run = getattr(args, 'dry_run', False)
            skip_injection = getattr(args, 'skip_injection', False)
            llava_include_shapes = getattr(args, 'llava_include_shapes', 'smart')
            max_shapes_per_slide = getattr(args, 'max_shapes_per_slide', 5)
            min_shape_area = getattr(args, 'min_shape_area', '1%')
            
            if dry_run:
                logger.info("🔍 DRY RUN MODE: Processing manifest but not modifying files")
            
            # 1) Dry-run mode: test new pipeline without modifications
            if dry_run:
                result = processor._test_new_pipeline_dry_run(
                    input_pptx,
                    llava_include_shapes=llava_include_shapes,
                    max_shapes_per_slide=max_shapes_per_slide,
                    min_shape_area=min_shape_area
                )
                
                if result['success']:
                    print("✅ Dry run completed successfully!")
                    print(f"Schema version: {result.get('schema_version', 'N/A')}")
                    print(f"Elements discovered: {result.get('discovered_elements', 0)}")
                    print(f"Elements classified: {result.get('classified_elements', 0)}")
                    print(f"Include strategy: {result.get('include_strategy', 'N/A')}")
                    print(f"Min area threshold: {result.get('min_area_threshold', 0):.0f} sq pts")
                    print()
                    print("Policy decisions:")
                    print(f"  Preserved (existing ALT): {result.get('preserved_count', 0)}")
                    print(f"  Cached (reused): {result.get('cached_count', 0)}")
                    print(f"  Need generation: {result.get('needs_generation_count', 0)}")
                    print(f"  Excluded: {result.get('excluded_count', 0)}")
                    print(f"  Generated (dry-run): {result.get('generated_count', 0)}")
                    print()
                    print(f"Manifest saved to: {result.get('manifest_path', 'N/A')}")
                else:
                    print("❌ Dry run failed!")
                    for error in result.get('errors', []):
                        print(f"Error: {error}")
                    return 1
                    
            # 2) Normal injection (skip if --approval-doc-only or --dry-run)
            elif not args.approval_doc_only:
                result = processor.process_single_file(
                    input_pptx, 
                    output_path, 
                    args.export_pdf
                )
                
                if result['success']:
                    print("✅ Processing completed successfully!")
                    print(f"Images processed: {result['processed_images']}")
                    print(f"Time: {result['processing_time']:.2f}s")
                    if 'pdf_export' in result:
                        pdf_result = result['pdf_export']
                        if pdf_result['success']:
                            print(f"PDF exported: {pdf_result['pdf_file']}")
                else:
                    print("❌ Processing failed!")
                    for error in result.get('errors', []):
                        print(f"Error: {error}")
                    if not (args.generate_approval_documents or args.approval_doc_only):
                        return 1
            
            # 2) Approvals doc (if requested)
            if args.generate_approval_documents or args.approval_doc_only:
                try:
                    from approval.approval_pipeline import make_review_doc, ApprovalOptions
                    
                    out_dir = output_path or processor.config_manager.config.get('paths', {}).get('output_folder', '.')
                    if output_path and Path(output_path).is_file():
                        out_dir = str(Path(output_path).parent)
                    
                    opts = ApprovalOptions.from_config(processor.config_manager)
                    
                    # Get final_alt_map from processing result if available
                    final_alt_map = None
                    if not args.approval_doc_only and 'result' in locals() and result.get('final_alt_map'):
                        final_alt_map = result['final_alt_map']
                    
                    # Use the output PPTX (post-injection) for review doc generation
                    pptx_for_review = output_path if output_path and not args.approval_doc_only else input_pptx
                    
                    review_path = make_review_doc(
                        pptx_for_review,
                        out_dir,
                        processor.config_manager,
                        opts,
                        final_alt_map,
                    )
                    
                    if args.approval_out and args.approval_out != review_path:
                        import shutil
                        shutil.move(review_path, args.approval_out)
                        review_path = args.approval_out
                    
                    print(f"📋 Approval document generated: {review_path}")
                    
                except Exception as e:
                    print(f"❌ Approval document generation failed: {e}")
                    if args.approval_doc_only:
                        return 1
                
        elif args.command == 'batch-process':
            # Validate input directory (allow absolute paths)
            try:
                validated_input_dir = sanitize_input_path(args.input_dir, allow_absolute=True)
                input_dir = str(validated_input_dir)
            except SecurityError as e:
                print(f"Security Error (input directory): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid input directory: {e}")
                return 1

            # Validate output directory if provided
            output_dir = None
            if args.output_dir:
                try:
                    validated_output_dir = validate_output_path(args.output_dir)
                    output_dir = str(validated_output_dir)
                except SecurityError as e:
                    print(f"Security Error (output directory): {e}")
                    return 1
                except ValueError as e:
                    print(f"Invalid output directory: {e}")
                    return 1

            result = processor.process_directory(
                input_dir,
                output_dir,
                args.pattern,
                args.export_pdf
            )
            
            print(f"Batch processing completed:")
            print(f"  Total files: {result['total_files']}")
            print(f"  Successfully processed: {result['processed_files']}")
            print(f"  Failed: {result['failed_files']}")
            print(f"  Total time: {result['total_processing_time']:.2f}s")
            
            if not result['success']:
                return 1
                
        elif args.command == 'extract':
            # Validate input file (allow absolute paths for batch processing)
            try:
                validated_input = sanitize_input_path(args.input_file, allow_absolute=True)
                input_file = str(validated_input)
            except SecurityError as e:
                print(f"Security Error (input): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid input path: {e}")
                return 1

            # Validate output file if provided
            output_file = None
            if args.output:
                try:
                    validated_output = validate_output_path(args.output)
                    output_file = str(validated_output)
                except SecurityError as e:
                    print(f"Security Error (output): {e}")
                    return 1
                except ValueError as e:
                    print(f"Invalid output path: {e}")
                    return 1

            result = processor.extract_images_only(input_file, output_file)
            
            if result['success']:
                print(f"✅ Extracted {result['images_extracted']} images")
                if result['output_file']:
                    print(f"Data saved to: {result['output_file']}")
            else:
                print(f"❌ Extraction failed: {result['error']}")
                return 1
                
        elif args.command == 'inject':
            # Validate input file (allow absolute paths for batch processing)
            try:
                validated_input = sanitize_input_path(args.input_file, allow_absolute=True)
                input_file = str(validated_input)
            except SecurityError as e:
                print(f"Security Error (input): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid input path: {e}")
                return 1

            # Validate alt text file (allow absolute paths for batch processing)
            try:
                validated_alt_text = sanitize_input_path(args.alt_text_file, allow_absolute=True)
                alt_text_file = str(validated_alt_text)
            except SecurityError as e:
                print(f"Security Error (alt text file): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid alt text file path: {e}")
                return 1

            # Validate output file if provided
            output_file = None
            if args.output:
                try:
                    validated_output = validate_output_path(args.output)
                    output_file = str(validated_output)
                except SecurityError as e:
                    print(f"Security Error (output): {e}")
                    return 1
                except ValueError as e:
                    print(f"Invalid output path: {e}")
                    return 1

            result = processor.inject_alt_text_from_file(
                input_file,
                alt_text_file,
                output_file
            )
            
            if result['success']:
                stats = result['statistics']
                print("✅ ALT text injection completed!")
                print(f"Successfully injected: {stats['injected_successfully']}")
                print(f"Total images: {stats['total_images']}")
            else:
                print(f"❌ Injection failed: {result['error']}")
                return 1
                
        elif args.command == 'test-survival':
            # Validate input file (allow absolute paths for batch processing)
            try:
                validated_input = sanitize_input_path(args.input_file, allow_absolute=True)
                input_file = str(validated_input)
            except SecurityError as e:
                print(f"Security Error (input): {e}")
                return 1
            except ValueError as e:
                print(f"Invalid input path: {e}")
                return 1

            result = processor.test_pdf_export_survival(input_file)
            
            if result['success']:
                print("✅ ALT text survival test completed:")
                print(f"Total images: {result['total_images']}")
                print(f"Images with ALT text: {result['images_with_alt_text']}")
                print(f"Coverage: {result['alt_text_coverage']:.1%}")
            else:
                print(f"❌ Survival test failed")
                for error in result.get('errors', []):
                    print(f"Error: {error}")
                return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        print(f"💥 Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
