"""
PPTX Accessibility Processor - Adapted from PDF processor to work with PowerPoint files.
Integrates with existing ConfigManager, FlexibleAltGenerator, medical prompts, and decorative detection.
"""

import logging
import os
import sys
import tempfile
import time
import base64
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from collections import defaultdict
from hashlib import md5

# Third-party imports for PPTX processing
try:
    from pptx import Presentation
    from pptx.shapes.picture import Picture
    from pptx.shapes.base import BaseShape
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    from pptx.oxml.ns import _nsmap
except ImportError as e:
    raise ImportError(
        "python-pptx is required for PPTX processing. Install with: pip install python-pptx"
    ) from e

# Setup paths for shared modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))

# Import shared modules
from config_manager import ConfigManager
from unified_alt_generator import FlexibleAltGenerator
from decorative_filter import (
    is_force_decorative_by_filename, 
    is_decorative_image,
    get_image_hash,
    validate_decorative_config
)

logger = logging.getLogger(__name__)


class PPTXImageInfo:
    """Container for PPTX image information."""
    
    def __init__(self, shape: Picture, slide_idx: int, shape_idx: int, 
                 image_data: bytes, filename: str, slide_text: str = ""):
        self.shape = shape
        self.slide_idx = slide_idx
        self.shape_idx = shape_idx
        self.image_data = image_data
        self.filename = filename
        self.slide_text = slide_text
        self.image_hash = get_image_hash(image_data)
        
        # Extract shape properties
        self.width = shape.width.emu if shape.width else 0
        self.height = shape.height.emu if shape.height else 0
        self.left = shape.left.emu if shape.left else 0
        self.top = shape.top.emu if shape.top else 0
        
        # Convert EMU to pixels (1 EMU = 1/914400 inch, assume 96 DPI)
        self.width_px = int(self.width / 914400 * 96) if self.width else 0
        self.height_px = int(self.height / 914400 * 96) if self.height else 0
        self.left_px = int(self.left / 914400 * 96) if self.left else 0
        self.top_px = int(self.top / 914400 * 96) if self.top else 0
        
        # Unique identifier consistent with PPTXAltTextInjector
        self.image_key = self._create_consistent_image_key(slide_idx, shape_idx, shape)
    
    def _create_consistent_image_key(self, slide_idx: int, shape_idx: int, shape: Picture) -> str:
        """Create image key consistent with PPTXAltTextInjector."""
        components = [f"slide_{slide_idx}", f"shape_{shape_idx}"]
        
        # Add shape name if meaningful (not default Picture names)
        shape_name = getattr(shape, 'name', '')
        if shape_name and not shape_name.startswith('Picture'):
            components.append(f"name_{shape_name}")
        
        # Add hash for uniqueness (consistent with injector)
        if self.image_hash:
            components.append(f"hash_{self.image_hash[:8]}")
        
        return "_".join(components)


class PPTXShapeInfo:
    """Container for PPTX shape information for decorative detection."""
    
    def __init__(self, shape: BaseShape, slide_idx: int, shape_idx: int, slide_text: str = ""):
        self.shape = shape
        self.slide_idx = slide_idx
        self.shape_idx = shape_idx
        self.slide_text = slide_text
        
        # Extract shape properties
        self.shape_name = getattr(shape, 'name', 'unnamed')
        self.shape_type = getattr(shape, 'shape_type', None)
        self.shape_type_name = self._get_shape_type_name()
        
        # Dimensions
        self.width = shape.width.emu if hasattr(shape, 'width') and shape.width else 0
        self.height = shape.height.emu if hasattr(shape, 'height') and shape.height else 0
        self.left = shape.left.emu if hasattr(shape, 'left') and shape.left else 0
        self.top = shape.top.emu if hasattr(shape, 'top') and shape.top else 0
        
        # Convert EMU to pixels
        self.width_px = int(self.width / 914400 * 96) if self.width else 0
        self.height_px = int(self.height / 914400 * 96) if self.height else 0
        self.left_px = int(self.left / 914400 * 96) if self.left else 0
        self.top_px = int(self.top / 914400 * 96) if self.top else 0
        
        # Check for text content
        self.has_text = hasattr(shape, 'text') and bool(shape.text and shape.text.strip())
        self.text_content = shape.text.strip() if self.has_text else ""
        
        # Create unique identifier
        self.shape_key = f"slide_{slide_idx}_shape_{shape_idx}_{self.shape_name}"
    
    def _get_shape_type_name(self) -> str:
        """Get human-readable shape type name."""
        if self.shape_type is None:
            return "unknown"
        
        try:
            # Find the name of the shape type enum
            for attr_name in dir(MSO_SHAPE_TYPE):
                if not attr_name.startswith('_') and not callable(getattr(MSO_SHAPE_TYPE, attr_name, None)):
                    try:
                        attr_value = getattr(MSO_SHAPE_TYPE, attr_name)
                        if attr_value == self.shape_type:
                            return attr_name
                    except (AttributeError, TypeError):
                        continue
            return f"MSO_SHAPE_TYPE({self.shape_type})"
        except Exception as e:
            return f"error_getting_type({self.shape_type})"


