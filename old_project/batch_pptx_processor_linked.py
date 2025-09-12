import os
import glob
import logging
import argparse
from pathlib import Path

# Import your existing modules
from pptx_alt import PowerPointAccessibilityAuditor
from unified_alt_generator import FlexibleAltGenerator
from decorative_filter import is_decorative_image, get_image_hash
from docx_alt_review import generate_alt_review_doc
from config_manager import ConfigManager

logger = logging.getLogger(__name__)


def setup_logging(config_manager: ConfigManager):
    """Set up logging based on configuration."""
    logging_config = config_manager.get_logging_config()
    
    level = getattr(logging, logging_config['level'].upper(), logging.INFO)
    
    handlers = [logging.StreamHandler()]
    if logging_config['log_to_file']:
        log_dir = Path(config_manager.get_output_folder()) / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / 'batch_processor.log'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


def extract_image_data_from_pptx(file_path, config_manager, output_folder=None):
    """Extract image data from PowerPoint with config support."""
    file_path = Path(file_path)
    output_config = config_manager.get_output_config()
    
    # Use provided output folder or get from config
    if not output_folder:
        output_folder = config_manager.get_output_folder()
    
    # Create auditor with config settings
    auditor = PowerPointAccessibilityAuditor(
        config_manager,
        input_folder=file_path.parent,
        output_folder=output_folder,
        thumbnail_max_width=output_config['thumbnail_max_width']
    )
    
    # Inject config manager into auditor (for decorative overrides)
    auditor.config_manager = config_manager
    
    image_data = auditor.run(file_path)

    if not isinstance(image_data, list):
        logger.error(f"Expected image_data to be a list, but got: {type(image_data)}")
        return None

    return image_data


def process_single_pptx(pptx_path, output_folder, config_manager, alt_generator):
    """Process a single PowerPoint file with configuration support."""
    pptx_path = Path(pptx_path)
    print(f"\n📄 Processing: {pptx_path.name}")
    
    # Extract image data from PowerPoint
    image_data = extract_image_data_from_pptx(pptx_path, config_manager, output_folder)
    if not image_data:
        logger.warning(f"No image data found in {pptx_path}")
        return None

    # Process statistics
    total_images = len([img for img in image_data if img.get('thumbnail_path')])
    decorative_count = 0
    generated_count = 0
    
    # Process each image
    processed_images = []
    for i, img_info in enumerate(image_data):
        if not isinstance(img_info, dict):
            logger.error(f"Entry {i} in image_data is not a dict!")
            continue

        # Handle image path
        thumbnail = img_info.get('thumbnail_path')
        if thumbnail is None:
            img_info['image_path'] = None
        else:
            img_info['image_path'] = os.path.normpath(thumbnail)
        
        # Ensure current_alt is present
        img_info['current_alt'] = img_info.get('alt_text', '[No ALT text]')
        
        # Apply decorative overrides from config
        if thumbnail and config_manager.should_force_decorative(Path(thumbnail).name):
            img_info['is_decorative'] = True
            img_info['suggested_alt'] = '[Decorative image - no ALT text needed]'
            logger.info(f"Forced decorative: {Path(thumbnail).name}")
        elif thumbnail and config_manager.should_never_decorative(Path(thumbnail).name):
            if img_info.get('is_decorative'):
                img_info['is_decorative'] = False
                logger.info(f"Prevented decorative marking: {Path(thumbnail).name}")
        
        # Count decorative images
        if img_info.get('is_decorative'):
            decorative_count += 1
        
        # Generate ALT text if needed and not already done
        if (not img_info.get('suggested_alt') and 
            not img_info.get('is_decorative') and 
            not img_info.get('alt_text') and 
            thumbnail and os.path.exists(thumbnail)):
            
            # Determine prompt type based on image name
            image_name = Path(thumbnail).name.lower()
            prompt_type = 'default'

            # Auto-select prompt based on keywords
            if any(term in image_name for term in ['anatomy', 'anatomical']):
                prompt_type = 'anatomical'
            elif any(term in image_name for term in ['xray', 'mri', 'ct', 'scan']):
                prompt_type = 'diagnostic'
            elif any(term in image_name for term in ['chart', 'graph', 'plot']):
                prompt_type = 'chart'
            elif any(term in image_name for term in ['diagram', 'schematic', 'flowchart']):
                prompt_type = 'diagram'
            elif any(term in image_name for term in ['clinical', 'patient', 'photo']):
                prompt_type = 'clinical_photo'
            
            logger.info(f"Generating ALT text with '{prompt_type}' prompt")
            alt_generator.set_prompt_type(prompt_type)
            
            context = f"Slide {img_info.get('slide_number')} of '{pptx_path.stem}'"
            generated_alt = alt_generator.generate_alt_text(thumbnail, context=context)
            
            if generated_alt:
                img_info['suggested_alt'] = generated_alt
                generated_count += 1
            else:
                img_info['suggested_alt'] = '[ALT text generation failed]'
        
        processed_images.append(img_info)
    
    # Print statistics
    print(f"📊 Statistics:")
    print(f"   Total images: {total_images}")
    print(f"   Decorative: {decorative_count}")
    print(f"   Generated ALT text: {generated_count}")
    
    # Generate the review document
    pptx_name = Path(pptx_path).stem
    output_path = os.path.join(output_folder, f"{pptx_name}_review.docx")

    if not processed_images:
        logger.warning(f"No valid image data found in {pptx_path}")
        return None

    # Final safety check for required fields
    for i, img in enumerate(processed_images):
        img.setdefault('image_number', img.get('image_index', i + 1))
        img.setdefault('slide_number', 'Unknown')
        img.setdefault('alt_text', '[No ALT text]')
        img.setdefault('current_alt', img['alt_text'])

    generate_alt_review_doc(processed_images, lecture_title=pptx_name, output_path=output_path)
    print(f"✅ Review document saved: {output_path}")
    return output_path


