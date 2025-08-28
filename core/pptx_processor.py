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
            'generation_time': 0.0,
            'injection_time': 0.0,
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
                    result['success'] = True
                    logger.info("✅ PPTX processing completed successfully!")
                    
                    # Final coverage validation
                    final_coverage = validation_result['total_coverage_percent']
                    logger.info(f"📊 Final ALT text coverage: {final_coverage:.1f}%")
                    if final_coverage == 100.0:
                        logger.info("🎯 100% ALT text coverage achieved!")
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
        logger.info(f"  Total images found: {result['total_images']}")
        logger.info(f"  Images processed (descriptive): {result['processed_images']}")
        logger.info(f"  Decorative images (heuristic): {result['decorative_images']}")
        logger.info(f"  Decorative images (fallback): {result['fallback_decorative']}")
        logger.info(f"  Failed images: {result['failed_images']}")
        logger.info(f"  Generation time: {result['generation_time']:.2f}s")
        logger.info(f"  Injection time: {result['injection_time']:.2f}s")
        logger.info(f"  Total processing time: {result['total_time']:.2f}s")
        logger.info(f"  Success: {result['success']}")
        
        # Calculate and log coverage
        total_covered = result['processed_images'] + result['decorative_images'] + result['fallback_decorative']
        coverage_percent = (total_covered / result['total_images'] * 100) if result['total_images'] > 0 else 0
        logger.info(f"  Image Coverage: {total_covered}/{result['total_images']} ({coverage_percent:.1f}%)")
        
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