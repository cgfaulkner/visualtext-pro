"""
PDF Accessibility Processor for PDF ALT Text Generator
Orchestrates the complete PDF ALT text workflow
"""

import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

# Setup paths for direct execution

# Add parent directory to path for shared and core modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import core processing modules
from pdf_context_extractor import extract_pdf_context
from pdf_alt_injector import inject_alt_text, create_alt_text_mapping
from pdf_accessibility_recreator import PDFAccessibilityRecreator

# Import shared modules
from config_manager import ConfigManager
from unified_alt_generator import FlexibleAltGenerator

logger = logging.getLogger(__name__)


class PDFAccessibilityProcessor:
    """
    Main orchestrator for PDF accessibility processing.
    Coordinates context extraction, ALT text generation, and injection.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the PDF accessibility processor.
        
        Args:
            config_manager: Optional ConfigManager instance. If None, creates a new one.
        """
        self.config_manager = config_manager or ConfigManager()
        
        # Initialize ALT text generator
        try:
            self.alt_generator = FlexibleAltGenerator(self.config_manager)
            logger.info("Initialized PDF accessibility processor with ALT text generator")
        except Exception as e:
            logger.error(f"Failed to initialize ALT text generator: {e}")
            raise
        
        # Get processing configuration
        self.processing_config = self.config_manager.config.get('pdf_processing', {})
        
        # Decorative detection settings
        self.decorative_size_threshold = self.processing_config.get('decorative_size_threshold', 50)
        self.skip_decorative = self.processing_config.get('skip_decorative_images', True)
        
        # Recreation workflow setting
        self.use_recreation_workflow = self.processing_config.get('use_recreation_workflow', False)
        
        logger.debug(f"Decorative size threshold: {self.decorative_size_threshold}px")
        logger.debug(f"Skip decorative images: {self.skip_decorative}")
        logger.debug(f"Use recreation workflow: {self.use_recreation_workflow}")
    
    def process_pdf(self, pdf_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a PDF file to add ALT text to images.
        
        Args:
            pdf_path: Path to the input PDF file
            output_path: Optional path for output file. If None, overwrites original.
            
        Returns:
            Dictionary with processing statistics:
            {
                'success': bool,
                'input_file': str,
                'output_file': str,
                'total_images': int,
                'processed_images': int,
                'decorative_images': int,
                'failed_images': int,
                'generation_time': float,
                'injection_time': float,
                'total_time': float,
                'errors': List[str]
            }
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)
        
        # Initialize result structure
        result = {
            'success': False,
            'input_file': str(pdf_path),
            'output_file': '',
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
        if not pdf_path.exists():
            error_msg = f"PDF file not found: {pdf_path}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
            return result
        
        # Determine output path
        if output_path is None:
            output_path = pdf_path  # Overwrite original
        else:
            output_path = Path(output_path)
            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
        
        result['output_file'] = str(output_path)
        
        logger.info(f"Processing PDF: {pdf_path.name}")
        logger.info(f"Output will be saved to: {output_path}")
        
        try:
            # Step 1: Extract context from PDF
            logger.info("Step 1: Extracting images and context from PDF...")
            extraction_start = time.time()
            
            context_data = extract_pdf_context(str(pdf_path))
            
            extraction_time = time.time() - extraction_start
            logger.info(f"Context extraction completed in {extraction_time:.2f}s")
            
            images = context_data.get('images', [])
            result['total_images'] = len(images)
            
            if not images:
                logger.warning(f"No images found in PDF: {pdf_path.name}")
                result['success'] = True  # Not an error, just no images to process
                result['total_time'] = time.time() - start_time
                return result
            
            logger.info(f"Found {len(images)} images to analyze")
            
            # Step 2: Generate ALT text for images
            logger.info("Step 2: Generating ALT text for images...")
            generation_start = time.time()
            
            alt_text_mapping = {}
            
            for i, image_info in enumerate(images):
                image_key = f"page_{image_info['page_number']}_image_{image_info['image_index']}"
                
                try:
                    # Check if we should generate ALT text for this image
                    if not self._should_generate_alt_text(image_info):
                        logger.debug(f"Skipping decorative image: {image_key}")
                        result['decorative_images'] += 1
                        continue
                    
                    # Generate ALT text
                    alt_text = self._generate_alt_text_for_image(image_info)
                    
                    if alt_text:
                        alt_text_mapping[image_key] = alt_text
                        result['processed_images'] += 1
                        logger.info(f"Generated ALT text for {image_key}: {alt_text[:50]}...")
                    else:
                        result['failed_images'] += 1
                        error_msg = f"Failed to generate ALT text for {image_key}"
                        logger.warning(error_msg)
                        result['errors'].append(error_msg)
                
                except Exception as e:
                    result['failed_images'] += 1
                    error_msg = f"Error processing {image_key}: {str(e)}"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
                    continue
            
            result['generation_time'] = time.time() - generation_start
            logger.info(f"ALT text generation completed in {result['generation_time']:.2f}s")
            
            # Step 3: Inject ALT text into PDF
            if alt_text_mapping:
                logger.info("Step 3: Adding ALT text to PDF...")
                injection_start = time.time()
                
                if self.use_recreation_workflow:
                    # Use ReportLab recreation workflow for better accessibility
                    logger.info("Using ReportLab recreation workflow for accessibility")
                    recreator = PDFAccessibilityRecreator()
                    recreation_result = recreator.recreate_accessible_pdf(
                        str(pdf_path),
                        alt_text_mapping,
                        str(output_path)
                    )
                    
                    injection_success = recreation_result['success']
                    if not injection_success:
                        result['errors'].extend(recreation_result['errors'])
                else:
                    # Use original PyMuPDF injection method
                    logger.info("Using PyMuPDF injection method")
                    injection_success = inject_alt_text(
                        str(pdf_path), 
                        context_data, 
                        alt_text_mapping, 
                        str(output_path)
                    )
                
                result['injection_time'] = time.time() - injection_start
                logger.info(f"ALT text processing completed in {result['injection_time']:.2f}s")
                
                if injection_success:
                    result['success'] = True
                    workflow_type = "recreation" if self.use_recreation_workflow else "injection"
                    logger.info(f"✅ PDF processing completed successfully using {workflow_type} workflow!")
                else:
                    error_msg = f"ALT text {'recreation' if self.use_recreation_workflow else 'injection'} failed"
                    logger.error(error_msg)
                    result['errors'].append(error_msg)
            else:
                logger.info("No ALT text to process - all images were decorative or failed generation")
                result['success'] = True  # Not an error condition
            
        except Exception as e:
            error_msg = f"Unexpected error during PDF processing: {str(e)}"
            logger.error(error_msg, exc_info=True)
            result['errors'].append(error_msg)
        
        # Calculate total processing time
        result['total_time'] = time.time() - start_time
        
        # Log final statistics
        self._log_processing_summary(result)
        
        return result
    
    def _should_generate_alt_text(self, image_info: Dict[str, Any]) -> bool:
        """
        Determine if ALT text should be generated for an image.
        Uses basic decorative detection based on image size.
        
        Args:
            image_info: Image information from context extractor
            
        Returns:
            bool: True if ALT text should be generated
        """
        # Skip if decorative detection is disabled
        if not self.skip_decorative:
            return True
        
        # Get image dimensions
        width = image_info.get('image_width', 0)
        height = image_info.get('image_height', 0)
        
        # Basic size-based decorative detection
        if width > 0 and height > 0:
            max_dimension = max(width, height)
            if max_dimension < self.decorative_size_threshold:
                logger.debug(f"Image marked as decorative: {width}x{height} < {self.decorative_size_threshold}px")
                return False
        
        # Check for decorative patterns in surrounding text or page context
        # This could be enhanced with more sophisticated detection
        surrounding_text = image_info.get('surrounding_text', '').lower()
        decorative_keywords = ['logo', 'icon', 'bullet', 'decoration', 'border', 'divider']
        
        for keyword in decorative_keywords:
            if keyword in surrounding_text:
                logger.debug(f"Image marked as decorative due to context: {keyword}")
                return False
        
        return True
    
    def _generate_alt_text_for_image(self, image_info: Dict[str, Any]) -> Optional[str]:
        """
        Generate ALT text for a single image.
        
        Args:
            image_info: Image information from context extractor
            
        Returns:
            Generated ALT text or None if generation failed
        """
        try:
            # Save image to temporary file for ALT text generation
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                temp_file.write(image_info['image_data'])
                temp_image_path = temp_file.name
            
            try:
                # Get context for better ALT text generation
                context = self._build_generation_context(image_info)
                
                # Generate ALT text using the configured generator
                alt_text = self.alt_generator.generate_alt_text(
                    image_path=temp_image_path,
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
            logger.error(f"Failed to generate ALT text: {e}")
            return None
    
    def _build_generation_context(self, image_info: Dict[str, Any]) -> Optional[str]:
        """
        Build context string for ALT text generation.
        
        Args:
            image_info: Image information from context extractor
            
        Returns:
            Context string or None
        """
        context_parts = []
        
        # Add surrounding text
        surrounding_text = image_info.get('surrounding_text', '').strip()
        if surrounding_text:
            context_parts.append(f"Nearby text: {surrounding_text[:200]}")
        
        # Add page information
        page_num = image_info.get('page_number', 0)
        if page_num > 0:
            context_parts.append(f"Page {page_num}")
        
        # Add document title if available
        # Note: This would need to be passed from the context_data
        # For now, we'll keep it simple
        
        return ". ".join(context_parts) if context_parts else None
    
    def _log_processing_summary(self, result: Dict[str, Any]):
        """Log a summary of the processing results."""
        logger.info("PDF Processing Summary:")
        logger.info(f"  Input file: {result['input_file']}")
        logger.info(f"  Output file: {result['output_file']}")
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
    """Test the PDF accessibility processor."""
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) not in [2, 3]:
        print("Usage: python pdf_processor.py <pdf_file> [output_file]")
        print("\nThis will process a PDF to add ALT text to images.")
        print("If output_file is not specified, the original file will be overwritten.")
        return
    
    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) == 3 else None
    
    try:
        print("PDF Accessibility Processor Test")
        print("=" * 50)
        print(f"Processing: {pdf_path}")
        if output_path:
            print(f"Output: {output_path}")
        else:
            print("Output: Overwriting original file")
        print()
        
        # Initialize processor
        config_manager = ConfigManager()
        processor = PDFAccessibilityProcessor(config_manager)
        
        # Process PDF
        result = processor.process_pdf(pdf_path, output_path)
        
        # Display results
        print("Processing Results:")
        print(f"  Success: {result['success']}")
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
            print("✅ PDF processing completed successfully!")
            print(f"Modified PDF saved to: {result['output_file']}")
        else:
            print("❌ PDF processing failed!")
            return 1
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())