class PPTXAccessibilityProcessor:
    """
    PPTX accessibility processor that integrates with the existing PDF ALT text system.
    Reuses ConfigManager, FlexibleAltGenerator, medical prompts, and decorative detection.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None, debug: bool = False):
        """
        Initialize the PPTX accessibility processor.
        
        Args:
            config_manager: Optional ConfigManager instance. If None, creates a new one.
        """
        self.config_manager = config_manager or ConfigManager()
        self.debug = debug
        
        # Validate decorative configuration
        if not validate_decorative_config(self.config_manager.config):
            logger.warning("Decorative configuration validation failed")
        
        # Initialize ALT text generator
        try:
            self.alt_generator = FlexibleAltGenerator(self.config_manager)
            logger.info("Initialized PPTX accessibility processor with ALT text generator")
        except Exception as e:
            logger.error(f"Failed to initialize ALT text generator: {e}")
            raise
        
        # Get processing configuration
        self.processing_config = self.config_manager.config.get('pptx_processing', {})
        
        # Decorative detection settings
        self.decorative_size_threshold = self.processing_config.get('decorative_size_threshold', 50)
        self.skip_decorative = self.processing_config.get('skip_decorative_images', True)
        
        # Context extraction settings
        self.include_slide_notes = self.processing_config.get('include_slide_notes', True)
        self.include_slide_text = self.processing_config.get('include_slide_text', True)
        self.max_context_length = self.processing_config.get('max_context_length', 200)
        
        logger.debug(f"Decorative size threshold: {self.decorative_size_threshold}px")
        logger.debug(f"Skip decorative images: {self.skip_decorative}")
        logger.debug(f"Include slide notes: {self.include_slide_notes}")
        logger.debug(f"Include slide text: {self.include_slide_text}")
    
    def process_pptx(self, pptx_path: str, output_path: Optional[str] = None, 
                    force_decorative: bool = False, failed_generation_callback=None, debug: bool = False) -> Dict[str, Any]:
        """
        Process a PPTX file to add ALT text to images.
        
        Args:
            pptx_path: Path to the input PPTX file
            output_path: Optional path for output file. If None, overwrites original.
            force_decorative: Force decorative fallback for failed generations
            failed_generation_callback: Callback function for failed generations
            
        Returns:
            Dictionary with processing statistics
        """
        start_time = time.time()
        pptx_path = Path(pptx_path)
        debug = debug or self.debug
        
        # Initialize result structure
        result = {
            'success': False,
            'input_file': str(pptx_path),
            'output_file': '',
            'total_slides': 0,
            'total_images': 0,
            'processed_images': 0,
            'decorative_images': 0,
            'fallback_decorative': 0,
            'failed_images': 0,
            'total_shapes': 0,
            'decorative_shapes_marked': 0,
            'shapes_with_content': 0,
            'generation_time': 0.0,
            'injection_time': 0.0,
            'decorative_marking_time': 0.0,
            'total_time': 0.0,
            'errors': []
        }
        
        # Validate input file
        if not pptx_path.exists():
            error_msg = f"PPTX file not found: {pptx_path}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            return result
        
        # Determine output path
        if output_path is None:
            output_path = pptx_path  # Overwrite original
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
        
        result['output_file'] = str(output_path)
        
        logger.info(f"Processing PPTX: {pptx_path.name}")
        logger.info(f"Output will be saved to: {output_path}")
        
        try:
            # Step 1: Extract images and context from PPTX
            logger.info("Step 1: Extracting images and context from PPTX...")
            extraction_start = time.time()
            
            presentation, image_infos = self._extract_images_from_pptx(str(pptx_path))
            
            extraction_time = time.time() - extraction_start
            logger.info(f"Context extraction completed in {extraction_time:.2f}s")
            
            result['total_slides'] = len(presentation.slides)
            result['total_images'] = len(image_infos)
            
            if not image_infos:
                logger.warning(f"No images found in PPTX: {pptx_path.name}")
                result['success'] = True  # Not an error, just no images to process
                result['total_time'] = time.time() - start_time
                return result
            
            logger.info(f"Found {len(image_infos)} images across {result['total_slides']} slides")
            
            # Step 2: Generate ALT text for images
            logger.info("Step 2: Generating ALT text for images...")
            generation_start = time.time()
            
            alt_text_mapping = {}
            image_tracker = defaultdict(list)  # Track duplicate images
            
            for image_info in image_infos:
                # Track image occurrences for duplicate detection
                image_tracker[image_info.image_hash].append(image_info)
            
            for image_info in image_infos:
                generation_failure_reason = None
                
                try:
                    # Check if we should generate ALT text for this image
                    if not self._should_generate_alt_text(image_info, image_tracker):
                        alt_text_mapping[image_info.image_key] = {
                            'alt_text': '[Decorative image]',
                            'shape': image_info.shape,
                            'slide_idx': image_info.slide_idx,
                            'shape_idx': image_info.shape_idx
                        }
                        result['decorative_images'] += 1
                        logger.debug(f"Skipping decorative image: {image_info.image_key}")
                        continue
                    
                    # Generate ALT text with comprehensive error handling
                    if debug:
                        logger.info(f"🔍 DEBUG: Attempting ALT text generation for {image_info.image_key}")
                        logger.info(f"🔍 DEBUG: Image: {image_info.width_px}x{image_info.height_px}px, file: {image_info.filename}")
                        logger.info(f"🔍 DEBUG: Slide text: {image_info.slide_text[:100]}...")
                    
                    alt_text, failure_reason = self._generate_alt_text_for_image_with_validation(image_info, debug)
                    
                    if alt_text and alt_text.strip() and alt_text.strip() != "":
                        # Successfully generated valid ALT text
                        alt_text_mapping[image_info.image_key] = {
                            'alt_text': alt_text.strip(),
                            'shape': image_info.shape,
                            'slide_idx': image_info.slide_idx,
                            'shape_idx': image_info.shape_idx
                        }
                        result['processed_images'] += 1
                        if debug:
                            logger.info(f"✅ DEBUG: Generated ALT text for {image_info.image_key}: {alt_text[:50]}...")
                        else:
                            logger.info(f"Generated ALT text for {image_info.image_key}: {alt_text[:50]}...")
                    else:
                        # Generation failed or returned empty/invalid text
                        generation_failure_reason = failure_reason or "Empty or invalid ALT text returned"
                        
                        if debug:
                            logger.warning(f"❌ DEBUG: Generation failed for {image_info.image_key}: {generation_failure_reason}")
                        
                        # Apply decorative fallback for 100% coverage
                        if force_decorative:
                            fallback_alt_text = "[Decorative image]"
                            alt_text_mapping[image_info.image_key] = {
                                'alt_text': fallback_alt_text,
                                'shape': image_info.shape,
                                'slide_idx': image_info.slide_idx,
                                'shape_idx': image_info.shape_idx
                            }
                            result['fallback_decorative'] += 1
                            logger.info(f"Applied decorative fallback for {image_info.image_key} - Reason: {generation_failure_reason}")
                            
                            # Log failed generation for manual review
                            if failed_generation_callback:
                                failed_generation_callback(
                                    image_info.image_key,
                                    {
                                        'slide_idx': image_info.slide_idx,
                                        'shape_idx': image_info.shape_idx,
                                        'filename': image_info.filename,
                                        'width_px': image_info.width_px,
                                        'height_px': image_info.height_px,
                                        'slide_text': image_info.slide_text
                                    },
                                    f"ALT text generation failed ({generation_failure_reason}), applied decorative fallback"
                                )
                        else:
                            result['failed_images'] += 1
                            error_msg = f"Failed to generate ALT text for {image_info.image_key}: {generation_failure_reason}"
                            logger.warning(error_msg)
                            result['errors'].append(error_msg)
                            
                            # Log failed generation for manual review
                            if failed_generation_callback:
                                failed_generation_callback(
                                    image_info.image_key,
                                    {
                                        'slide_idx': image_info.slide_idx,
                                        'shape_idx': image_info.shape_idx,
                                        'filename': image_info.filename,
                                        'width_px': image_info.width_px,
                                        'height_px': image_info.height_px,
                                        'slide_text': image_info.slide_text
                                    },
                                    f"ALT text generation failed: {generation_failure_reason}"
                                )
                
                except Exception as e:
                    generation_failure_reason = f"Exception during generation: {str(e)}"
                    
                    if debug:
                        logger.error(f"💥 DEBUG: Exception processing {image_info.image_key}: {e}", exc_info=True)
                    
                    # Apply decorative fallback for exceptions too if force_decorative is enabled
                    if force_decorative:
                        fallback_alt_text = "[Decorative image]"
                        alt_text_mapping[image_info.image_key] = {
                            'alt_text': fallback_alt_text,
                            'shape': image_info.shape,
                            'slide_idx': image_info.slide_idx,
                            'shape_idx': image_info.shape_idx
                        }
                        result['fallback_decorative'] += 1
                        logger.info(f"Applied decorative fallback for {image_info.image_key} after exception - Reason: {generation_failure_reason}")
                        
                        # Log failed generation for manual review
                        if failed_generation_callback:
                            failed_generation_callback(
                                image_info.image_key,
                                {
                                    'slide_idx': image_info.slide_idx,
                                    'shape_idx': image_info.shape_idx,
                                    'filename': image_info.filename,
                                    'width_px': image_info.width_px,
                                    'height_px': image_info.height_px,
                                    'slide_text': image_info.slide_text
                                },
                                f"Exception during generation ({generation_failure_reason}), applied decorative fallback"
                            )
                    else:
                        result['failed_images'] += 1
                        error_msg = f"Error processing {image_info.image_key}: {str(e)}"
                        logger.error(error_msg)
                        result['errors'].append(error_msg)
                        
                        # Log failed generation for manual review
                        if failed_generation_callback:
                            failed_generation_callback(
                                image_info.image_key,
                                {
                                    'slide_idx': image_info.slide_idx,
                                    'shape_idx': image_info.shape_idx,
                                    'filename': image_info.filename,
                                    'width_px': image_info.width_px,
                                    'height_px': image_info.height_px,
                                    'slide_text': image_info.slide_text
                                },
                                f"Exception during generation: {str(e)}"
                            )
            
            result['generation_time'] = time.time() - generation_start
            logger.info(f"ALT text generation completed in {result['generation_time']:.2f}s")
            
            # Step 3: Validate 100% coverage before injection
            logger.info("Step 3: Validating ALT text coverage...")
            validation_result = self._validate_complete_coverage(image_infos, alt_text_mapping, force_decorative, debug)
            
            if not validation_result['complete_coverage']:
                missing_count = validation_result['missing_count']
                error_msg = f"Incomplete ALT text coverage: {missing_count} images missing ALT text"
                logger.error(error_msg)
                result['errors'].append(error_msg)
                
                if debug:
                    logger.error("❌ DEBUG: Images missing ALT text:")
                    for missing_key in validation_result['missing_images']:
                        logger.error(f"   - {missing_key}")
            
            # Step 4: Inject ALT text into PPTX
            if alt_text_mapping:
                logger.info("Step 4: Adding ALT text to PPTX...")
                injection_start = time.time()
                
                if debug:
                    logger.info(f"🔍 DEBUG: Injecting {len(alt_text_mapping)} ALT text mappings")
                    for key, info in list(alt_text_mapping.items())[:3]:  # Show first 3
                        logger.info(f"🔍 DEBUG: {key} -> '{info['alt_text'][:30]}...'")
                
                injection_success = self._inject_alt_text_to_pptx(
                    presentation, alt_text_mapping, str(output_path), debug
                )
                
                result['injection_time'] = time.time() - injection_start
                logger.info(f"ALT text injection completed in {result['injection_time']:.2f}s")
                
                if injection_success:
                    # Step 5: Detect and mark decorative shapes
                    logger.info("Step 5: Detecting and marking decorative shapes...")
                    decorative_start = time.time()
                    
                    decorative_shapes = self.detect_decorative_shapes(presentation, debug)
                    result['total_shapes'], result['shapes_with_content'] = self._count_all_shapes(presentation)
                    
                    if decorative_shapes:
                        marked_count = self.set_decorative_flag(decorative_shapes, debug)
                        result['decorative_shapes_marked'] = marked_count
                        
                        if debug:
                            logger.info(f"🔍 DEBUG: Marked {marked_count} decorative shapes")
                    else:
                        logger.info("No decorative shapes detected")
                        result['decorative_shapes_marked'] = 0
                    
                    result['decorative_marking_time'] = time.time() - decorative_start
                    logger.info(f"Decorative shape processing completed in {result['decorative_marking_time']:.2f}s")
                    
                    result['success'] = True
                    logger.info("✅ PPTX processing completed successfully!")
                    
                    # Final coverage validation
                    final_coverage = validation_result['total_coverage_percent']
                    logger.info(f"📊 Final ALT text coverage: {final_coverage:.1f}%")
                    if final_coverage == 100.0:
                        logger.info("🎯 100% ALT text coverage achieved!")
                    
                    # Report decorative shape coverage
                    if result['total_shapes'] > 0:
                        shape_coverage = (result['decorative_shapes_marked'] / result['total_shapes']) * 100
                        logger.info(f"🎨 Decorative shapes marked: {result['decorative_shapes_marked']}/{result['total_shapes']} ({shape_coverage:.1f}%)")
                else:
                    error_msg = "ALT text injection failed"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
            else:
                logger.warning("No ALT text to inject - this should not happen with proper fallback")
                result['success'] = False
                result['errors'].append("No ALT text mappings generated - fallback system failed")
            
        except Exception as e:
            error_msg = f"Unexpected error during PPTX processing: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result['errors'].append(error_msg)
        
        # Calculate total processing time
        result['total_time'] = time.time() - start_time
        
        # Log final statistics
        self._log_processing_summary(result)
        
        return result
    
    def _extract_images_from_pptx(self, pptx_path: str) -> Tuple[Presentation, List[PPTXImageInfo]]:
        """
        Extract all images from PPTX with their context, including grouped shapes, 
        chart elements, embedded objects, and images in text boxes.
        
        Args:
            pptx_path: Path to PPTX file
            
        Returns:
            Tuple of (Presentation object, List of PPTXImageInfo objects)
        """
        presentation = Presentation(pptx_path)
        image_infos = []
        
        for slide_idx, slide in enumerate(presentation.slides):
            logger.debug(f"Processing slide {slide_idx + 1}")
            
            # Extract slide text for context
            slide_text = self._extract_slide_text(slide) if self.include_slide_text else ""
            
            # Extract slide notes for context
            slide_notes = self._extract_slide_notes(slide) if self.include_slide_notes else ""
            
            # Combine slide context
            slide_context = []
            if slide_text:
                slide_context.append(slide_text)
            if slide_notes:
                slide_context.append(f"Notes: {slide_notes}")
            slide_context_str = " ".join(slide_context)
            
            # Debug: Log all shapes found on this slide with detailed enumeration
            logger.debug(f"Slide {slide_idx + 1} has {len(slide.shapes)} shapes:")
            self._enumerate_all_shapes(slide.shapes, indent="  ")
            
            # Process all shapes recursively to find images
            images_found_on_slide = self._extract_images_from_shapes(
                slide.shapes, slide_idx, slide_context_str
            )
            
            image_infos.extend(images_found_on_slide)
            logger.debug(f"Found {len(images_found_on_slide)} images on slide {slide_idx + 1}")
        
        # Also attempt to find images through presentation relationships
        # This can catch images that aren't accessible through the shape API
        logger.debug("Attempting to find additional images through presentation relationships...")
        relationship_images = self._extract_images_from_relationships(presentation)
        
        logger.info(f"Extracted {len(image_infos)} images via shapes, {len(relationship_images)} via relationships from {len(presentation.slides)} slides")
        logger.info(f"Total unique images found: {len(image_infos)}")
        return presentation, image_infos
    
    def _extract_images_from_shapes(self, shapes, slide_idx: int, slide_context: str, parent_group_idx: int = None) -> List[PPTXImageInfo]:
        """
        Recursively extract images from shapes, including grouped shapes, charts, and embedded objects.
        
        Args:
            shapes: Collection of shapes to process
            slide_idx: Slide index
            slide_context: Slide context text
            parent_group_idx: Index of parent group if this is a nested call
            
        Returns:
            List of PPTXImageInfo objects
        """
        image_infos = []
        
        for shape_idx, shape in enumerate(shapes):
            try:
                # Create unique shape identifier
                if parent_group_idx is not None:
                    shape_id = f"{parent_group_idx}_{shape_idx}"
                else:
                    shape_id = shape_idx
                
                # Debug: Log detailed shape information
                shape_name = getattr(shape, 'name', 'unnamed')
                shape_type = getattr(shape, 'shape_type', 'unknown')
                logger.debug(f"    Examining shape {shape_id}: {type(shape).__name__} (type={shape_type}, name='{shape_name}')")
                
                # Check for various types of images
                images_from_shape = []
                
                # 1. Direct picture shapes (original logic)
                if hasattr(shape, 'image') and shape.image:
                    logger.debug(f"      -> Found direct picture shape")
                    try:
                        image_data = shape.image.blob
                        filename = getattr(shape.image, 'filename', f'slide_{slide_idx}_shape_{shape_id}.png')
                        
                        image_info = PPTXImageInfo(
                            shape=shape,
                            slide_idx=slide_idx,
                            shape_idx=shape_id,
                            image_data=image_data,
                            filename=filename,
                            slide_text=slide_context[:self.max_context_length] if slide_context else ""
                        )
                        images_from_shape.append(image_info)
                        logger.debug(f"      -> Extracted direct image: {filename}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract direct image from shape {shape_id}: {e}")
                
                # 2. Group shapes (recursively process shapes within groups)
                if hasattr(shape, 'shapes'):
                    logger.debug(f"      -> Found group shape with {len(shape.shapes)} child shapes")
                    group_images = self._extract_images_from_shapes(
                        shape.shapes, slide_idx, slide_context, shape_id
                    )
                    images_from_shape.extend(group_images)
                    logger.debug(f"      -> Extracted {len(group_images)} images from group")
                
                # 3. Chart shapes (may contain images)
                if hasattr(shape, 'chart'):
                    logger.debug(f"      -> Found chart shape")
                    chart_images = self._extract_images_from_chart(shape.chart, slide_idx, shape_id, slide_context)
                    images_from_shape.extend(chart_images)
                    logger.debug(f"      -> Extracted {len(chart_images)} images from chart")
                
                # 4. Text boxes with image fills
                if hasattr(shape, 'text_frame') and hasattr(shape, 'fill'):
                    logger.debug(f"      -> Examining text box for image fill")
                    fill_images = self._extract_images_from_fill(shape.fill, slide_idx, shape_id, slide_context, shape_name)
                    images_from_shape.extend(fill_images)
                    if fill_images:
                        logger.debug(f"      -> Extracted {len(fill_images)} images from text box fill")
                
                # 5. Shape fills (any shape can have an image fill)
                elif hasattr(shape, 'fill'):
                    logger.debug(f"      -> Examining shape fill")
                    fill_images = self._extract_images_from_fill(shape.fill, slide_idx, shape_id, slide_context, shape_name)
                    images_from_shape.extend(fill_images)
                    if fill_images:
                        logger.debug(f"      -> Extracted {len(fill_images)} images from shape fill")
                
                # 6. OLE objects and embedded content
                if hasattr(shape, '_element'):
                    logger.debug(f"      -> Examining XML element for embedded objects")
                    ole_images = self._extract_images_from_ole(shape._element, slide_idx, shape_id, slide_context, shape_name)
                    images_from_shape.extend(ole_images)
                    if ole_images:
                        logger.debug(f"      -> Extracted {len(ole_images)} images from OLE objects")
                
                image_infos.extend(images_from_shape)
                
                if images_from_shape:
                    logger.debug(f"    Total images from shape {shape_id}: {len(images_from_shape)}")
                
            except Exception as e:
                logger.warning(f"Error processing shape {shape_idx} on slide {slide_idx}: {e}")
                continue
        
        return image_infos
    
    def _extract_images_from_chart(self, chart, slide_idx: int, shape_id: str, slide_context: str) -> List[PPTXImageInfo]:
        """
        Extract images from chart elements (chart backgrounds, data point images, etc.).
        
        Args:
            chart: Chart object
            slide_idx: Slide index
            shape_id: Shape identifier
            slide_context: Slide context text
            
        Returns:
            List of PPTXImageInfo objects
        """
        images = []
        
        try:
            # Check chart plot area fill
            if hasattr(chart, 'plot_area') and hasattr(chart.plot_area, 'fill'):
                fill_images = self._extract_images_from_fill(
                    chart.plot_area.fill, slide_idx, f"{shape_id}_plot", slide_context, "chart_plot_area"
                )
                images.extend(fill_images)
            
            # Check chart area fill
            if hasattr(chart, 'chart_area') and hasattr(chart.chart_area, 'fill'):
                fill_images = self._extract_images_from_fill(
                    chart.chart_area.fill, slide_idx, f"{shape_id}_area", slide_context, "chart_area"
                )
                images.extend(fill_images)
            
            # Check series fills (data points might have image fills)
            if hasattr(chart, 'series'):
                for series_idx, series in enumerate(chart.series):
                    if hasattr(series, 'fill'):
                        fill_images = self._extract_images_from_fill(
                            series.fill, slide_idx, f"{shape_id}_series_{series_idx}", 
                            slide_context, f"chart_series_{series_idx}"
                        )
                        images.extend(fill_images)
            
        except Exception as e:
            logger.debug(f"Error extracting images from chart: {e}")
        
        return images
    
    def _extract_images_from_fill(self, fill, slide_idx: int, shape_id: str, slide_context: str, source_name: str) -> List[PPTXImageInfo]:
        """
        Extract images from fill objects (picture fills, texture fills, etc.).
        
        Args:
            fill: Fill object
            slide_idx: Slide index
            shape_id: Shape identifier
            slide_context: Slide context text
            source_name: Name describing the source of this fill
            
        Returns:
            List of PPTXImageInfo objects
        """
        images = []
        
        try:
            # Check if this is a picture fill
            if hasattr(fill, 'type') and fill.type is not None:
                # Import fill type constants
                from pptx.dml.fill import MSO_FILL_TYPE
                
                if fill.type == MSO_FILL_TYPE.PICTURE:
                    logger.debug(f"        -> Found picture fill in {source_name}")
                    
                    # Try to extract image data from picture fill
                    if hasattr(fill, '_fill') and hasattr(fill._fill, 'blipFill'):
                        blip_fill = fill._fill.blipFill
                        if hasattr(blip_fill, 'blip') and hasattr(blip_fill.blip, 'rId'):
                            # This indicates there's an image, but we need to get the actual data
                            # For now, create a placeholder entry - the actual extraction would need
                            # access to the presentation's part relationships
                            logger.debug(f"        -> Picture fill found but data extraction needs relationship resolution")
                            
                            # Create a minimal image info to track this image
                            # Note: We can't create a full PPTXImageInfo without actual image data
                            # This is a limitation that would need deeper PPTX internals access
                            pass
                
        except Exception as e:
            logger.debug(f"Error extracting images from fill: {e}")
        
        return images
    
    def _extract_images_from_ole(self, element, slide_idx: int, shape_id: str, slide_context: str, source_name: str) -> List[PPTXImageInfo]:
        """
        Extract images from OLE objects and other embedded content.
        
        Args:
            element: XML element
            slide_idx: Slide index
            shape_id: Shape identifier
            slide_context: Slide context text
            source_name: Name describing the source
            
        Returns:
            List of PPTXImageInfo objects
        """
        images = []
        
        try:
            # Look for embedded objects in the XML
            # This would require parsing the XML structure for oleObj elements
            # and embedded image relationships
            
            # Check for oleObj elements
            ole_objects = element.xpath('.//p:oleObj', namespaces=element.nsmap) if element.nsmap else []
            if ole_objects:
                logger.debug(f"        -> Found {len(ole_objects)} OLE objects in {source_name}")
                # OLE object image extraction would require access to embedded parts
            
            # Check for embedded pictures in alternative locations
            embedded_pics = element.xpath('.//pic:pic', namespaces=element.nsmap) if element.nsmap else []
            if embedded_pics:
                logger.debug(f"        -> Found {len(embedded_pics)} embedded pictures in {source_name}")
            
        except Exception as e:
            logger.debug(f"Error extracting images from OLE: {e}")
        
        return images
    
    def _enumerate_all_shapes(self, shapes, indent: str = ""):
        """
        Recursively enumerate and log detailed information about all shapes.
        
        Args:
            shapes: Collection of shapes to enumerate
            indent: Indentation string for nested shapes
        """
        for i, shape in enumerate(shapes):
            try:
                # Get shape type information
                shape_type_name = "unknown"
                shape_type_value = getattr(shape, 'shape_type', None)
                
                # Try to get MSO shape type name
                try:
                    from pptx.enum.shapes import MSO_SHAPE_TYPE
                    if shape_type_value is not None:
                        # Find the name of the shape type enum
                        for attr_name in dir(MSO_SHAPE_TYPE):
                            if not attr_name.startswith('_') and getattr(MSO_SHAPE_TYPE, attr_name) == shape_type_value:
                                shape_type_name = attr_name
                                break
                        else:
                            shape_type_name = f"MSO_SHAPE_TYPE({shape_type_value})"
                except ImportError:
                    shape_type_name = str(shape_type_value) if shape_type_value is not None else "unknown"
                
                # Collect shape properties
                properties = []
                
                # Basic properties
                shape_name = getattr(shape, 'name', 'unnamed')
                if shape_name and shape_name != 'unnamed':
                    properties.append(f"name='{shape_name}'")
                
                # Dimensions if available
                if hasattr(shape, 'width') and hasattr(shape, 'height'):
                    try:
                        width_px = int(shape.width.emu / 914400 * 96) if shape.width else 0
                        height_px = int(shape.height.emu / 914400 * 96) if shape.height else 0
                        properties.append(f"size={width_px}x{height_px}px")
                    except:
                        pass
                
                # Check for image content
                has_image = hasattr(shape, 'image') and shape.image
                if has_image:
                    properties.append("HAS_IMAGE")
                
                # Check for chart content
                has_chart = hasattr(shape, 'chart')
                if has_chart:
                    properties.append("HAS_CHART")
                
                # Check for grouped shapes
                has_shapes = hasattr(shape, 'shapes')
                if has_shapes:
                    child_count = len(shape.shapes) if shape.shapes else 0
                    properties.append(f"GROUP({child_count})")
                
                # Check for text content
                has_text = hasattr(shape, 'text') and shape.text
                if has_text:
                    text_preview = shape.text.strip()[:30].replace('\n', ' ')
                    properties.append(f"text='{text_preview}...'")
                
                # Check for fill
                has_fill = hasattr(shape, 'fill')
                if has_fill:
                    try:
                        fill_type = getattr(shape.fill, 'type', None)
                        if fill_type is not None:
                            from pptx.dml.fill import MSO_FILL_TYPE
                            if fill_type == MSO_FILL_TYPE.PICTURE:
                                properties.append("PICTURE_FILL")
                            elif fill_type == MSO_FILL_TYPE.TEXTURED:
                                properties.append("TEXTURE_FILL")
                            else:
                                properties.append(f"fill_type={fill_type}")
                    except:
                        properties.append("FILL")
                
                # Log the shape information
                props_str = f" [{', '.join(properties)}]" if properties else ""
                logger.debug(f"{indent}Shape {i}: {type(shape).__name__} ({shape_type_name}){props_str}")
                
                # Recursively enumerate grouped shapes
                if has_shapes and shape.shapes:
                    logger.debug(f"{indent}  Group contents:")
                    self._enumerate_all_shapes(shape.shapes, indent + "    ")
                
            except Exception as e:
                logger.debug(f"{indent}Shape {i}: Error enumerating - {e}")
    
    def _extract_images_from_relationships(self, presentation: Presentation) -> List[PPTXImageInfo]:
        """
        Extract images by directly parsing presentation relationships and parts.
        This can find images that aren't accessible through the normal shape API.
        
        Args:
            presentation: Presentation object
            
        Returns:
            List of PPTXImageInfo objects
        """
        images = []
        
        try:
            # Access the presentation part and its relationships
            prs_part = presentation.part
            
            # Get all image parts from relationships
            image_parts = []
            for relationship in prs_part.rels.values():
                if hasattr(relationship, 'target_part'):
                    target = relationship.target_part
                    # Check if this is an image part
                    if hasattr(target, 'content_type') and target.content_type.startswith('image/'):
                        image_parts.append((relationship.rId, target))
            
            logger.debug(f"Found {len(image_parts)} image parts in presentation relationships")
            
            # Also check slide-level relationships
            for slide_idx, slide in enumerate(presentation.slides):
                try:
                    slide_part = slide.part
                    for relationship in slide_part.rels.values():
                        if hasattr(relationship, 'target_part'):
                            target = relationship.target_part
                            if hasattr(target, 'content_type') and target.content_type.startswith('image/'):
                                image_parts.append((f"slide_{slide_idx}_{relationship.rId}", target))
                except Exception as e:
                    logger.debug(f"Error checking slide {slide_idx} relationships: {e}")
            
            logger.debug(f"Total image parts found: {len(image_parts)}")
            
            # Create image info objects for relationship-based images
            # Note: These won't have shape context, but they represent actual images in the file
            for rel_id, image_part in image_parts:
                try:
                    image_data = image_part.blob
                    filename = getattr(image_part, 'partname', f'relationship_{rel_id}.png')
                    
                    # Create a minimal image info - we don't have shape context for these
                    logger.debug(f"Found relationship image: {filename} ({len(image_data)} bytes)")
                    
                except Exception as e:
                    logger.debug(f"Error extracting image from relationship {rel_id}: {e}")
        
        except Exception as e:
            logger.debug(f"Error extracting images from relationships: {e}")
        
        return images
    
    def detect_decorative_shapes(self, presentation: Presentation, debug: bool = False) -> List[PPTXShapeInfo]:
        """
        Detect decorative shapes (basic geometric shapes without meaningful content) in PPTX.
        
        Args:
            presentation: PowerPoint presentation
            debug: Enable debug logging
            
        Returns:
            List of PPTXShapeInfo objects representing decorative shapes
        """
        decorative_shapes = []
        
        # Define decorative shape types (basic geometric shapes)
        # Note: Many geometric shapes appear as AUTO_SHAPE in python-pptx
        decorative_shape_types = {
            MSO_SHAPE_TYPE.AUTO_SHAPE,    # Most geometric shapes (rectangles, ovals, etc.)
            MSO_SHAPE_TYPE.LINE,          # Lines
            MSO_SHAPE_TYPE.FREEFORM,      # Freeform drawings
            MSO_SHAPE_TYPE.CALLOUT,       # Callout shapes
            MSO_SHAPE_TYPE.TEXT_EFFECT    # WordArt/text effects (often decorative)
        }
        
        for slide_idx, slide in enumerate(presentation.slides):
            if debug:
                logger.info(f"🔍 DEBUG: Scanning slide {slide_idx + 1} for decorative shapes")
            
            # Extract slide text for context
            slide_text = self._extract_slide_text(slide) if self.include_slide_text else ""
            
            # Process all shapes recursively
            decorative_on_slide = self._detect_decorative_shapes_recursive(
                slide.shapes, slide_idx, slide_text, decorative_shape_types, debug
            )
            
            decorative_shapes.extend(decorative_on_slide)
            
            if debug and decorative_on_slide:
                logger.info(f"🔍 DEBUG: Found {len(decorative_on_slide)} decorative shapes on slide {slide_idx + 1}")
        
        logger.info(f"Detected {len(decorative_shapes)} potentially decorative shapes")
        return decorative_shapes
    
    def _detect_decorative_shapes_recursive(self, shapes, slide_idx: int, slide_text: str, 
                                          decorative_types: set, debug: bool = False, 
                                          parent_group_idx: str = None) -> List[PPTXShapeInfo]:
        """
        Recursively detect decorative shapes, including those in groups.
        
        Args:
            shapes: Collection of shapes to process
            slide_idx: Slide index
            slide_text: Slide text context
            decorative_types: Set of shape types considered potentially decorative
            debug: Enable debug logging
            parent_group_idx: Parent group identifier for nested shapes
            
        Returns:
            List of decorative PPTXShapeInfo objects
        """
        decorative_shapes = []
        
        for shape_idx, shape in enumerate(shapes):
            try:
                # Create hierarchical shape identifier
                if parent_group_idx is not None:
                    shape_id = f"{parent_group_idx}_{shape_idx}"
                else:
                    shape_id = shape_idx
                
                # Skip images (handled separately)
                if hasattr(shape, 'image') and shape.image:
                    continue
                
                # Skip shapes that are grouped with meaningful content
                if hasattr(shape, 'shapes'):
                    # This is a group - recursively check its contents
                    if debug:
                        logger.debug(f"    Examining group shape {shape_id} with {len(shape.shapes)} children")
                    
                    group_decorative = self._detect_decorative_shapes_recursive(
                        shape.shapes, slide_idx, slide_text, decorative_types, debug, shape_id
                    )
                    
                    # Only mark the group as decorative if ALL its contents are decorative or empty
                    if self._is_group_decorative(shape, group_decorative, debug):
                        shape_info = PPTXShapeInfo(shape, slide_idx, shape_id, slide_text)
                        decorative_shapes.append(shape_info)
                        if debug:
                            logger.debug(f"    Marked group {shape_id} as decorative")
                    else:
                        # Add individual decorative shapes from within the group
                        decorative_shapes.extend(group_decorative)
                    
                    continue
                
                # Check if this shape type is potentially decorative
                try:
                    shape_type = getattr(shape, 'shape_type', None)
                    if shape_type is None:
                        if debug:
                            logger.debug(f"    Shape {shape_id} has no shape_type attribute")
                        continue
                    
                    if shape_type not in decorative_types:
                        if debug:
                            logger.debug(f"    Shape {shape_id} type {shape_type} not in decorative types")
                        continue
                except Exception as e:
                    if debug:
                        logger.debug(f"    Error getting shape type for {shape_id}: {e}")
                    continue
                
                # Create shape info for analysis
                try:
                    shape_info = PPTXShapeInfo(shape, slide_idx, shape_id, slide_text)
                    
                    if debug:
                        logger.debug(f"    Analyzing shape {shape_id}: {shape_info.shape_type_name} "
                                   f"({shape_info.width_px}x{shape_info.height_px}px)")
                    
                    # Apply decorative detection heuristics
                    if self._is_shape_decorative(shape_info, debug):
                        decorative_shapes.append(shape_info)
                        if debug:
                            logger.debug(f"    ✅ Marked shape {shape_id} as decorative")
                    elif debug:
                        logger.debug(f"    ❌ Shape {shape_id} has meaningful content")
                
                except Exception as e:
                    logger.warning(f"Error creating shape info for {shape_id}: {e}")
                    if debug:
                        logger.debug(f"    Skipping shape {shape_id} due to creation error")
                    continue
                
            except Exception as e:
                logger.warning(f"Error analyzing shape {shape_idx} on slide {slide_idx}: {e}")
                continue
        
        return decorative_shapes
    
    def _is_shape_decorative(self, shape_info: PPTXShapeInfo, debug: bool = False) -> bool:
        """
        Determine if a shape is decorative based on heuristics.
        
        Args:
            shape_info: Shape information
            debug: Enable debug logging
            
        Returns:
            bool: True if shape appears to be decorative
        """
        # Rule 1: Shapes with meaningful text content are not decorative
        if shape_info.has_text and len(shape_info.text_content) > 2:
            if debug:
                logger.debug(f"      Rule 1: Has text content: '{shape_info.text_content[:30]}...'")
            return False
        
        # Rule 2: Very small shapes are likely decorative (bullets, dividers, etc.)
        min_dimension = min(shape_info.width_px, shape_info.height_px)
        if min_dimension < self.decorative_size_threshold:
            if debug:
                logger.debug(f"      Rule 2: Very small shape ({min_dimension}px < {self.decorative_size_threshold}px)")
            return True
        
        # Rule 3: Lines are typically decorative unless they have text
        if shape_info.shape_type == MSO_SHAPE_TYPE.LINE:
            if debug:
                logger.debug(f"      Rule 3: Line shape")
            return True
        
        # Rule 4: Auto shapes without text are often decorative (includes rectangles, ovals, etc.)
        if shape_info.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and not shape_info.has_text:
            # Additional check: if the shape is large, it might be a background element
            max_dimension = max(shape_info.width_px, shape_info.height_px)
            if max_dimension > 200:  # Large background elements
                if debug:
                    logger.debug(f"      Rule 4a: Large auto shape background element ({max_dimension}px)")
                return True
            elif min_dimension < 100:  # Small geometric decorations
                if debug:
                    logger.debug(f"      Rule 4b: Small auto shape decoration ({min_dimension}px)")
                return True
        
        # Rule 5: Callouts without text are often decorative
        if shape_info.shape_type == MSO_SHAPE_TYPE.CALLOUT and not shape_info.has_text:
            if debug:
                logger.debug(f"      Rule 5: Callout without text")
            return True
        
        # Rule 6: Text effects are often decorative WordArt
        if shape_info.shape_type == MSO_SHAPE_TYPE.TEXT_EFFECT:
            if debug:
                logger.debug(f"      Rule 6: Text effect/WordArt shape")
            return True
        
        # Rule 7: Freeform shapes are often decorative drawings
        if shape_info.shape_type == MSO_SHAPE_TYPE.FREEFORM:
            if debug:
                logger.debug(f"      Rule 7: Freeform drawing shape")
            return True
        
        # Default: not decorative
        if debug:
            logger.debug(f"      No decorative rules matched - shape has content")
        return False
    
    def _is_group_decorative(self, group_shape, group_decorative_shapes: List[PPTXShapeInfo], debug: bool = False) -> bool:
        """
        Determine if an entire group should be marked as decorative.
        
        Args:
            group_shape: The group shape object
            group_decorative_shapes: List of decorative shapes found within the group
            debug: Enable debug logging
            
        Returns:
            bool: True if the entire group should be marked as decorative
        """
        try:
            total_shapes_in_group = len(group_shape.shapes)
            decorative_shapes_in_group = len(group_decorative_shapes)
            
            if debug:
                logger.debug(f"      Group analysis: {decorative_shapes_in_group}/{total_shapes_in_group} shapes are decorative")
            
            # If all shapes in the group are decorative, mark the whole group as decorative
            if total_shapes_in_group > 0 and decorative_shapes_in_group == total_shapes_in_group:
                return True
            
            # If the group is mostly decorative (80%+) and small, consider it decorative
            if total_shapes_in_group > 0:
                decorative_ratio = decorative_shapes_in_group / total_shapes_in_group
                if decorative_ratio >= 0.8 and total_shapes_in_group <= 5:
                    if debug:
                        logger.debug(f"      Group is {decorative_ratio:.1%} decorative with {total_shapes_in_group} shapes")
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error analyzing group decorativeness: {e}")
            return False
    
    def set_decorative_flag(self, decorative_shapes: List[PPTXShapeInfo], debug: bool = False) -> int:
        """
        Mark shapes as decorative in the PPTX XML structure using Office 2019+ decorative attribute.
        
        Args:
            decorative_shapes: List of shapes to mark as decorative
            debug: Enable debug logging
            
        Returns:
            int: Number of shapes successfully marked as decorative
        """
        marked_count = 0
        
        # Register decorative namespace if not already done
        try:
            _nsmap["adec"] = "http://schemas.microsoft.com/office/drawing/2017/decorative"
        except:
            pass  # May already be registered
        
        for shape_info in decorative_shapes:
            try:
                if debug:
                    logger.debug(f"🔍 DEBUG: Setting decorative flag for {shape_info.shape_key}")
                
                success = self._set_shape_decorative_xml(shape_info.shape, debug)
                
                if success:
                    marked_count += 1
                    if debug:
                        logger.debug(f"    ✅ Successfully marked {shape_info.shape_key} as decorative")
                else:
                    logger.warning(f"Failed to mark shape as decorative: {shape_info.shape_key} "
                                 f"(type: {shape_info.shape_type_name}, size: {shape_info.width_px}x{shape_info.height_px}px)")
                    if debug:
                        logger.debug(f"    ❌ XML marking failed for {shape_info.shape_key}")
                        # Try to provide more diagnostic info
                        if hasattr(shape_info.shape, '_element'):
                            logger.debug(f"    Shape has _element: {shape_info.shape._element}")
                            logger.debug(f"    Element tag: {getattr(shape_info.shape._element, 'tag', 'no_tag')}")
                        else:
                            logger.debug(f"    Shape has no _element attribute")
                
            except Exception as e:
                logger.warning(f"Error setting decorative flag for {shape_info.shape_key}: {e}")
                continue
        
        logger.info(f"Successfully marked {marked_count}/{len(decorative_shapes)} shapes as decorative")
        return marked_count
    
    def _set_shape_decorative_xml(self, shape: BaseShape, debug: bool = False) -> bool:
        """
        Set the decorative attribute in the shape's XML structure.
        
        Args:
            shape: Shape to mark as decorative
            debug: Enable debug logging
            
        Returns:
            bool: True if successfully set
        """
        success_methods = []
        
        try:
            # Method 1: Try to set decorative attribute on cNvPr element
            if hasattr(shape, '_element') and shape._element is not None:
                element = shape._element
                
                # Find the cNvPr (non-visual properties) element with multiple namespace tries
                cnvpr_elements = []
                try:
                    cnvpr_elements = element.xpath('.//p:cNvPr | .//pic:cNvPr | .//a:cNvPr',
                                                 namespaces={
                                                     'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
                                                     'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
                                                     'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'
                                                 })
                except Exception as xpath_error:
                    if debug:
                        logger.debug(f"      XPath query failed: {xpath_error}")
                
                if cnvpr_elements:
                    for i, cnvpr in enumerate(cnvpr_elements):
                        try:
                            # Set the decorative attribute (Office 2019+ feature)
                            decorative_attr = '{http://schemas.microsoft.com/office/drawing/2017/decorative}decorative'
                            cnvpr.set(decorative_attr, '1')
                            success_methods.append(f"cNvPr_element_{i}")
                            
                            if debug:
                                logger.debug(f"      Set decorative='1' on cNvPr element {i}")
                        except Exception as cnvpr_error:
                            if debug:
                                logger.debug(f"      Failed to set decorative on cNvPr {i}: {cnvpr_error}")
                
                # Method 2: Try alternative XML approaches
                try:
                    # Try setting decorative directly on the shape element
                    decorative_attr = '{http://schemas.microsoft.com/office/drawing/2017/decorative}decorative'
                    element.set(decorative_attr, '1')
                    success_methods.append("shape_element")
                    
                    if debug:
                        logger.debug(f"      Set decorative='1' on shape element")
                except Exception as element_error:
                    if debug:
                        logger.debug(f"      Failed to set decorative on shape element: {element_error}")
                
                # Method 3: Fallback - set a custom attribute for tracking
                try:
                    # Set a custom attribute that can be used for identification
                    custom_attr = '{http://schemas.anthropic.com/accessibility/2024}decorative'
                    element.set(custom_attr, '1')
                    success_methods.append("custom_fallback")
                    
                    if debug:
                        logger.debug(f"      Set custom decorative attribute as fallback")
                except Exception as custom_error:
                    if debug:
                        logger.debug(f"      Failed to set custom decorative attribute: {custom_error}")
                
                # Method 4: Try setting ALT text to empty (accessibility best practice for decorative)
                if cnvpr_elements:
                    for i, cnvpr in enumerate(cnvpr_elements):
                        try:
                            cnvpr.set('descr', '')  # Empty ALT text for decorative images
                            success_methods.append(f"empty_alt_text_{i}")
                            
                            if debug:
                                logger.debug(f"      Set empty ALT text on cNvPr element {i} as fallback")
                        except Exception as alt_error:
                            if debug:
                                logger.debug(f"      Failed to set empty ALT text on cNvPr {i}: {alt_error}")
            
            # If we had any success, return True
            if success_methods:
                if debug:
                    logger.debug(f"      Decorative marking succeeded via: {', '.join(success_methods)}")
                return True
            
            if debug:
                logger.debug(f"      No suitable XML element found for decorative marking")
            return False
            
        except Exception as e:
            if debug:
                logger.debug(f"      Error in decorative XML marking: {e}")
            return len(success_methods) > 0  # Return True if we had any success before the error
    
    def _count_all_shapes(self, presentation: Presentation) -> Tuple[int, int]:
        """
        Count total shapes and shapes with text content for coverage reporting.
        
        Args:
            presentation: PowerPoint presentation
            
        Returns:
            Tuple of (total_shapes, shapes_with_content)
        """
        total_shapes = 0
        shapes_with_content = 0
        
        for slide in presentation.slides:
            shapes_on_slide, content_shapes_on_slide = self._count_shapes_recursive(slide.shapes)
            total_shapes += shapes_on_slide
            shapes_with_content += content_shapes_on_slide
        
        return total_shapes, shapes_with_content
    
    def _count_shapes_recursive(self, shapes) -> Tuple[int, int]:
        """
        Recursively count shapes and those with meaningful content.
        
        Args:
            shapes: Collection of shapes to count
            
        Returns:
            Tuple of (total_shapes, shapes_with_content)
        """
        total_shapes = 0
        shapes_with_content = 0
        
        for shape in shapes:
            # Skip images (counted separately)
            if hasattr(shape, 'image') and shape.image:
                continue
            
            total_shapes += 1
            
            # Check if shape has meaningful content
            has_text = hasattr(shape, 'text') and shape.text and shape.text.strip()
            if has_text and len(shape.text.strip()) > 2:
                shapes_with_content += 1
            
            # Recursively count grouped shapes
            if hasattr(shape, 'shapes'):
                group_total, group_content = self._count_shapes_recursive(shape.shapes)
                total_shapes += group_total
                shapes_with_content += group_content
        
        return total_shapes, shapes_with_content
    
    def _extract_slide_text(self, slide) -> str:
        """Extract all text content from a slide."""
        text_parts = []
        
        for shape in slide.shapes:
            if hasattr(shape, 'text') and shape.text:
                text_parts.append(shape.text.strip())
        
        return " ".join(text_parts)
    
    def _extract_slide_notes(self, slide) -> str:
        """Extract notes from a slide."""
        try:
            if slide.notes_slide and slide.notes_slide.notes_text_frame:
                notes_text = slide.notes_slide.notes_text_frame.text
                return notes_text.strip()
        except Exception as e:
            logger.debug(f"Failed to extract slide notes: {e}")
        
        return ""
    
    def _should_generate_alt_text(self, image_info: PPTXImageInfo, 
                                 image_tracker: defaultdict) -> bool:
        """
        Determine if ALT text should be generated for an image using existing decorative detection.
        
        Args:
            image_info: Image information
            image_tracker: Dictionary tracking image occurrences
            
        Returns:
            bool: True if ALT text should be generated
        """
        # Check configuration-based decorative rules first
        if is_force_decorative_by_filename(image_info.filename, self.config_manager.config):
            logger.debug(f"Image marked as decorative by config rules: {image_info.filename}")
            return False
        
        # Check if decorative detection is disabled
        if not self.skip_decorative:
            return True
        
        # Use the existing heuristic-based decorative detection
        position = (image_info.left_px, image_info.top_px)
        dimensions = (image_info.width_px, image_info.height_px)
        slide_shapes = []  # Not used by current heuristics
        
        is_decorative, notes = is_decorative_image(
            image_bytes=image_info.image_data,
            image_name=image_info.filename,
            position=position,
            dimensions=dimensions,
            slide_shapes=slide_shapes,
            image_hash=image_info.image_hash,
            image_tracker=image_tracker
        )
        
        if is_decorative:
            logger.debug(f"Image marked as decorative by heuristics: {image_info.filename} - {', '.join(notes)}")
            return False
        
        return True
    
    def _generate_alt_text_for_image(self, image_info: PPTXImageInfo) -> Optional[str]:
        """
        Generate ALT text for a single image using the existing ALT text generator.
        
        Args:
            image_info: Image information
            
        Returns:
            Generated ALT text or None if generation failed
        """
        try:
            # Save image to temporary file for ALT text generation
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                temp_file.write(image_info.image_data)
                temp_image_path = temp_file.name
            
            try:
                # Build context for better ALT text generation
                context = self._build_generation_context(image_info)
                
                # Determine appropriate prompt type based on content
                prompt_type = self._determine_prompt_type(image_info)
                
                # Generate ALT text using the configured generator
                alt_text = self.alt_generator.generate_alt_text(
                    image_path=temp_image_path,
                    prompt_type=prompt_type,
                    context=context
                )
                
                return alt_text
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_image_path)
                except OSError:
                    pass  # File cleanup failure is not critical
        
        except Exception as e:
            logger.error(f"Failed to generate ALT text for {image_info.image_key}: {e}")
            return None
    
    def _generate_alt_text_for_image_with_validation(self, image_info: PPTXImageInfo, debug: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate ALT text with comprehensive validation and detailed failure tracking.
        
        Args:
            image_info: Image information
            debug: Whether to enable debug logging
            
        Returns:
            Tuple of (alt_text, failure_reason). If alt_text is None/empty, failure_reason explains why.
        """
        failure_reason = None
        
        try:
            # Save image to temporary file for ALT text generation
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                temp_file.write(image_info.image_data)
                temp_image_path = temp_file.name
            
            try:
                # Build context for better ALT text generation
                context = self._build_generation_context(image_info)
                
                # Determine appropriate prompt type based on content
                prompt_type = self._determine_prompt_type(image_info)
                
                if debug:
                    logger.info(f"🔍 DEBUG: Using prompt type '{prompt_type}' with context: {context[:100]}...")
                
                # Generate ALT text using the configured generator
                alt_text = self.alt_generator.generate_alt_text(
                    image_path=temp_image_path,
                    prompt_type=prompt_type,
                    context=context
                )
                
                # Comprehensive validation of the generated ALT text
                if alt_text is None:
                    failure_reason = "Generator returned None"
                    return None, failure_reason
                
                if not isinstance(alt_text, str):
                    failure_reason = f"Generator returned non-string type: {type(alt_text)}"
                    return None, failure_reason
                
                alt_text_stripped = alt_text.strip()
                if not alt_text_stripped:
                    failure_reason = "Generator returned empty or whitespace-only string"
                    return None, failure_reason
                
                if len(alt_text_stripped) < 3:
                    failure_reason = f"Generator returned very short ALT text: '{alt_text_stripped}'"
                    return None, failure_reason
                
                # Check for common failure patterns
                failure_patterns = [
                    'error', 'failed', 'cannot', 'unable', 'sorry', 
                    'i cannot', 'i am unable', 'no description',
                    'not available', 'description not available'
                ]
                
                alt_text_lower = alt_text_stripped.lower()
                for pattern in failure_patterns:
                    if pattern in alt_text_lower:
                        failure_reason = f"Generator returned failure message containing '{pattern}'"
                        return None, failure_reason
                
                # ALT text passed all validation checks
                if debug:
                    logger.info(f"✅ DEBUG: Generated valid ALT text: '{alt_text_stripped[:50]}...'")
                
                return alt_text_stripped, None
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_image_path)
                except OSError:
                    pass  # File cleanup failure is not critical
        
        except Exception as e:
            failure_reason = f"Exception during generation: {str(e)}"
            if debug:
                logger.error(f"💥 DEBUG: Exception in ALT text generation: {e}", exc_info=True)
            return None, failure_reason
    
    def _build_generation_context(self, image_info: PPTXImageInfo) -> Optional[str]:
        """
        Build context string for ALT text generation.
        
        Args:
            image_info: Image information
            
        Returns:
            Context string or None
        """
        context_parts = []
        
        # Add slide text context
        if image_info.slide_text:
            context_parts.append(f"Slide content: {image_info.slide_text}")
        
        # Add slide number
        context_parts.append(f"Slide {image_info.slide_idx + 1}")
        
        # Add image filename if it provides context
        if image_info.filename and not image_info.filename.startswith('slide_'):
            context_parts.append(f"File: {image_info.filename}")
        
        return ". ".join(context_parts) if context_parts else None
    
    def _determine_prompt_type(self, image_info: PPTXImageInfo) -> str:
        """
        Determine the appropriate prompt type based on image and context.
        
        Args:
            image_info: Image information
            
        Returns:
            Prompt type string
        """
        # Check filename and context for medical content indicators
        text_to_check = (image_info.filename + " " + image_info.slide_text).lower()
        
        # Medical-specific prompt detection
        anatomical_keywords = ['anatomy', 'organ', 'body', 'muscle', 'bone', 'tissue']
        diagnostic_keywords = ['xray', 'x-ray', 'ct', 'mri', 'ultrasound', 'scan', 'radiograph']
        clinical_keywords = ['patient', 'clinical', 'medical', 'surgery', 'procedure', 'treatment']
        chart_keywords = ['chart', 'graph', 'data', 'results', 'statistics', 'plot']
        diagram_keywords = ['diagram', 'flowchart', 'process', 'workflow', 'schematic']
        
        if any(keyword in text_to_check for keyword in anatomical_keywords):
            return 'anatomical'
        elif any(keyword in text_to_check for keyword in diagnostic_keywords):
            return 'diagnostic'
        elif any(keyword in text_to_check for keyword in clinical_keywords):
            return 'clinical_photo'
        elif any(keyword in text_to_check for keyword in chart_keywords):
            return 'chart'
        elif any(keyword in text_to_check for keyword in diagram_keywords):
            return 'diagram'
        else:
            # Check if this appears to be medical content in general
            medical_keywords = ['medical', 'health', 'doctor', 'hospital', 'clinic']
            if any(keyword in text_to_check for keyword in medical_keywords):
                return 'unified_medical'
        
        return 'default'
    
    def _validate_complete_coverage(self, image_infos: List[PPTXImageInfo], alt_text_mapping: Dict[str, Any], 
                                  force_decorative: bool = False, debug: bool = False) -> Dict[str, Any]:
        """
        Validate that every image has ALT text (either real or decorative fallback).
        
        Args:
            image_infos: List of all images found in the PPTX
            alt_text_mapping: Current ALT text mappings
            force_decorative: Whether decorative fallback was enabled
            debug: Whether to enable debug logging
            
        Returns:
            Dictionary with validation results
        """
        total_images = len(image_infos)
        covered_images = len(alt_text_mapping)
        missing_images = []
        
        # Check each image has ALT text
        for image_info in image_infos:
            if image_info.image_key not in alt_text_mapping:
                missing_images.append(image_info.image_key)
        
        missing_count = len(missing_images)
        coverage_percent = (covered_images / total_images * 100) if total_images > 0 else 0
        complete_coverage = missing_count == 0
        
        # Count ALT text types
        descriptive_count = 0
        decorative_count = 0
        
        for key, info in alt_text_mapping.items():
            alt_text = info['alt_text']
            if alt_text == '[Decorative image]':
                decorative_count += 1
            else:
                descriptive_count += 1
        
        validation_result = {
            'complete_coverage': complete_coverage,
            'total_images': total_images,
            'covered_images': covered_images,
            'missing_count': missing_count,
            'missing_images': missing_images,
            'descriptive_count': descriptive_count,
            'decorative_count': decorative_count,
            'total_coverage_percent': coverage_percent
        }
        
        if debug:
            logger.info(f"🔍 DEBUG: Coverage validation results:")
            logger.info(f"   Total images: {total_images}")
            logger.info(f"   Images with ALT text: {covered_images}")
            logger.info(f"   Descriptive ALT text: {descriptive_count}")
            logger.info(f"   Decorative ALT text: {decorative_count}")
            logger.info(f"   Missing ALT text: {missing_count}")
            logger.info(f"   Coverage: {coverage_percent:.1f}%")
            
            if missing_count > 0:
                logger.warning(f"❌ DEBUG: {missing_count} images missing ALT text:")
                for missing_key in missing_images[:5]:  # Show first 5
                    logger.warning(f"   - {missing_key}")
                if len(missing_images) > 5:
                    logger.warning(f"   ... and {len(missing_images) - 5} more")
        
        # Log validation summary
        if complete_coverage:
            logger.info(f"✅ Complete ALT text coverage achieved: {covered_images}/{total_images} images")
            logger.info(f"   Descriptive: {descriptive_count}, Decorative: {decorative_count}")
        else:
            logger.error(f"❌ Incomplete ALT text coverage: {covered_images}/{total_images} images ({coverage_percent:.1f}%)")
            logger.error(f"   Missing ALT text for {missing_count} images")
            if not force_decorative:
                logger.error("   💡 Consider using --force-decorative to ensure 100% coverage")
        
        return validation_result
    
    def _inject_alt_text_to_pptx(self, presentation: Presentation, 
                               alt_text_mapping: Dict[str, Any], output_path: str, debug: bool = False) -> bool:
        """
        Inject ALT text into PPTX presentation using the dedicated injector.
        
        Args:
            presentation: Presentation object
            alt_text_mapping: Mapping of image keys to ALT text and shape info
            output_path: Path to save modified PPTX
            
        Returns:
            bool: True if injection succeeded
        """
        try:
            # Import the dedicated ALT text injector
            from pptx_alt_injector import PPTXAltTextInjector
            
            # Create injector instance
            injector = PPTXAltTextInjector(self.config_manager)
            
            # Convert mapping format to match injector expectations
            simple_mapping = {}
            logger.debug("Converting ALT text mapping from processor format:")
            for image_key, info in alt_text_mapping.items():
                simple_mapping[image_key] = info['alt_text']
                logger.debug(f"  Processor key: {image_key} -> ALT: '{info['alt_text'][:50]}...'")
            
            logger.debug(f"Created simple mapping with {len(simple_mapping)} entries for injector")
            
            # Save presentation to temp file for injector processing
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as temp_file:
                temp_path = temp_file.name
            
            presentation.save(temp_path)
            
            # Use injector to perform robust ALT text injection
            result = injector.inject_alt_text_from_mapping(temp_path, simple_mapping, output_path)
            
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            
            # Log injector statistics
            stats = result['statistics']
            logger.info(f"ALT text injection via dedicated injector:")
            logger.info(f"  Successfully injected: {stats['injected_successfully']}")
            logger.info(f"  Skipped (existing): {stats['skipped_existing']}")
            logger.info(f"  Failed: {stats['failed_injection']}")
            
            return result['success']
            
        except Exception as e:
            logger.error(f"Failed to inject ALT text via dedicated injector: {e}")
            # Fallback to original simple method
            return self._inject_alt_text_simple(presentation, alt_text_mapping, output_path)
    
    def _inject_alt_text_simple(self, presentation: Presentation, 
                              alt_text_mapping: Dict[str, Any], output_path: str) -> bool:
        """
        Fallback simple ALT text injection method.
        
        Args:
            presentation: Presentation object
            alt_text_mapping: Mapping of image keys to ALT text and shape info
            output_path: Path to save modified PPTX
            
        Returns:
            bool: True if injection succeeded
        """
        try:
            logger.info(f"Using fallback injection method for {len(alt_text_mapping)} images")
            
            for image_key, info in alt_text_mapping.items():
                try:
                    shape = info['shape']
                    alt_text = info['alt_text']
                    
                    # Set ALT text on the shape
                    if hasattr(shape, '_element'):
                        # Access the underlying XML element and set the description
                        shape._element.set('descr', alt_text)
                        logger.debug(f"Set ALT text for {image_key}: {alt_text[:50]}...")
                    else:
                        logger.warning(f"Cannot set ALT text for {image_key}: shape has no _element")
                        
                except Exception as e:
                    logger.error(f"Failed to set ALT text for {image_key}: {e}")
                    continue
            
            # Save the modified presentation
            presentation.save(output_path)
            logger.info(f"Saved PPTX with ALT text to: {output_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Fallback ALT text injection failed: {e}")
            return False
    
    def _log_processing_summary(self, result: Dict[str, Any]):
        """Log a summary of the processing results."""
        logger.info("PPTX Processing Summary:")
        logger.info(f"  Input file: {result['input_file']}")
        logger.info(f"  Output file: {result['output_file']}")
        logger.info(f"  Total slides: {result['total_slides']}")
        
        # Image processing summary
        logger.info(f"  Total images found: {result['total_images']}")
        logger.info(f"  Images processed (descriptive): {result['processed_images']}")
        logger.info(f"  Decorative images (heuristic): {result['decorative_images']}")
        logger.info(f"  Decorative images (fallback): {result['fallback_decorative']}")
        logger.info(f"  Failed images: {result['failed_images']}")
        
        # Shape processing summary
        if 'total_shapes' in result:
            logger.info(f"  Total shapes found: {result['total_shapes']}")
            logger.info(f"  Shapes with content: {result.get('shapes_with_content', 0)}")
            logger.info(f"  Decorative shapes marked: {result.get('decorative_shapes_marked', 0)}")
        
        # Timing information
        logger.info(f"  Generation time: {result['generation_time']:.2f}s")
        logger.info(f"  Injection time: {result['injection_time']:.2f}s")
        if 'decorative_marking_time' in result:
            logger.info(f"  Decorative marking time: {result['decorative_marking_time']:.2f}s")
        logger.info(f"  Total processing time: {result['total_time']:.2f}s")
        logger.info(f"  Success: {result['success']}")
        
        # Calculate and log coverage
        total_covered = result['processed_images'] + result['decorative_images'] + result['fallback_decorative']
        coverage_percent = (total_covered / result['total_images'] * 100) if result['total_images'] > 0 else 0
        logger.info(f"  Image Coverage: {total_covered}/{result['total_images']} ({coverage_percent:.1f}%)")
        
        # Shape coverage if available
        if 'total_shapes' in result and result['total_shapes'] > 0:
            shape_coverage = (result.get('decorative_shapes_marked', 0) / result['total_shapes']) * 100
            logger.info(f"  Shape Coverage (decorative): {result.get('decorative_shapes_marked', 0)}/{result['total_shapes']} ({shape_coverage:.1f}%)")
        
        if result['errors']:
            logger.warning(f"Errors encountered: {len(result['errors'])}")
            for error in result['errors']:
                logger.warning(f"  - {error}")


