# VisualText Pro - Multi-Format Accessibility Toolkit

## Overview

VisualText Pro is a comprehensive accessibility toolkit for extracting visual elements from PowerPoint presentations, generating high-quality alternative text using AI vision models, and injecting the descriptions back into slides. The toolkit focuses on meaningful accessibility improvements while filtering out placeholder content and handling complex grouped shapes intelligently.

**Key Features:**
- AI-powered ALT text generation using local LLaVA models
- Smart filtering of PowerPoint placeholder text boxes
- Intelligent handling of grouped shapes with semantic roll-up
- Multiple processing pipelines for different workflow needs
- Preserve/replace/smart ALT text policies
- Batch processing capabilities
- Review document generation for human oversight

## Repository Structure

```
visualtext-pro/
├── core/                    # Core processing pipelines and orchestration
├── shared/                  # Shared utilities, configuration, and manifest handling  
├── Documents to Review/     # Default input folder for presentations
├── config.yaml             # Main configuration file
├── altgen.py               # 🆕 Unified CLI dispatcher (recommended entry point)
├── pptx_alt_processor.py   # Original full-featured processor
├── pptx_clean_processor.py # Three-phase pipeline with JSON artifacts  
├── pptx_manifest_processor.py # Manifest-driven workflow with caching
└── requirements.txt        # Python dependencies
```

## Installation

1. **Python Environment**: Use Python 3.12 in a fresh virtual environment
   ```bash
   python3.12 -m venv visualtext-pro
   source visualtext-pro/bin/activate  # On Windows: visualtext-pro\Scripts\activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **LLaVA Setup**: Install and run Ollama with LLaVA model
   ```bash
   # Install Ollama (see https://ollama.ai)
   ollama pull llava
   ollama serve  # Runs on http://127.0.0.1:11434 by default
   ```

## Quick Start

**Recommended approach using unified CLI:**

1. **Place presentation in Documents to Review/** (or use full path)

2. **Process single file:**
   ```bash
   python altgen.py process "Documents to Review/your_deck.pptx"
   ```

3. **Dry run to preview changes:**
   ```bash
   python altgen.py --dry-run process "Documents to Review/your_deck.pptx"
   ```

4. **Batch process folder:**
   ```bash
   python altgen.py process "Documents to Review/"
   ```

## Command-Line Tools

### altgen.py (Unified CLI - Recommended)

**Purpose**: Single entry point that dispatches to the appropriate underlying processor based on your needs.

**Usage**: `python altgen.py [global-options] <command> [command-options]`

#### Global Options (Apply to All Commands)

| Flag | Values | Default | Description |
|------|--------|---------|-------------|
| `--config` | path | `config.yaml` | Path to configuration file |
| `--mode` | presentation, scientific, context, auto | auto | Processing approach for content analysis |
| `--alt-policy` | preserve, smart, overwrite_all | smart | How to handle existing ALT text |
| `--dry-run` | flag | false | Preview changes without modifying files |
| `--verbose` | flag | false | Enable detailed logging output |
| `--log-jsonl` | path | none | Log processing decisions to JSONL file |
| `--profile` | name | none | Load preset configuration profile |

#### ALT Text Policies Explained

- **preserve**: Keep all existing ALT text, only add to elements without any
- **smart**: Replace low-quality/placeholder ALT text, preserve meaningful descriptions  
- **overwrite_all**: Replace all existing ALT text with newly generated descriptions

#### Processing Modes Explained

- **presentation**: Optimized for business presentations with photos and simple graphics
- **scientific**: Enhanced shape processing for diagrams, charts, and technical content
- **context**: Uses surrounding slide content (titles, text) to inform ALT text generation
- **auto**: Automatically selects appropriate mode based on presentation content

#### Commands

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `analyze <file>` | Analyze presentation and generate review document | `--output` |
| `process <file>` | Full pipeline: analyze, generate, and inject ALT text | `--output` |
| `inject <file>` | Inject ALT text from existing manifest/mapping | `--manifest` |
| `review <manifest>` | Generate Word review document from manifest | `--output` |
| `audit <file>` | Validate presentation accessibility and report issues | |

#### Example Commands

```bash
# Quick processing with smart ALT policy
python altgen.py --alt-policy smart process presentation.pptx

# Scientific mode for technical content with dry run
python altgen.py --mode scientific --dry-run process technical_diagram.pptx

# Batch process with detailed logging
python altgen.py --verbose --log-jsonl logs/batch.jsonl process "folder/*.pptx"

