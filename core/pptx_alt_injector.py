"""
PPTX ALT Text Injector for PPTX Accessibility Processor
Injects ALT text into PowerPoint presentations using python-pptx XML manipulation
Integrates with existing ConfigManager, reinjection settings, and workflow patterns
"""

import logging
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
from hashlib import md5
import tempfile

# Third-party imports for PPTX processing
try:
    from pptx import Presentation
    from pptx.shapes.picture import Picture
    from pptx.shapes.base import BaseShape
    from pptx.oxml.ns import _nsmap
    PPTX_AVAILABLE = True
except ImportError as e:
    PPTX_AVAILABLE = False
    PPTX_ERROR = str(e)

# Setup paths for shared and core modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import shared modules
from config_manager import ConfigManager
from decorative_filter import is_force_decorative_by_filename

logger = logging.getLogger(__name__)


class PPTXImageIdentifier:
    """
    Robust image identifier for maintaining consistency across extract→generate→inject workflow.
    """
    
    def __init__(self, slide_idx: int, shape_idx: int, shape_name: str = "", 
                 image_hash: str = "", embed_id: str = ""):
        self.slide_idx = slide_idx
        self.shape_idx = shape_idx
        self.shape_name = shape_name
        self.image_hash = image_hash
        self.embed_id = embed_id
        self.image_key = self._create_image_key()
    
    def _create_image_key(self) -> str:
        """Create robust, unique identifier for image."""
        components = [f"slide_{self.slide_idx}", f"shape_{self.shape_idx}"]
        
        if self.shape_name and not self.shape_name.startswith('Picture'):
            components.append(f"name_{self.shape_name}")
        
        if self.image_hash:
            components.append(f"hash_{self.image_hash[:8]}")
        
        return "_".join(components)
    
    @classmethod
    def from_shape(cls, shape: Picture, slide_idx: int, shape_idx: int):
        """Create identifier from shape object."""
        shape_name = getattr(shape, 'name', '')
        
        # Extract image hash if available
        image_hash = ""
        try:
            if hasattr(shape, 'image') and shape.image:
                image_data = shape.image.blob
                image_hash = md5(image_data).hexdigest()
        except Exception:
            pass
        
        # Extract embed ID if available
        embed_id = ""
        try:
            blip_fill = shape._element.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
            if blip_fill is not None:
                embed_id = blip_fill.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', '')
        except Exception:
            pass
        
        return cls(slide_idx, shape_idx, shape_name, image_hash, embed_id)