def debug_image_extraction(pptx_path: str):
    """
    Debug function to test comprehensive image extraction with detailed logging.
    
    Args:
        pptx_path: Path to PPTX file to analyze
    """
    # Set up debug logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print(f"🔍 DEBUG MODE: Analyzing image extraction in {pptx_path}")
    print("=" * 80)
    
    try:
        # Initialize processor with debug enabled
        config_manager = ConfigManager()
        processor = PPTXAccessibilityProcessor(config_manager, debug=True)
        
        # Extract images with comprehensive logging
        presentation, image_infos = processor._extract_images_from_pptx(pptx_path)
        
        # Summary
        print("\n" + "=" * 80)
        print("🔍 DEBUG SUMMARY:")
        print(f"   Total slides: {len(presentation.slides)}")
        print(f"   Total images found: {len(image_infos)}")
        
        if image_infos:
            print("\n📋 Image Details:")
            for i, img_info in enumerate(image_infos, 1):
                print(f"   {i:2d}. {img_info.filename} ({img_info.width_px}x{img_info.height_px}px)")
                print(f"       Key: {img_info.image_key}")
                print(f"       Slide: {img_info.slide_idx + 1}, Shape: {img_info.shape_idx}")
                print(f"       Hash: {img_info.image_hash[:8]}...")
                if img_info.slide_text:
                    print(f"       Context: {img_info.slide_text[:60]}...")
                print()
        else:
            print("   ❌ No images were detected!")
            print("   Check the debug logs above to see what shapes were found.")
        
    except Exception as e:
        print(f"❌ Error during debug extraction: {e}")
        raise