def batch_process_pptx_folder(input_folder, output_folder, config_manager, alt_generator):
    """Process all PowerPoint files in a folder with configuration support."""
    
    # Create output directory if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    # Find all .pptx files
    pptx_files = glob.glob(os.path.join(input_folder, '*.pptx'))
    
    # Filter out temporary files
    pptx_files = [f for f in pptx_files if not os.path.basename(f).startswith('~$')]
    
    if not pptx_files:
        print(f"❌ No .pptx files found in {input_folder}")
        return []
    
    print(f"📁 Found {len(pptx_files)} PowerPoint files to process")
    
    # Process each file
    processed_files = []
    failed_files = []
    
    for idx, pptx_file in enumerate(pptx_files, 1):
        print(f"\n{'='*60}")
        print(f"Processing file {idx}/{len(pptx_files)}")
        
        try:
            output_path = process_single_pptx(pptx_file, output_folder, config_manager, alt_generator)
            if output_path:
                processed_files.append(output_path)
        except Exception as e:
            print(f"❌ Error processing {pptx_file}: {str(e)}")
            logger.exception(f"Full error for {pptx_file}:")
            failed_files.append(pptx_file)
            continue
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Batch processing complete!")
    print(f"✅ Successfully processed: {len(processed_files)} files")
    if failed_files:
        print(f"❌ Failed: {len(failed_files)} files")
        for failed in failed_files:
            print(f"   - {os.path.basename(failed)}")
    print(f"📁 Review documents saved in: {output_folder}")
    
    return processed_files


