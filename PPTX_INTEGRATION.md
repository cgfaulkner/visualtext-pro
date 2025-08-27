# PPTX ALT Text Integration

This document describes how the PPTX ALT text injection mechanism has been adapted to work with your existing PDF accessibility system components.

## Overview

The PPTX integration successfully adapts the existing PDF processing architecture to handle PowerPoint presentations while reusing all your core components:

- ✅ **ConfigManager** - Uses the same configuration system
- ✅ **FlexibleAltGenerator** - Leverages existing AI provider architecture 
- ✅ **Medical-specific prompts** - Full support for anatomical, diagnostic, clinical, etc.
- ✅ **Decorative detection** - Same rule-based and heuristic detection
- ✅ **Batch processing** - Parallel processing with comprehensive reporting

## Architecture

```
PPTX Integration Architecture
├── Core Components (Reused)
│   ├── ConfigManager           # Configuration management
│   ├── FlexibleAltGenerator    # AI provider abstraction & fallback
│   ├── Medical prompt system   # Domain-specific prompts  
│   └── Decorative filter       # Image classification rules
│
└── New PPTX Components
    ├── PPTXAccessibilityProcessor   # Single file processing
    ├── PPTXBatchProcessor          # Batch processing
    ├── PPTXImageInfo              # Image data container
    └── Integration tests          # Validation suite
```

## Key Features

### 1. **Seamless Integration**
- Uses existing `config.yaml` with new `pptx_processing` section
- Same AI providers (LLaVA, etc.) and fallback chains
- Identical decorative detection rules and medical prompts

### 2. **Medical Domain Support**
- **Anatomical**: "Describe this anatomical image... Mention key structures and orientations"
- **Diagnostic**: "Describe this diagnostic image... Note the imaging type and key findings"  
- **Clinical Photo**: "Describe this clinical photo... Focus on the visible condition"
- **Unified Medical**: General medical image description

### 3. **Smart Context Extraction**
- Extracts slide text and notes for context-aware ALT text
- Intelligent prompt type detection based on content keywords
- Respects character limits and truncation settings

### 4. **Decorative Detection**
- Configuration-based rules (contains: logo, watermark, border, etc.)
- Never-decorative overrides (anatomy, xray, mri, etc.)
- Size-based thresholds and heuristic detection
- Duplicate image detection across slides

## Installation

### Prerequisites
```bash
pip install python-pptx
```

### Files Added
- `core/pptx_processor.py` - Single PPTX file processor
- `core/pptx_batch_processor.py` - Batch processing with parallel support
- `test_pptx_integration.py` - Integration test suite
- Updated `config.yaml` with PPTX settings

## Configuration

The existing `config.yaml` has been extended with PPTX-specific settings:

```yaml
# PPTX Processing Configuration (NEW)
pptx_processing:
  # Decorative image detection settings (same as PDF)
  skip_decorative_images: true
  decorative_size_threshold: 50  # Images smaller than this (px) are considered decorative
  
  # Context extraction settings
  include_slide_notes: true    # Include slide notes in ALT text generation context
  include_slide_text: true     # Include slide text in ALT text generation context
  max_context_length: 200      # Maximum length of context text to include
  
  # Batch processing settings
  max_workers: 4               # Number of concurrent slides to process
  preserve_original: true      # Keep backup of original file
  
  # Image extraction settings
  supported_formats: ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "svg", "wmf", "emf"]
  convert_wmf_to_png: true     # Convert WMF files to PNG for better AI processing
```

## Usage

### Single File Processing

```python
from core.pptx_processor import PPTXAccessibilityProcessor
from shared.config_manager import ConfigManager

# Initialize
config_manager = ConfigManager()
processor = PPTXAccessibilityProcessor(config_manager)

# Process a single PPTX file
result = processor.process_pptx(
    pptx_path="presentation.pptx",
    output_path="presentation_with_alt.pptx"  # Optional, overwrites original if None
)

print(f"Success: {result['success']}")
print(f"Images processed: {result['processed_images']}")
print(f"Decorative images: {result['decorative_images']}")
```

### Command Line Usage

```bash
# Process single file
python core/pptx_processor.py presentation.pptx output_presentation.pptx

# Process single file (overwrite original)
python core/pptx_processor.py presentation.pptx
```

### Batch Processing

```python
from core.pptx_batch_processor import PPTXBatchProcessor

# Initialize batch processor
batch_processor = PPTXBatchProcessor(config_manager)

# Process all PPTX files in a directory
result = batch_processor.process_batch(
    input_path="slides_folder/",
    output_path="processed_slides/",
    parallel=True
)

# Generate detailed report
report = batch_processor.generate_report(result, "processing_report.txt")
```

### Command Line Batch Processing

```bash
# Process directory with parallel processing (default)
python core/pptx_batch_processor.py slides_folder/ -o processed_slides/

# Process sequentially
python core/pptx_batch_processor.py slides_folder/ --sequential

# Generate processing report
python core/pptx_batch_processor.py slides_folder/ --report processing_report.txt

# Verbose logging
python core/pptx_batch_processor.py slides_folder/ -v
```