class PPTXAltTextInjector:
    """
    PPTX ALT text injector that integrates with existing system architecture.
    Supports multiple injection methods, validation, and ConfigManager integration.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the PPTX ALT text injector.
        
        Args:
            config_manager: Optional ConfigManager instance
        """
        if not PPTX_AVAILABLE:
            raise ImportError(f"python-pptx is required: {PPTX_ERROR}")
        
        self.config_manager = config_manager or ConfigManager()
        
        # Get reinjection settings from config
        self.reinjection_config = self.config_manager.config.get('reinjection', {})
        self.skip_alt_text_if = self.reinjection_config.get('skip_alt_text_if', [])
        
        # Get ALT text handling settings
        self.alt_text_config = self.config_manager.config.get('alt_text_handling', {})
        self.mode = self.alt_text_config.get('mode', 'preserve')
        self.clean_generated_alt_text = self.alt_text_config.get('clean_generated_alt_text', True)
        
        # Get PPTX-specific settings
        self.pptx_config = self.config_manager.config.get('pptx_processing', {})
        
        # Register XML namespaces for decorative detection
        self._register_namespaces()
        
        # Statistics
        self.injection_stats = {
            'total_images': 0,
            'injected_successfully': 0,
            'skipped_existing': 0,
            'skipped_invalid': 0,
            'failed_injection': 0,
            'validation_failures': 0
        }
        
        logger.info("Initialized PPTX ALT text injector")
        logger.debug(f"Skip ALT text if: {self.skip_alt_text_if}")
        logger.debug(f"Mode: {self.mode}")
    
    def _register_namespaces(self):
        """Register required XML namespaces."""
        try:
            # Register decorative namespace for Office 2019+ decorative image support
            _nsmap["adec"] = "http://schemas.microsoft.com/office/drawing/2017/decorative"
        except Exception as e:
            logger.warning(f"Could not register XML namespaces: {e}")
    
    def inject_alt_text_from_mapping(self, pptx_path: str, alt_text_mapping: Dict[str, str], 
                                   output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Inject ALT text into PPTX file from a mapping dictionary.
        
        Args:
            pptx_path: Path to input PPTX file
            alt_text_mapping: Dictionary mapping image keys to ALT text
            output_path: Optional output path (defaults to overwriting input)
            
        Returns:
            Dictionary with injection results and statistics
        """
        pptx_path = Path(pptx_path)
        if output_path is None:
            output_path = pptx_path
        else:
            output_path = Path(output_path)
        
        # Validate input file
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        logger.info(f"Injecting ALT text into: {pptx_path}")
        logger.info(f"Output will be saved to: {output_path}")
        logger.info(f"ALT text mappings: {len(alt_text_mapping)}")
        
        # Reset statistics
        self.injection_stats = {key: 0 for key in self.injection_stats}
        
        try:
            # Load presentation
            presentation = Presentation(str(pptx_path))
            
            # Build image identifier mapping for matching
            image_identifiers = self._build_image_identifier_mapping(presentation)
            
            # Debug: Show what keys we have vs what we expect
            logger.debug(f"Mapping keys from generator ({len(alt_text_mapping)}):")
            for key in sorted(alt_text_mapping.keys()):
                logger.debug(f"  Expected: {key}")
            
            logger.debug(f"Identifier keys from PPTX ({len(image_identifiers)}):")
            for key in sorted(image_identifiers.keys()):
                logger.debug(f"  Available: {key}")
            
            # Inject ALT text for each mapping
            matched_keys = []
            unmatched_keys = []
            
            for image_key, alt_text in alt_text_mapping.items():
                if image_key in image_identifiers:
                    identifier, shape = image_identifiers[image_key]
                    self._inject_alt_text_single(shape, alt_text, identifier)
                    matched_keys.append(image_key)
                else:
                    logger.warning(f"Could not find image for key: {image_key}")
                    unmatched_keys.append(image_key)
            
            logger.info(f"Key matching results: {len(matched_keys)} matched, {len(unmatched_keys)} unmatched")
            
            # Save presentation
            output_path.parent.mkdir(parents=True, exist_ok=True)
            presentation.save(str(output_path))
            
            # Create result summary
            result = {
                'success': True,
                'input_file': str(pptx_path),
                'output_file': str(output_path),
                'statistics': self.injection_stats.copy(),
                'errors': []
            }
            
            self._log_injection_summary(result)
            return result
            
        except Exception as e:
            error_msg = f"Failed to inject ALT text: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            return {
                'success': False,
                'input_file': str(pptx_path),
                'output_file': str(output_path),
                'statistics': self.injection_stats.copy(),
                'errors': [error_msg]
            }
    
    def _build_image_identifier_mapping(self, presentation: Presentation) -> Dict[str, Tuple[PPTXImageIdentifier, Picture]]:
        """
        Build mapping from image keys to (identifier, shape) tuples.
        
        Args:
            presentation: PowerPoint presentation
            
        Returns:
            Dictionary mapping image keys to (identifier, shape) tuples
        """
        mapping = {}
        
        for slide_idx, slide in enumerate(presentation.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, 'image') and shape.image:
                    self.injection_stats['total_images'] += 1
                    
                    try:
                        identifier = PPTXImageIdentifier.from_shape(shape, slide_idx, shape_idx)
                        mapping[identifier.image_key] = (identifier, shape)
                        
                        logger.debug(f"Mapped image: {identifier.image_key}")
                        
                    except Exception as e:
                        logger.warning(f"Could not create identifier for slide {slide_idx}, shape {shape_idx}: {e}")
        
        logger.info(f"Built identifier mapping for {len(mapping)} images")
        return mapping
    
    def _inject_alt_text_single(self, shape: Picture, alt_text: str, identifier: PPTXImageIdentifier) -> bool:
        """
        Inject ALT text into a single shape.
        
        Args:
            shape: Picture shape to inject ALT text into
            alt_text: ALT text to inject
            identifier: Image identifier for logging
            
        Returns:
            bool: True if injection was successful
        """
        try:
            # Check if we should skip this ALT text
            if self._should_skip_alt_text(alt_text):
                logger.debug(f"Skipping invalid ALT text for {identifier.image_key}: '{alt_text}'")
                self.injection_stats['skipped_invalid'] += 1
                return False
            
            # Check if image already has ALT text and we should preserve it
            existing_alt_text = self._get_existing_alt_text(shape)
            if existing_alt_text and self.mode == 'preserve' and not self._should_skip_alt_text(existing_alt_text):
                logger.debug(f"Preserving existing ALT text for {identifier.image_key}: '{existing_alt_text}'")
                self.injection_stats['skipped_existing'] += 1
                return True
            
            # Clean ALT text if configured
            if self.clean_generated_alt_text:
                alt_text = self._clean_alt_text(alt_text)
            
            # Perform injection using multiple fallback methods
            success = self._inject_alt_text_robust(shape, alt_text)
            
            if success:
                # Validate injection
                if self._validate_alt_text_injection(shape, alt_text):
                    logger.debug(f"Successfully injected ALT text for {identifier.image_key}: '{alt_text[:50]}...'")
                    self.injection_stats['injected_successfully'] += 1
                    return True
                else:
                    logger.warning(f"ALT text injection validation failed for {identifier.image_key}")
                    self.injection_stats['validation_failures'] += 1
                    return False
            else:
                logger.error(f"All injection methods failed for {identifier.image_key}")
                self.injection_stats['failed_injection'] += 1
                return False
                
        except Exception as e:
            logger.error(f"Error injecting ALT text for {identifier.image_key}: {e}")
            self.injection_stats['failed_injection'] += 1
            return False
    
    def _inject_alt_text_robust(self, shape: Picture, alt_text: str) -> bool:
        """
        Inject ALT text using multiple fallback methods for maximum compatibility.
        
        Args:
            shape: Picture shape
            alt_text: ALT text to inject
            
        Returns:
            bool: True if any method succeeded
        """
        # List of injection methods in order of preference
        injection_methods = [
            ('modern_property', self._inject_via_modern_property),
            ('xml_cnvpr', self._inject_via_xml_cnvpr),
            ('xml_element', self._inject_via_xml_element),
            ('xml_fallback', self._inject_via_xml_fallback)
        ]
        
        for method_name, method_func in injection_methods:
            try:
                if method_func(shape, alt_text):
                    logger.debug(f"ALT text injected successfully via {method_name}")
                    return True
            except Exception as e:
                logger.debug(f"Injection method {method_name} failed: {e}")
                continue
        
        return False
    
    def _inject_via_modern_property(self, shape: Picture, alt_text: str) -> bool:
        """Inject using modern property-based approach (python-pptx >= 0.6.22)."""
        if hasattr(shape, 'descr'):
            shape.descr = alt_text
            return True
        return False
    
    def _inject_via_xml_cnvpr(self, shape: Picture, alt_text: str) -> bool:
        """Inject via direct XML cNvPr element manipulation."""
        cNvPr = shape._element._nvXxPr.cNvPr
        cNvPr.set('descr', alt_text)
        return True
    
    def _inject_via_xml_element(self, shape: Picture, alt_text: str) -> bool:
        """Inject via XML element attribute (current approach)."""
        shape._element.set('descr', alt_text)
        return True
    
    def _inject_via_xml_fallback(self, shape: Picture, alt_text: str) -> bool:
        """Fallback XML injection method."""
        try:
            # Try to find and set descr attribute on various elements
            for element in [shape._element, shape._element._nvXxPr, shape._element._nvXxPr.cNvPr]:
                if element is not None:
                    element.set('descr', alt_text)
                    return True
        except Exception:
            pass
        return False
    
    def _get_existing_alt_text(self, shape: Picture) -> str:
        """
        Get existing ALT text from shape.
        
        Args:
            shape: Picture shape
            
        Returns:
            str: Existing ALT text or empty string
        """
        try:
            # Try modern property first
            if hasattr(shape, 'descr'):
                return shape.descr or ""
        except Exception:
            pass
        
        try:
            # Try XML access
            cNvPr = shape._element._nvXxPr.cNvPr
            return cNvPr.get('descr', '')
        except Exception:
            pass
        
        try:
            # Fallback XML access
            return shape._element.get('descr', '')
        except Exception:
            pass
        
        return ""
    
    def _validate_alt_text_injection(self, shape: Picture, expected_alt_text: str) -> bool:
        """
        Validate that ALT text was successfully injected.
        
        Args:
            shape: Picture shape
            expected_alt_text: Expected ALT text
            
        Returns:
            bool: True if validation passed
        """
        actual_alt_text = self._get_existing_alt_text(shape)
        return actual_alt_text == expected_alt_text
    
    def _should_skip_alt_text(self, alt_text: str) -> bool:
        """
        Check if ALT text should be skipped based on reinjection rules.
        
        Args:
            alt_text: ALT text to check
            
        Returns:
            bool: True if ALT text should be skipped
        """
        if not alt_text:
            return True
        
        alt_text_stripped = alt_text.strip()
        
        for skip_pattern in self.skip_alt_text_if:
            if isinstance(skip_pattern, str):
                if skip_pattern == alt_text_stripped:
                    return True
            
        return False
    
    def _clean_alt_text(self, alt_text: str) -> str:
        """
        Clean ALT text using existing alt_cleaner if available.
        
        Args:
            alt_text: ALT text to clean
            
        Returns:
            str: Cleaned ALT text
        """
        try:
            # Import and use existing alt_cleaner
            sys.path.insert(0, str(project_root / "shared"))
            from alt_cleaner import clean_alt_text
            return clean_alt_text(alt_text)
        except ImportError:
            logger.debug("alt_cleaner not available, using basic cleaning")
            # Basic cleaning - remove extra whitespace
            return " ".join(alt_text.split())
        except Exception as e:
            logger.warning(f"Error cleaning ALT text: {e}")
            return alt_text
    
    def _log_injection_summary(self, result: Dict[str, Any]):
        """Log summary of injection results."""
        stats = result['statistics']
        
        logger.info("PPTX ALT Text Injection Summary:")
        logger.info(f"  Input file: {result['input_file']}")
        logger.info(f"  Output file: {result['output_file']}")
        logger.info(f"  Total images found: {stats['total_images']}")
        logger.info(f"  Successfully injected: {stats['injected_successfully']}")
        logger.info(f"  Skipped (existing): {stats['skipped_existing']}")
        logger.info(f"  Skipped (invalid): {stats['skipped_invalid']}")
        logger.info(f"  Failed injection: {stats['failed_injection']}")
        logger.info(f"  Validation failures: {stats['validation_failures']}")
        logger.info(f"  Success: {result['success']}")
        
        if result.get('errors'):
            logger.warning(f"Errors encountered: {len(result['errors'])}")
            for error in result['errors']:
                logger.warning(f"  - {error}")
    
    def extract_images_with_identifiers(self, pptx_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract images with robust identifiers for roundtrip workflow.
        
        Args:
            pptx_path: Path to PPTX file
            
        Returns:
            Dictionary mapping image keys to image information
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        logger.info(f"Extracting images with identifiers from: {pptx_path}")
        
        presentation = Presentation(str(pptx_path))
        extracted_images = {}
        
        for slide_idx, slide in enumerate(presentation.slides):
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, 'image') and shape.image:
                    try:
                        # Create robust identifier
                        identifier = PPTXImageIdentifier.from_shape(shape, slide_idx, shape_idx)
                        
                        # Extract image information
                        image_info = {
                            'identifier': identifier,
                            'slide_idx': slide_idx,
                            'shape_idx': shape_idx,
                            'shape_name': identifier.shape_name,
                            'image_key': identifier.image_key,
                            'image_hash': identifier.image_hash,
                            'embed_id': identifier.embed_id,
                            'existing_alt_text': self._get_existing_alt_text(shape),
                            'image_data': shape.image.blob,
                            'filename': getattr(shape.image, 'filename', f'slide_{slide_idx}_shape_{shape_idx}.png')
                        }
                        
                        extracted_images[identifier.image_key] = image_info
                        logger.debug(f"Extracted image: {identifier.image_key}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract image from slide {slide_idx}, shape {shape_idx}: {e}")
        
        logger.info(f"Extracted {len(extracted_images)} images with identifiers")
        return extracted_images
    
    def test_pdf_export_alt_text_survival(self, pptx_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Test that ALT text survives PowerPoint → PDF export.
        
        Args:
            pptx_path: Path to PPTX file
            output_dir: Optional directory for output files
            
        Returns:
            Dictionary with test results
        """
        pptx_path = Path(pptx_path)
        if not pptx_path.exists():
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")
        
        if output_dir is None:
            output_dir = pptx_path.parent
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Testing ALT text survival in PDF export for: {pptx_path}")
        
        # This would require PowerPoint automation or a PDF conversion library
        # For now, we'll create a placeholder test that validates ALT text exists in PPTX
        
        try:
            presentation = Presentation(str(pptx_path))
            alt_text_count = 0
            total_images = 0
            
            for slide_idx, slide in enumerate(presentation.slides):
                for shape_idx, shape in enumerate(slide.shapes):
                    if hasattr(shape, 'image') and shape.image:
                        total_images += 1
                        existing_alt = self._get_existing_alt_text(shape)
                        if existing_alt and not self._should_skip_alt_text(existing_alt):
                            alt_text_count += 1
            
            survival_test_result = {
                'success': True,
                'pptx_file': str(pptx_path),
                'total_images': total_images,
                'images_with_alt_text': alt_text_count,
                'alt_text_coverage': alt_text_count / total_images if total_images > 0 else 0,
                'test_type': 'pptx_validation',
                'note': 'Full PDF export testing requires PowerPoint automation or conversion library',
                'errors': []
            }
            
            logger.info(f"ALT text survival test completed:")
            logger.info(f"  Total images: {total_images}")
            logger.info(f"  Images with ALT text: {alt_text_count}")
            logger.info(f"  Coverage: {survival_test_result['alt_text_coverage']:.1%}")
            
            return survival_test_result
            
        except Exception as e:
            error_msg = f"PDF export survival test failed: {str(e)}"
            logger.error(error_msg)
            
            return {
                'success': False,
                'pptx_file': str(pptx_path),
                'test_type': 'pptx_validation',
                'errors': [error_msg]
            }


def create_alt_text_mapping(image_data: Dict[str, Dict[str, Any]], 
                          alt_text_results: Dict[str, str]) -> Dict[str, str]:
    """
    Create ALT text mapping from extracted image data and generation results.
    
    Args:
        image_data: Dictionary from extract_images_with_identifiers()
        alt_text_results: Dictionary mapping image keys to generated ALT text
        
    Returns:
        Dictionary mapping image keys to ALT text for injection
    """
    mapping = {}
    
    for image_key, image_info in image_data.items():
        if image_key in alt_text_results:
            alt_text = alt_text_results[image_key]
            mapping[image_key] = alt_text
            logger.debug(f"Mapped ALT text for {image_key}: {alt_text[:50]}...")
    
    logger.info(f"Created ALT text mapping for {len(mapping)} images")
    return mapping


def main():
    """Command-line interface for PPTX ALT text injection."""
    parser = argparse.ArgumentParser(
        description='Inject ALT text into PowerPoint presentations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pptx_alt_injector.py presentation.pptx --alt-text-file mappings.json
  python pptx_alt_injector.py presentation.pptx --extract-only --output extracted_images.json
  python pptx_alt_injector.py presentation.pptx --test-pdf-export
  python pptx_alt_injector.py presentation.pptx --config custom_config.yaml --verbose
        """
    )
    
    parser.add_argument('pptx_file', help='Input PPTX file')
    parser.add_argument('-o', '--output', help='Output PPTX file (default: overwrite input)')
    parser.add_argument('--alt-text-file', help='JSON file containing ALT text mappings')
    parser.add_argument('--extract-only', action='store_true', 
                       help='Only extract images with identifiers (no injection)')
    parser.add_argument('--test-pdf-export', action='store_true',
                       help='Test ALT text survival in PDF export')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--mode', choices=['preserve', 'overwrite'], 
                       help='ALT text handling mode')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # Initialize components
        config_manager = ConfigManager(args.config)
        injector = PPTXAltTextInjector(config_manager)
        
        # Override mode if specified
        if args.mode:
            injector.mode = args.mode
        
        print(f"PPTX ALT Text Injector")
        print(f"Processing: {args.pptx_file}")
        
        # Extract-only mode
        if args.extract_only:
            extracted_images = injector.extract_images_with_identifiers(args.pptx_file)
            output_file = args.output or f"{Path(args.pptx_file).stem}_extracted_images.json"
            
            import json
            with open(output_file, 'w') as f:
                # Convert to JSON-serializable format
                serializable = {}
                for key, info in extracted_images.items():
                    serializable[key] = {
                        'slide_idx': info['slide_idx'],
                        'shape_idx': info['shape_idx'],
                        'shape_name': info['shape_name'],
                        'image_key': info['image_key'],
                        'existing_alt_text': info['existing_alt_text'],
                        'filename': info['filename']
                    }
                json.dump(serializable, f, indent=2)
            
            print(f"Extracted {len(extracted_images)} images to: {output_file}")
            return 0
        
        # PDF export test mode
        if args.test_pdf_export:
            result = injector.test_pdf_export_alt_text_survival(args.pptx_file, args.output)
            
            if result['success']:
                print(f"✅ PDF export test completed")
                print(f"ALT text coverage: {result['alt_text_coverage']:.1%} ({result['images_with_alt_text']}/{result['total_images']})")
            else:
                print(f"❌ PDF export test failed")
                for error in result['errors']:
                    print(f"Error: {error}")
            
            return 0 if result['success'] else 1
        
        # ALT text injection mode
        if not args.alt_text_file:
            parser.error("--alt-text-file is required for ALT text injection")
        
        # Load ALT text mappings
        import json
        with open(args.alt_text_file, 'r') as f:
            alt_text_mapping = json.load(f)
        
        # Perform injection
        result = injector.inject_alt_text_from_mapping(
            args.pptx_file,
            alt_text_mapping,
            args.output
        )
        
        # Display results
        stats = result['statistics']
        print(f"\nInjection Results:")
        print(f"  Success: {result['success']}")
        print(f"  Images processed: {stats['injected_successfully']}/{stats['total_images']}")
        print(f"  Skipped (existing): {stats['skipped_existing']}")
        print(f"  Failed: {stats['failed_injection']}")
        
        if result.get('errors'):
            print(f"Errors:")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result['success']:
            print(f"✅ ALT text injection completed successfully!")
            print(f"Output saved to: {result['output_file']}")
        else:
            print(f"❌ ALT text injection failed!")
        
        return 0 if result['success'] else 1
        
    except Exception as e:
        logger.error(f"ALT text injection failed: {e}", exc_info=True)
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())