# Generate review document only
python altgen.py analyze presentation.pptx --output review.docx
```

### Direct Processor Usage (Advanced)

For advanced users who need specific pipeline features:

#### pptx_alt_processor.py (Original Full-Featured)

**Best for**: Single files, PDF export, comprehensive processing with all features

```bash
# Basic processing
python pptx_alt_processor.py process presentation.pptx

# With PDF export and approval documents  
python pptx_alt_processor.py process presentation.pptx --export-pdf --generate-approval-documents

# Shape processing controls for scientific content
python pptx_alt_processor.py process technical.pptx --llava-include-shapes all --max-shapes-per-slide 10
```

**Key Flags**:
- `--export-pdf`: Generate accessible PDF after processing
- `--llava-include-shapes`: `off|smart|all` - Controls which shapes get processed
- `--max-shapes-per-slide`: Limit shapes processed per slide (performance)
- `--min-shape-area`: Minimum shape size to process (e.g., "1%", "100px")

#### pptx_clean_processor.py (Three-Phase Pipeline)

**Best for**: Audit trails, reproducible results, JSON artifact inspection

```bash
# Full pipeline with review document
python pptx_clean_processor.py process presentation.pptx --review-doc

# Review document only (no injection)
python pptx_clean_processor.py process presentation.pptx --review-doc-only

# Inject from existing artifacts
python pptx_clean_processor.py inject presentation.pptx --alt-map final_alt_map.json
```

#### pptx_manifest_processor.py (Manifest-Driven)

**Best for**: Caching, consistency across runs, team workflows

```bash
# Process with manifest caching
python pptx_manifest_processor.py process presentation.pptx --manifest cache.jsonl

# Review-only mode (no file changes)
python pptx_manifest_processor.py process presentation.pptx --review-only

# Validate existing manifest
python pptx_manifest_processor.py validate cache.jsonl
```

## Configuration

### config.yaml Structure

```yaml
# ALT Text Generation
mode: preserve                    # Default ALT handling: preserve|replace
fallback_policy: none            # Decorative shape handling
min_confidence: 0.7              # Minimum confidence for ALT text acceptance

# AI Provider Configuration
ai_providers:
  llava:
    endpoint: "http://127.0.0.1:11434/api/generate"
    model: "llava"
    timeout: 30
    max_retries: 3

# Path Configuration
paths:
  input_folder: "Documents to Review"
  output_folder: "Documents to Review"
  temp_folder: "temp"
  cache_folder: "cache"

# Processing Controls  
processing:
  max_workers: 4                 # Concurrent processing threads
  max_shapes_per_slide: 5        # Limit shapes processed per slide
  min_shape_area: "1%"          # Minimum shape size threshold

# Prompt Templates
prompts:
  default: "Describe this image for screen reader accessibility..."
  scientific: "Describe this technical diagram focusing on..."
  decorative_override: "[Decorative image]"
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLAVA_ENDPOINT` | Override LLaVA API endpoint | `http://127.0.0.1:11434` |
| `VISUALTEXT_PRO_CONFIG` | Override config file path | `config.yaml` |
| `VISUALTEXT_PRO_LOG_LEVEL` | Set logging verbosity | `INFO` |

## Processing Pipeline Details

### Order of Operations

1. **Discovery Phase**: Scan presentation for visual elements, filter out empty placeholders
2. **Classification Phase**: Categorize elements (images, shapes, groups) and determine processing approach
3. **Generation Phase**: Generate ALT text using AI model, applying content-aware prompts
4. **Resolution Phase**: Apply ALT text policies (preserve/smart/overwrite_all) 
5. **Injection Phase**: Write ALT text back to presentation with verification
6. **Validation Phase**: Confirm successful injection and accessibility compliance

### Smart Filtering Logic

**Automatically Filtered Out**:
- Empty PowerPoint placeholder text boxes ("Click to add title/text")
- Decorative shapes below minimum size threshold
- Hidden slides and elements
- Shapes marked as decorative in configuration

**Intelligently Processed**:
- Grouped shapes with semantic roll-up (describes group concept, marks children decorative)
- Charts and graphs as unified visual elements
- Technical diagrams with relationship awareness
- Photos and meaningful graphics

### Error Handling and Recovery

- **LLaVA Connection Issues**: Automatic retry with exponential backoff
- **File Lock Conflicts**: Queue-based processing with conflict resolution  
- **Corrupted Presentations**: Graceful failure with detailed error reporting
- **Partial Processing**: Resume capability from manifest checkpoints

## Troubleshooting

### Common Issues

**"All providers failed for text generation"**
- Check LLaVA service: `curl http://127.0.0.1:11434/api/tags`
- Verify model installed: `ollama list`
- Check endpoint in config.yaml

