"""
PPTX Batch Processor - Process multiple PPTX files with ALT text generation.
Integrates with the existing ConfigManager and workflow patterns.
"""

import logging
import os
import sys
import time
import concurrent.futures
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Setup paths for shared modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "shared"))
sys.path.insert(0, str(project_root / "core"))

# Import modules
from config_manager import ConfigManager
from pptx_processor import PPTXAccessibilityProcessor

logger = logging.getLogger(__name__)


class PPTXBatchProcessor:
    """
    Batch processor for PPTX files that integrates with the existing system architecture.
    Supports parallel processing and comprehensive reporting.
    """
    
    def __init__(self, config_manager: Optional[ConfigManager] = None):
        """
        Initialize the batch processor.
        
        Args:
            config_manager: Optional ConfigManager instance
        """
        self.config_manager = config_manager or ConfigManager()
        
        # Get batch processing configuration
        self.pptx_config = self.config_manager.config.get('pptx_processing', {})
        self.paths_config = self.config_manager.config.get('paths', {})
        
        # Processing settings
        self.max_workers = self.pptx_config.get('max_workers', 4)
        self.preserve_original = self.pptx_config.get('preserve_original', True)
        self.supported_formats = self.pptx_config.get('supported_formats', ['.pptx', '.ppt'])
        
        # Paths
        self.input_folder = Path(self.paths_config.get('input_folder', 'documents_to_review'))
        self.output_folder = Path(self.paths_config.get('output_folder', 'reviewed_reports'))
        
        logger.info(f"Initialized PPTX batch processor:")
        logger.info(f"  Input folder: {self.input_folder}")
        logger.info(f"  Output folder: {self.output_folder}")
        logger.info(f"  Max workers: {self.max_workers}")
        logger.info(f"  Preserve original: {self.preserve_original}")
    
    def discover_pptx_files(self, input_path: Optional[str] = None) -> List[Path]:
        """
        Discover PPTX files to process.
        
        Args:
            input_path: Optional specific path to search. Uses config input_folder if None.
            
        Returns:
            List of PPTX file paths
        """
        search_path = Path(input_path) if input_path else self.input_folder
        
        if not search_path.exists():
            logger.error(f"Input path does not exist: {search_path}")
            return []
        
        pptx_files = []
        
        if search_path.is_file():
            # Single file
            if search_path.suffix.lower() in ['.pptx', '.ppt']:
                pptx_files.append(search_path)
        else:
            # Directory - search for PPTX files
            for pattern in ['*.pptx', '*.PPTX', '*.ppt', '*.PPT']:
                pptx_files.extend(search_path.glob(pattern))
                # Also search subdirectories
                pptx_files.extend(search_path.rglob(pattern))
        
        # Remove duplicates and sort
        pptx_files = sorted(list(set(pptx_files)))
        
        logger.info(f"Discovered {len(pptx_files)} PPTX files to process")
        for file_path in pptx_files:
            logger.debug(f"  Found: {file_path}")
        
        return pptx_files
    
    def process_batch(self, input_path: Optional[str] = None, 
                     output_path: Optional[str] = None,
                     parallel: bool = True) -> Dict[str, Any]:
        """
        Process a batch of PPTX files.
        
        Args:
            input_path: Optional input path (file or directory)
            output_path: Optional output directory
            parallel: Whether to process files in parallel
            
        Returns:
            Dictionary with batch processing results
        """
        start_time = time.time()
        
        # Initialize result structure
        result = {
            'success': False,
            'total_files': 0,
            'processed_files': 0,
            'failed_files': 0,
            'skipped_files': 0,
            'total_images': 0,
            'processed_images': 0,
            'decorative_images': 0,
            'failed_images': 0,
            'total_time': 0.0,
            'average_time_per_file': 0.0,
            'files': [],
            'errors': []
        }
        
        # Discover files to process
        pptx_files = self.discover_pptx_files(input_path)
        result['total_files'] = len(pptx_files)
        
        if not pptx_files:
            logger.warning("No PPTX files found to process")
            result['success'] = True  # Not an error condition
            result['total_time'] = time.time() - start_time
            return result
        
        # Determine output directory
        output_dir = Path(output_path) if output_path else self.output_folder
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Processing {len(pptx_files)} PPTX files")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Parallel processing: {'Enabled' if parallel else 'Disabled'}")
        
        # Process files
        if parallel and len(pptx_files) > 1:
            file_results = self._process_files_parallel(pptx_files, output_dir)
        else:
            file_results = self._process_files_sequential(pptx_files, output_dir)
        
        # Aggregate results
        for file_result in file_results:
            result['files'].append(file_result)
            
            if file_result['success']:
                result['processed_files'] += 1
                result['total_images'] += file_result.get('total_images', 0)
                result['processed_images'] += file_result.get('processed_images', 0)
                result['decorative_images'] += file_result.get('decorative_images', 0)
                result['failed_images'] += file_result.get('failed_images', 0)
            else:
                result['failed_files'] += 1
            
            # Collect errors
            if file_result.get('errors'):
                result['errors'].extend(file_result['errors'])
        
        # Calculate final statistics
        result['total_time'] = time.time() - start_time
        if result['processed_files'] > 0:
            result['average_time_per_file'] = result['total_time'] / result['processed_files']
        
        result['success'] = result['failed_files'] == 0
        
        # Log final summary
        self._log_batch_summary(result)
        
        return result
    
    def _process_files_sequential(self, pptx_files: List[Path], output_dir: Path) -> List[Dict[str, Any]]:
        """Process files sequentially."""
        results = []
        processor = PPTXAccessibilityProcessor(self.config_manager)
        
        for i, pptx_file in enumerate(pptx_files, 1):
            logger.info(f"Processing file {i}/{len(pptx_files)}: {pptx_file.name}")
            
            try:
                output_file = self._determine_output_path(pptx_file, output_dir)
                file_result = processor.process_pptx(str(pptx_file), str(output_file))
                file_result['input_file'] = str(pptx_file)
                file_result['output_file'] = str(output_file)
                results.append(file_result)
                
                if file_result['success']:
                    logger.info(f"✅ Successfully processed: {pptx_file.name}")
                else:
                    logger.error(f"❌ Failed to process: {pptx_file.name}")
                    
            except Exception as e:
                error_result = {
                    'success': False,
                    'input_file': str(pptx_file),
                    'output_file': '',
                    'errors': [f"Processing error: {str(e)}"],
                    'total_time': 0.0
                }
                results.append(error_result)
                logger.error(f"❌ Error processing {pptx_file.name}: {e}")
        
        return results
    
    def _process_files_parallel(self, pptx_files: List[Path], output_dir: Path) -> List[Dict[str, Any]]:
        """Process files in parallel."""
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_file = {}
            
            for pptx_file in pptx_files:
                output_file = self._determine_output_path(pptx_file, output_dir)
                future = executor.submit(self._process_single_file, pptx_file, output_file)
                future_to_file[future] = pptx_file
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_file):
                pptx_file = future_to_file[future]
                
                try:
                    file_result = future.result()
                    results.append(file_result)
                    
                    if file_result['success']:
                        logger.info(f"✅ Successfully processed: {pptx_file.name}")
                    else:
                        logger.error(f"❌ Failed to process: {pptx_file.name}")
                        
                except Exception as e:
                    error_result = {
                        'success': False,
                        'input_file': str(pptx_file),
                        'output_file': '',
                        'errors': [f"Processing error: {str(e)}"],
                        'total_time': 0.0
                    }
                    results.append(error_result)
                    logger.error(f"❌ Error processing {pptx_file.name}: {e}")
        
        return results
    
    def _process_single_file(self, pptx_file: Path, output_file: Path) -> Dict[str, Any]:
        """Process a single PPTX file (used by parallel processing)."""
        processor = PPTXAccessibilityProcessor(self.config_manager)
        
        file_result = processor.process_pptx(str(pptx_file), str(output_file))
        file_result['input_file'] = str(pptx_file)
        file_result['output_file'] = str(output_file)
        
        return file_result
    
    def _determine_output_path(self, input_file: Path, output_dir: Path) -> Path:
        """
        Determine the output path for a processed file.
        
        Args:
            input_file: Input PPTX file path
            output_dir: Output directory
            
        Returns:
            Output file path
        """
        # Create output filename
        if self.preserve_original:
            # Add suffix to indicate ALT text processing
            stem = input_file.stem
            suffix = input_file.suffix
            output_filename = f"{stem}_with_alt{suffix}"
        else:
            # Use same filename (will overwrite)
            output_filename = input_file.name
        
        return output_dir / output_filename
    
    def _log_batch_summary(self, result: Dict[str, Any]):
        """Log a comprehensive summary of batch processing results."""
        logger.info("PPTX Batch Processing Summary:")
        logger.info(f"  Total files found: {result['total_files']}")
        logger.info(f"  Files processed successfully: {result['processed_files']}")
        logger.info(f"  Files failed: {result['failed_files']}")
        logger.info(f"  Files skipped: {result['skipped_files']}")
        logger.info(f"  Total images found: {result['total_images']}")
        logger.info(f"  Images processed: {result['processed_images']}")
        logger.info(f"  Decorative images skipped: {result['decorative_images']}")
        logger.info(f"  Images failed: {result['failed_images']}")
        logger.info(f"  Total processing time: {result['total_time']:.2f}s")
        logger.info(f"  Average time per file: {result['average_time_per_file']:.2f}s")
        logger.info(f"  Overall success: {result['success']}")
        
        if result['errors']:
            logger.warning(f"Total errors encountered: {len(result['errors'])}")
            # Log first few errors for debugging
            for i, error in enumerate(result['errors'][:5], 1):
                logger.warning(f"  Error {i}: {error}")
            if len(result['errors']) > 5:
                logger.warning(f"  ... and {len(result['errors']) - 5} more errors")
    
    def generate_report(self, result: Dict[str, Any], output_path: Optional[str] = None) -> str:
        """
        Generate a detailed processing report.
        
        Args:
            result: Batch processing results
            output_path: Optional path to save report
            
        Returns:
            Report content as string
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report_lines = [
            "PPTX Batch Processing Report",
            "=" * 50,
            f"Generated: {timestamp}",
            "",
            "SUMMARY:",
            f"  Total files: {result['total_files']}",
            f"  Successfully processed: {result['processed_files']}",
            f"  Failed: {result['failed_files']}",
            f"  Total processing time: {result['total_time']:.2f}s",
            f"  Average time per file: {result['average_time_per_file']:.2f}s",
            "",
            "IMAGE STATISTICS:",
            f"  Total images found: {result['total_images']}",
            f"  Images processed with ALT text: {result['processed_images']}",
            f"  Decorative images (skipped): {result['decorative_images']}",
            f"  Images that failed processing: {result['failed_images']}",
            "",
            "FILE DETAILS:",
            "-" * 20
        ]
        
        # Add details for each file
        for file_info in result['files']:
            status = "✅ SUCCESS" if file_info['success'] else "❌ FAILED"
            input_file = Path(file_info['input_file']).name
            
            report_lines.extend([
                f"File: {input_file}",
                f"  Status: {status}",
                f"  Processing time: {file_info.get('total_time', 0):.2f}s",
                f"  Total images: {file_info.get('total_images', 0)}",
                f"  Processed: {file_info.get('processed_images', 0)}",
                f"  Decorative: {file_info.get('decorative_images', 0)}",
                f"  Failed: {file_info.get('failed_images', 0)}",
            ])
            
            if file_info.get('errors'):
                report_lines.append(f"  Errors: {len(file_info['errors'])}")
                for error in file_info['errors']:
                    report_lines.append(f"    - {error}")
            
            report_lines.append("")
        
        # Add overall error summary
        if result['errors']:
            report_lines.extend([
                "ERRORS SUMMARY:",
                "-" * 20
            ])
            for i, error in enumerate(result['errors'], 1):
                report_lines.append(f"{i}. {error}")
        
        report_content = "\n".join(report_lines)
        
        # Save report if path provided
        if output_path:
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                logger.info(f"Report saved to: {output_path}")
            except Exception as e:
                logger.error(f"Failed to save report: {e}")
        
        return report_content


def main():
    """Command-line interface for batch PPTX processing."""
    import argparse
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description='Batch process PPTX files to add ALT text')
    parser.add_argument('input', nargs='?', help='Input file or directory (default: from config)')
    parser.add_argument('-o', '--output', help='Output directory (default: from config)')
    parser.add_argument('--sequential', action='store_true', help='Process files sequentially')
    parser.add_argument('--report', help='Path to save processing report')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        print("PPTX Batch Processor")
        print("=" * 50)
        
        # Initialize processor
        config_manager = ConfigManager()
        batch_processor = PPTXBatchProcessor(config_manager)
        
        # Process batch
        parallel = not args.sequential
        result = batch_processor.process_batch(
            input_path=args.input,
            output_path=args.output,
            parallel=parallel
        )
        
        # Display results
        print(f"\nProcessing completed!")
        print(f"Files processed: {result['processed_files']}/{result['total_files']}")
        print(f"Images processed: {result['processed_images']}")
        print(f"Total time: {result['total_time']:.2f}s")
        
        # Generate report if requested
        if args.report:
            report_content = batch_processor.generate_report(result, args.report)
            print(f"Report saved to: {args.report}")
        
        # Exit with appropriate code
        if result['success']:
            print("✅ All files processed successfully!")
            return 0
        else:
            print(f"❌ {result['failed_files']} files failed processing")
            return 1
            
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit(main())