## Integration Testing

Run the comprehensive integration test suite:

```bash
python test_pptx_integration.py
```

This validates:
- PPTX module availability  
- ConfigManager integration
- ALT generator integration
- Decorative filter integration
- Medical prompt system
- Processor initialization
- Configuration validation

## Medical Use Case Examples

### Example 1: Anatomical Presentation
```
Input slide text: "Human Heart Anatomy - Cross Section View"
Image: heart_anatomy.png
Generated ALT text: "Cross-sectional anatomical view of human heart showing four chambers and major vessels"
Prompt type: anatomical (auto-detected)
```

### Example 2: Diagnostic Imaging  
```
Input slide text: "Chest X-Ray Analysis - Pneumonia Case Study"  
Image: chest_xray.jpg
Generated ALT text: "Chest X-ray showing bilateral infiltrates consistent with pneumonia"
Prompt type: diagnostic (auto-detected)
```

### Example 3: Clinical Documentation
```
Input slide text: "Surgical Procedure - Minimally Invasive Technique"
Image: surgery_photo.jpg  
Generated ALT text: "Laparoscopic surgical view showing instrument placement during procedure"
Prompt type: clinical_photo (auto-detected)
```

## Decorative Detection Examples

### Images Marked as Decorative (Skipped)
- `logo.png`, `watermark.jpg`, `border_line.png`
- Images smaller than 50px in any dimension
- Headers, footers, dividers, separators

### Images Never Marked as Decorative
- `anatomy_chart.png`, `xray_image.jpg`, `mri_scan.png` 
- Any image containing: anatomy, pathology, xray, mri, ct, microscopy, diagram, chart, graph

## Processing Statistics

The system provides detailed statistics for each processing run:

```
PPTX Processing Summary:
  Input file: presentation.pptx
  Output file: presentation_with_alt.pptx
  Total slides: 25
  Total images found: 45
  Images processed: 38
  Decorative images skipped: 7
  Failed images: 0
  Generation time: 45.2s
  Injection time: 2.1s
  Total processing time: 47.3s
  Success: True
```

## Error Handling

The system includes robust error handling:

- **Provider fallback**: Automatic failover between AI providers
- **Smart retry logic**: Exponential backoff for temporary failures
- **Partial success**: Continues processing even if individual images fail
- **Detailed logging**: Comprehensive error reporting and debugging info

## Performance Considerations

- **Parallel processing**: Configurable worker threads for batch operations
- **Context caching**: Slide text and notes extracted once per slide
- **Smart truncation**: Automatic text summarization when context is too long
- **Cost tracking**: Monitor AI provider usage and costs

## Compatibility

- **Python 3.7+**
- **PowerPoint formats**: .pptx, .ppt (via python-pptx)
- **Image formats**: JPG, PNG, GIF, BMP, TIFF, SVG, WMF, EMF
- **AI Providers**: LLaVA (local), extensible to other providers

## Troubleshooting

### Common Issues

1. **"python-pptx not found"**
   ```bash
   pip install python-pptx
   ```

2. **"No PPTX configuration found"**
   - Ensure `config.yaml` includes the `pptx_processing` section
   - Run integration tests to validate configuration

3. **"No AI providers available"**
   - Check that LLaVA or other providers are configured in `ai_providers` section
   - Verify provider endpoints are accessible

4. **"All images marked as decorative"**
   - Review decorative detection rules in `decorative_overrides`
   - Adjust `decorative_size_threshold` if needed
   - Check `never_decorative` list for medical content

### Debug Mode
```bash
python core/pptx_processor.py presentation.pptx --verbose
```

## Future Enhancements

Possible extensions to the PPTX integration:

1. **Additional AI Providers**: GPT-4 Vision, Claude Vision, Gemini Pro Vision
2. **Advanced Context**: Table data extraction, chart interpretation  
3. **Accessibility Standards**: WCAG 2.1 AA compliance validation
4. **Template Support**: Custom ALT text templates per presentation type
5. **Integration APIs**: REST API for web service integration

## Conclusion

The PPTX ALT text integration successfully adapts your existing PDF accessibility system to handle PowerPoint presentations while maintaining all the sophisticated features:

- ✅ **Reuses 100% of existing architecture**: ConfigManager, FlexibleAltGenerator, prompts, decorative detection
- ✅ **Medical domain expertise**: Full support for anatomical, diagnostic, and clinical content  
- ✅ **Production ready**: Comprehensive error handling, logging, and testing
- ✅ **Scalable**: Parallel batch processing with detailed reporting
- ✅ **Extensible**: Easy to add new AI providers and prompt types

The integration maintains consistency with your existing workflow while extending capabilities to PowerPoint presentations, making it easy for users to process both PDF and PPTX files with the same system and configuration.