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

# Import system components
from config_manager import ConfigManager
from pptx_processor import PPTXAccessibilityProcessor
from pptx_alt_injector import PPTXAltTextInjector

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PPTXAltProcessor:
    """
    Simple integration script that combines all PPTX ALT text components.
    Provides an easy-to-use interface for complete PPTX accessibility processing.
    """
    
    def __init__(self, config_path: Optional[str] = None, verbose: bool = False, force_decorative: bool = False):
        """
        Initialize the PPTX ALT text processor.
        
        Args:
            config_path: Optional path to configuration file
            verbose: Enable verbose logging
            force_decorative: Force decorative fallback for failed generations
        """
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Initialize core components
        self.config_manager = ConfigManager(config_path)
        self.pptx_processor = PPTXAccessibilityProcessor(self.config_manager)
        self.alt_injector = PPTXAltTextInjector(self.config_manager)
        self.force_decorative = force_decorative
        
        # Setup failed generation logging
        self.failed_generations = []
        
        logger.info("PPTX ALT Text Processor initialized")
        logger.info(f"Configuration: {self.config_manager.config_path or 'default'}")
    
    def process_single_file(self, input_file: str, output_file: Optional[str] = None,
                          export_pdf: bool = False, generate_coverage_report: bool = True) -> dict:
        """
        Process a single PPTX file with complete ALT text workflow.
        
        Args:
            input_file: Path to input PPTX file
            output_file: Optional output path (defaults to overwriting input)
            export_pdf: Whether to export to PDF after processing
            
        Returns:
            Dictionary with processing results
        """
        input_path = Path(input_file)
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        if output_file is None:
            output_file = str(input_path)
        
        output_path = Path(output_file)
        
        logger.info(f"Processing PPTX: {input_path.name}")
        logger.info(f"Output: {output_path.name}")
        
        start_time = time.time()
        
        try:
            # Clear previous failed generations
            self.failed_generations = []
            
            # Use the existing PPTXAccessibilityProcessor with enhanced validation
            result = self.pptx_processor.process_pptx(
                str(input_path), 
                str(output_path), 
                force_decorative=self.force_decorative,
                failed_generation_callback=self._log_failed_generation
            )
            
            processing_time = time.time() - start_time
            result['processing_time'] = processing_time
            
            # Ensure we have the processed_images count
            if 'processed_images' not in result:
                result['processed_images'] = result.get('total_images', 0)
            
            if result['success']:
                # Generate and log coverage report
                coverage_report = self._generate_coverage_report(result)
                result['coverage_report'] = coverage_report
                
                logger.info(f"✅ Successfully processed PPTX:")
                logger.info(f"   Input: {input_path.name}")
                logger.info(f"   Output: {output_path.name}")
                logger.info(f"   Images processed: {result['processed_images']}")
                logger.info(f"   Processing time: {processing_time:.2f}s")
                
                # Log coverage statistics
                self._log_coverage_report(coverage_report)
                
                # Generate coverage report file if requested
                if generate_coverage_report:
                    self._save_coverage_report_file(coverage_report, input_path, output_path)
                
                # Optional PDF export
                if export_pdf:
                    pdf_result = self._export_to_pdf(output_path)
                    result['pdf_export'] = pdf_result
                    
                    if pdf_result['success']:
                        logger.info(f"   PDF exported: {pdf_result['pdf_file']}")
                    else:
                        logger.warning(f"   PDF export failed: {pdf_result['error']}")
            else:
                logger.error(f"❌ Processing failed:")
                for error in result.get('errors', []):
                    logger.error(f"   - {error}")
            
            # Log any failed generations for manual review
            if self.failed_generations:
                self._log_failed_generations_summary()
                result['failed_generations'] = self.failed_generations
            
            return result
            
        except Exception as e:
            error_msg = f"Processing failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            return {
                'success': False,
                'input_file': str(input_path),
                'output_file': str(output_path),
                'processing_time': time.time() - start_time,
                'errors': [error_msg]
            }
    
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
        Generate coverage report showing descriptive vs decorative counts.
        
        Args:
            result: Processing result dictionary
            
        Returns:
            Coverage report dictionary
        """
        total_images = result.get('total_images', 0)
        processed_images = result.get('processed_images', 0)  # Descriptive
        decorative_images = result.get('decorative_images', 0)
        failed_images = result.get('failed_images', 0)
        fallback_decorative = result.get('fallback_decorative', 0)
        
        # Calculate coverage percentages
        descriptive_coverage = (processed_images / total_images * 100) if total_images > 0 else 0
        decorative_coverage = ((decorative_images + fallback_decorative) / total_images * 100) if total_images > 0 else 0
        total_coverage = ((processed_images + decorative_images + fallback_decorative) / total_images * 100) if total_images > 0 else 0
        
        return {
            'total_images': total_images,
            'descriptive_images': processed_images,
            'decorative_images': decorative_images,
            'fallback_decorative_images': fallback_decorative,
            'failed_images': failed_images,
            'descriptive_coverage_percent': descriptive_coverage,
            'decorative_coverage_percent': decorative_coverage,
            'total_coverage_percent': total_coverage,
            'failed_generations_count': len(self.failed_generations)
        }
    
    def _log_coverage_report(self, coverage_report: dict):
        """
        Log the coverage report to console.
        
        Args:
            coverage_report: Coverage report dictionary
        """
        logger.info("📊 Image Coverage Report:")
        logger.info(f"   Total images: {coverage_report['total_images']}")
        logger.info(f"   Descriptive ALT text: {coverage_report['descriptive_images']} ({coverage_report['descriptive_coverage_percent']:.1f}%)")
        logger.info(f"   Decorative (heuristic): {coverage_report['decorative_images']}")
        logger.info(f"   Decorative (fallback): {coverage_report['fallback_decorative_images']}")
        logger.info(f"   Total decorative: {coverage_report['decorative_images'] + coverage_report['fallback_decorative_images']} ({coverage_report['decorative_coverage_percent']:.1f}%)")
        logger.info(f"   Failed/Unprocessed: {coverage_report['failed_images']}")
        logger.info(f"   TOTAL COVERAGE: {coverage_report['total_coverage_percent']:.1f}%")
        
        if coverage_report['failed_generations_count'] > 0:
            logger.warning(f"   Failed generations logged: {coverage_report['failed_generations_count']} (see coverage report file)")
    
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
    parser.add_argument('--force-decorative', action='store_true', help='Force decorative fallback for failed generations (ensures 100%% coverage)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        # Initialize processor
        processor = PPTXAltProcessor(args.config, args.verbose, args.force_decorative)
        
        if args.command == 'process':
            result = processor.process_single_file(
                args.input_file, 
                args.output, 
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
                return 1
                
        elif args.command == 'batch-process':
            result = processor.process_directory(
                args.input_dir,
                args.output_dir,
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
            result = processor.extract_images_only(args.input_file, args.output)
            
            if result['success']:
                print(f"✅ Extracted {result['images_extracted']} images")
                if result['output_file']:
                    print(f"Data saved to: {result['output_file']}")
            else:
                print(f"❌ Extraction failed: {result['error']}")
                return 1
                
        elif args.command == 'inject':
            result = processor.inject_alt_text_from_file(
                args.input_file,
                args.alt_text_file,
                args.output
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
            result = processor.test_pdf_export_survival(args.input_file)
            
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