def create_cli_parser():
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description='PowerPoint Accessibility Auditor - Batch Processor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Process with defaults from config
  %(prog)s --prompt anatomical                # Use anatomical prompt
  %(prog)s --max-tokens 100 --verbose         # Limit tokens and show debug info
  %(prog)s -i slides/ -o reports/             # Override input/output folders
  %(prog)s --config my_config.yaml            # Use custom config file
  %(prog)s --create-config                    # Create sample configuration
        """
    )
    
    # Input/Output arguments
    parser.add_argument('-i', '--input', 
                       help='Input folder containing .pptx files (overrides config)')
    
    parser.add_argument('-o', '--output', 
                       help='Output folder for review documents (overrides config)')
    
    # Configuration arguments
    parser.add_argument('-c', '--config',
                       help='Path to configuration file (YAML or JSON)')
    
    parser.add_argument('--create-config',
                       action='store_true',
                       help='Create a sample configuration file and exit')
    
    # Prompt arguments
    parser.add_argument('-p', '--prompt',
                       help='Prompt template to use',
                       default='default')
        
    parser.add_argument('--max-tokens',
                       type=int,
                       help='Maximum tokens in primary provider response')

    parser.add_argument('-m', '--model',
                       help='Model name for the primary provider (default: llava)')
    
    # Other options
    parser.add_argument('-v', '--verbose',
                       action='store_true',
                       help='Enable verbose logging (show prompts and responses)')
    
    parser.add_argument('--timeout',
                       type=int,
                       help='Request timeout for primary provider in seconds')

    parser.add_argument('--skip-decorative',
                       action='store_true',
                       help='Skip ALT text generation for decorative images')
    
    parser.add_argument('--pre-flight-only',
                       action='store_true',
                       help='Run pre-flight connectivity tests only and exit')

    
    return parser


def main():
    """Main entry point with CLI support."""
    # Parse command line arguments
    parser = create_cli_parser()
    args = parser.parse_args()
    
    # Handle config creation
    if args.create_config:
        config = ConfigManager()
        config.create_sample_config('config_sample.yaml')
        print("✅ Sample configuration created: config_sample.yaml")
        print("Edit this file and rename to config.yaml to use it.")
        return
    
    # Initialize configuration with validation
    try:
        config_manager = ConfigManager(args.config)
    except ValueError as e:
        print(f"❌ Configuration Error: {e}")
        print("\nRun with --create-config to generate a sample configuration file.")
        return
    
    # Get folders from config or CLI args
    input_folder = args.input or config_manager.get_input_folder()
    output_folder = args.output or config_manager.get_output_folder()
    
    # Update config from CLI args
    cli_updates = {}
    if args.prompt:
        cli_updates['prompt'] = args.prompt
    if args.max_tokens:
        cli_updates['max_tokens'] = args.max_tokens
    if args.verbose:
        cli_updates['verbose'] = True
    if args.model:
        cli_updates['model'] = args.model
    llava_cfg = (
        config_manager.config.setdefault('ai_providers', {})
        .setdefault('providers', {})
        .setdefault('llava', {})
    )
    if args.timeout:
        llava_cfg['timeout'] = args.timeout

    config_manager.update_from_cli(cli_updates)

    # Set up logging
    setup_logging(config_manager)
    
    # Validate input folder
    if not os.path.exists(input_folder):
        print(f"❌ Error: Input folder '{input_folder}' does not exist")
        print(f"   Please check your config.yaml or use -i to specify a valid folder")
        return
    
    # Create output directory
    os.makedirs(output_folder, exist_ok=True)
    
    # Initialize ALT text generator
    alt_generator = FlexibleAltGenerator(config_manager)
    
    # Display configuration
    print(f"🔧 Configuration:")
    print(f"   Config file: {config_manager.config_path or 'Using defaults'}")
    print(f"   Model: {llava_cfg.get('model')}")
    print(f"   Max tokens: {llava_cfg.get('max_tokens')}")
    print(f"   Default prompt: {cli_updates.get('prompt', 'auto-detect')}")
    if not args.pre_flight_only:
        print(f"   Input folder: {input_folder}")
        print(f"   Output folder: {output_folder}")
        print(f"   Thumbnail folder: {config_manager.get_thumbnail_folder()}")
    
    # Run pre-flight connectivity tests
    print(f"\n{'='*60}")
    print("🚀 Pre-flight System Check")
    print(f"{'='*60}")
    
    pre_flight_results = alt_generator.run_pre_flight_tests()
    
    # Handle pre-flight results
    if not pre_flight_results.get('enabled'):
        print("⚠️  Pre-flight tests disabled - proceeding without connectivity check")
    elif pre_flight_results.get('overall_success'):
        print("✅ All pre-flight tests passed - system ready for batch processing")
        
        # Log performance baseline for future reference
        total_time = pre_flight_results.get('total_duration', 0)
        print(f"📊 Baseline performance: {total_time:.2f}s pre-flight time")
        
        # Show test details
        for test in pre_flight_results.get('tests', []):
            if test['success']:
                print(f"   ✅ {test['test']}: {test['duration']:.2f}s")
            else:
                print(f"   ❌ {test['test']}: {test.get('error', 'Unknown error')}")
    else:
        print("💥 Pre-flight tests FAILED - cannot proceed with batch processing")
        
        # Show detailed failure information
        failed_tests = pre_flight_results.get('summary', {}).get('failed_tests', [])
        for test in pre_flight_results.get('tests', []):
            if not test['success']:
                print(f"❌ {test['test']}: {test.get('error', 'Unknown error')}")
        
        print(f"\n🔍 Troubleshooting steps:")
        print(f"   1. Check if Ollama is running: ollama list")
        print(f"   2. Verify LLaVA model is installed: ollama pull llava")
        print(f"   3. Test endpoint manually: curl {llava_cfg.get('endpoint', 'N/A').replace('/api/generate', '/api/tags')}")
        print(f"   4. Check configuration in: {config_manager.config_path or 'config.yaml'}")
        
        # Exit if fail_fast is enabled
        pre_flight_config = config_manager.config.get('pre_flight', {})
        if pre_flight_config.get('fail_fast_on_error', True):
            print("\n🛑 Exiting due to pre-flight failures (fail_fast_on_error = true)")
            return
        else:
            print("\n⚠️  Continuing despite pre-flight failures (fail_fast_on_error = false)")
    
    # Log pre-flight results for future reference
    logger.info("Pre-flight test results: %s", pre_flight_results)
    
    # If pre-flight only mode, exit here
    if args.pre_flight_only:
        print(f"\n✅ Pre-flight testing complete!")
        if pre_flight_results.get('overall_success'):
            print("🎉 System is ready for batch processing")
            return  # Exit with success
        else:
            print("💥 System has connectivity issues - see details above")
            exit(1)  # Exit with error code
    
    # Run batch processing
    print(f"\n{'='*60}")
    print("📄 Starting Batch Processing")
    print(f"{'='*60}")
    
    batch_process_pptx_folder(input_folder, output_folder, config_manager, alt_generator)


if __name__ == "__main__":
    main()