**"File not found" or Path Issues**
- Use absolute paths for files outside repository
- Check file permissions and write access
- Verify PowerPoint file isn't open in another application

**"No visual elements found"**
- Presentation may only contain text
- Check minimum shape area threshold in config
- Use `--verbose` to see filtering decisions

**Performance Issues**
- Reduce `max_shapes_per_slide` for complex presentations
- Increase `min_shape_area` to filter small decorative elements
- Use `--llava-include-shapes smart` instead of `all`

### Debug Mode

Enable comprehensive debugging:
```bash
python altgen.py --verbose --log-jsonl debug.jsonl process presentation.pptx
```

Review decisions in `debug.jsonl`:
```json
{"timestamp": "2024-01-01T12:00:00", "element": "slide_1_shape_3", "decision": "generate", "reason": "no_existing_alt"}
```

## Advanced Usage

### Batch Processing Patterns

**Process entire directory tree:**
```bash
find /path/to/presentations -name "*.pptx" -exec python altgen.py process {} \;
```

**Process with filtering:**
```bash
python altgen.py process "/presentations/*.pptx" --exclude "*template*" --exclude "*backup*"
```

**Resume interrupted batch:**
```bash
python altgen.py --resume batch_manifest.jsonl process /presentations/
```

### Integration with Document Management

**Generate accessibility reports:**
```bash
python altgen.py audit presentation.pptx > accessibility_report.txt
```

**Extract metadata for external systems:**
```bash
python pptx_alt_processor.py extract presentation.pptx --output metadata.json
```

**Inject from external ALT text sources:**
```bash
python pptx_alt_processor.py inject presentation.pptx --alt-text-file external_alt.json
```

### Quality Control Workflows  

**Review before deployment:**
```bash
# Generate review document
python altgen.py analyze presentation.pptx --output review.docx

# Process after human review
python altgen.py process presentation.pptx --alt-policy preserve
```

**A/B testing ALT text quality:**
```bash
# Generate with different modes
python altgen.py --mode presentation process test.pptx --output test_presentation.pptx
python altgen.py --mode scientific process test.pptx --output test_scientific.pptx
```

## Testing

Run the test suite:
```bash
# Full test suite
pytest

# Specific test categories
pytest tests/test_placeholder_filtering.py
pytest tests/test_alt_generation.py  
pytest tests/test_batch_processing.py

# With coverage report
pytest --cov=. --cov-report=html
```

## Performance Benchmarks

**Typical Processing Times** (on modern hardware with local LLaVA):
- Simple presentation (10 slides, 5 images): ~30 seconds
- Complex presentation (50 slides, 25 images): ~2-3 minutes  
- Scientific diagram (complex shapes): ~5-10 seconds per diagram
- Batch processing: ~20-40 presentations per hour

**Optimization Tips**:
- Use SSD storage for temp files
- Ensure adequate RAM (8GB+ recommended for large presentations)
- Consider GPU acceleration for LLaVA model
- Use `--dry-run` for testing without LLaVA calls

## Contributing

1. **Development Setup**:
   ```bash
   git clone https://github.com/your-repo/visualtext-pro
   cd visualtext-pro
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements-dev.txt
   ```

2. **Code Quality**:
   - Run `black .` for formatting
   - Run `flake8` for linting  
   - Add tests for new features
   - Update documentation

3. **Testing Changes**:
   ```bash
   # Test with sample presentations
   python altgen.py --dry-run process "Documents to Review/test*.pptx"
   
   # Run regression tests
   pytest tests/
   ```

## License and Attribution

This project uses several open-source components:
- **python-pptx**: PowerPoint file manipulation
- **Ollama + LLaVA**: Local AI vision model
- **python-docx**: Word document generation

See LICENSE file for full attribution and terms.

---

## Quick Reference Card

### Most Common Commands
```bash
# Quick start - process single file
python altgen.py process presentation.pptx

# Scientific content with preview
python altgen.py --mode scientific --dry-run process technical.pptx

# Batch with smart ALT policy  
python altgen.py --alt-policy smart process folder/

# Generate review document
python altgen.py analyze presentation.pptx --output review.docx
```

### Flag Priority (when multiple specified)
1. Command-line flags override config.yaml
2. `--profile` settings override defaults but not explicit flags
3. Environment variables override config.yaml defaults
4. Last specified flag wins for conflicting options

### File Extensions Supported
- **.pptx**: Modern PowerPoint (recommended)
- **.ppt**: Legacy PowerPoint (limited support)
- **.pdf**: Output format only (via `--export-pdf`)
- **.docx**: Review document format
- **.jsonl**: Manifest and logging format