def main():
    """Test the PPTX accessibility processor."""
    import sys
    
    # Check for debug flag
    debug_mode = '--debug' in sys.argv
    if debug_mode:
        sys.argv.remove('--debug')
    
    # Set up logging
    log_level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) not in [2, 3]:
        print("Usage: python pptx_processor.py [--debug] <pptx_file> [output_file]")
        print("\nOptions:")
        print("  --debug    Enable debug mode with comprehensive image extraction logging")
        print("\nThis will process a PPTX to add ALT text to images.")
        print("If output_file is not specified, the original file will be overwritten.")
        print("\nFor debugging image extraction issues, use --debug flag.")
        return
    
    pptx_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) == 3 else None
    
    # If debug mode is enabled, just run image extraction debugging
    if debug_mode:
        debug_image_extraction(pptx_path)
        return 0
    
    try:
        print("PPTX Accessibility Processor Test")
        print("=" * 50)
        print(f"Processing: {pptx_path}")
        if output_path:
            print(f"Output: {output_path}")
        else:
            print("Output: Overwriting original file")
        print()
        
        # Initialize processor
        config_manager = ConfigManager()
        processor = PPTXAccessibilityProcessor(config_manager)
        
        # Process PPTX
        result = processor.process_pptx(pptx_path, output_path)
        
        # Display results
        print("Processing Results:")
        print(f"  Success: {result['success']}")
        print(f"  Total slides: {result['total_slides']}")
        print(f"  Total images: {result['total_images']}")
        print(f"  Processed: {result['processed_images']}")
        print(f"  Decorative (skipped): {result['decorative_images']}")
        print(f"  Failed: {result['failed_images']}")
        
        # Show shape information if available
        if 'total_shapes' in result:
            print(f"  Total shapes: {result['total_shapes']}")
            print(f"  Decorative shapes marked: {result.get('decorative_shapes_marked', 0)}")
        
        print(f"  Total time: {result['total_time']:.2f}s")
        
        if result['errors']:
            print(f"  Errors: {len(result['errors'])}")
            for error in result['errors']:
                print(f"    - {error}")
        
        print()
        if result['success']:
            print("✅ PPTX processing completed successfully!")
            print(f"Modified PPTX saved to: {result['output_file']}")
        else:
            print("❌ PPTX processing failed!")
            return 1
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())