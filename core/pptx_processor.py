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
        
        # Unique identifier
        self.image_key = f"slide_{slide_idx}_shape_{shape_idx}"


class PPTXAccessibilityProcessor:
    """
    PPTX accessibility processor that integrates with the existing PDF ALT text system.
    Reuses ConfigManager, FlexibleAltGenerator, medical prompts, and decorative detection.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the PPTX accessibility processor.
        
        Args:
            config_manager: Optional ConfigManager instance. If None, creates a new one.
        """
        self.config_manager = config_manager or ConfigManager()
        
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
    
    def process_pptx(self, pptx_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a PPTX file to add ALT text to images.
        
        Args:
            pptx_path: Path to the input PPTX file
            output_path: Optional path for output file. If None, overwrites original.
            
        Returns:
            Dictionary with processing statistics
        """
        start_time = time.time()
        pptx_path = Path(pptx_path)
        
        # Initialize result structure
        result = {
            'success': False,
            'input_file': str(pptx_path),
            'output_file': '',
            'total_slides': 0,
            'total_images': 0,
            'processed_images': 0,
            'decorative_images': 0,
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
                try:
                    # Check if we should generate ALT text for this image
                    if not self._should_generate_alt_text(image_info, image_tracker):
                        logger.debug(f"Skipping decorative image: {image_info.image_key}")
                        result['decorative_images'] += 1
                        continue
                    
                    # Generate ALT text
                    alt_text = self._generate_alt_text_for_image(image_info)
                    
                    if alt_text:
                        alt_text_mapping[image_info.image_key] = {
                            'alt_text': alt_text,
                            'shape': image_info.shape,
                            'slide_idx': image_info.slide_idx,
                            'shape_idx': image_info.shape_idx
                        }
                        result['processed_images'] += 1
                        logger.info(f"Generated ALT text for {image_info.image_key}: {alt_text[:50]}...")
                    else:
                        result['failed_images'] += 1
                        error_msg = f"Failed to generate ALT text for {image_info.image_key}"
                        logger.warning(error_msg)
                        result['errors'].append(error_msg)
                
                except Exception as e:
                    result['failed_images'] += 1
                    error_msg = f"Error processing {image_info.image_key}: {str(e)}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
                    continue
            
            result['generation_time'] = time.time() - generation_start
            logger.info(f"ALT text generation completed in {result['generation_time']:.2f}s")
            
            # Step 3: Inject ALT text into PPTX
            if alt_text_mapping:
                logger.info("Step 3: Adding ALT text to PPTX...")
                injection_start = time.time()
                
                injection_success = self._inject_alt_text_to_pptx(
                    presentation, alt_text_mapping, str(output_path)
                )
                
                result['injection_time'] = time.time() - injection_start
                logger.info(f"ALT text injection completed in {result['injection_time']:.2f}s")
                
                if injection_success:
                    result['success'] = True
                    logger.info("✅ PPTX processing completed successfully!")
                else:
                    error_msg = "ALT text injection failed"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
            else:
                logger.info("No ALT text to inject - all images were decorative or failed generation")
                result['success'] = True  # Not an error condition
            
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
        Extract all images from PPTX with their context.
        
        Args:
            pptx_path: Path to PPTX file
            
        Returns:
            Tuple of (Presentation object, List of PPTXImageInfo objects)
        """
        presentation = Presentation(pptx_path)
        image_infos = []
        
        for slide_idx, slide in enumerate(presentation.slides):
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
            
            # Find all picture shapes
            for shape_idx, shape in enumerate(slide.shapes):
                if hasattr(shape, 'image') and shape.image:
                    try:
                        # Extract image data
                        image_data = shape.image.blob
                        filename = getattr(shape.image, 'filename', f'slide_{slide_idx}_image_{shape_idx}.png')
                        
                        # Create image info object
                        image_info = PPTXImageInfo(
                            shape=shape,
                            slide_idx=slide_idx,
                            shape_idx=shape_idx,
                            image_data=image_data,
                            filename=filename,
                            slide_text=slide_context_str[:self.max_context_length] if slide_context_str else ""
                        )
                        
                        image_infos.append(image_info)
                        logger.debug(f"Found image: {image_info.image_key} ({image_info.width_px}x{image_info.height_px}px)")
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract image from slide {slide_idx}, shape {shape_idx}: {e}")
                        continue
        
        logger.info(f"Extracted {len(image_infos)} images from {len(presentation.slides)} slides")
        return presentation, image_infos
    
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
    
    def _inject_alt_text_to_pptx(self, presentation: Presentation, 
                               alt_text_mapping: Dict[str, Any], output_path: str) -> bool:
        """
        Inject ALT text into PPTX presentation.
        
        Args:
            presentation: Presentation object
            alt_text_mapping: Mapping of image keys to ALT text and shape info
            output_path: Path to save modified PPTX
            
        Returns:
            bool: True if injection succeeded
        """
        try:
            logger.info(f"Injecting ALT text for {len(alt_text_mapping)} images")
            
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
            logger.error(f"Failed to inject ALT text into PPTX: {e}")
            return False
    
    def _log_processing_summary(self, result: Dict[str, Any]):
        """Log a summary of the processing results."""
        logger.info("PPTX Processing Summary:")
        logger.info(f"  Input file: {result['input_file']}")
        logger.info(f"  Output file: {result['output_file']}")
        logger.info(f"  Total slides: {result['total_slides']}")
        logger.info(f"  Total images found: {result['total_images']}")
        logger.info(f"  Images processed: {result['processed_images']}")
        logger.info(f"  Decorative images skipped: {result['decorative_images']}")
        logger.info(f"  Failed images: {result['failed_images']}")
        logger.info(f"  Generation time: {result['generation_time']:.2f}s")
        logger.info(f"  Injection time: {result['injection_time']:.2f}s")
        logger.info(f"  Total processing time: {result['total_time']:.2f}s")
        logger.info(f"  Success: {result['success']}")
        
        if result['errors']:
            logger.warning(f"Errors encountered: {len(result['errors'])}")
            for error in result['errors']:
                logger.warning(f"  - {error}")


def main():
    """Test the PPTX accessibility processor."""
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) not in [2, 3]:
        print("Usage: python pptx_processor.py <pptx_file> [output_file]")
        print("\nThis will process a PPTX to add ALT text to images.")
        print("If output_file is not specified, the original file will be overwritten.")
        return
    
    pptx_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) == 3 else None
    
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