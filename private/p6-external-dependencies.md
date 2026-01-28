# External Dependencies for ALT Text Generation

This document identifies all external dependencies involved in generating ALT text, including AI models, services, file system interactions, configuration values, and external tools.

---

## 1. AI/Vision Models

### 1.1 LLaVA (Large Language and Vision Assistant)

**Type**: Vision-language model  
**Location**: Local inference via Ollama API  
**Usage**: Primary AI model for generating descriptive ALT text from images

**How it's used:**
- Images are converted to base64-encoded PNG format
- Base64 image data is sent to LLaVA via HTTP POST request
- Prompt includes image description request and optional slide context
- LLaVA returns text description of the image
- Response is normalized and truncated to meet character limits

**Configuration**:
- Model name: `config.yaml` → `ai_providers.providers.llava.model` (default: `"llava"` or `"llava:latest"`)
- Base URL: `config.yaml` → `ai_providers.providers.llava.base_url` (default: `"http://127.0.0.1:11434"`)
- Endpoint: `config.yaml` → `ai_providers.providers.llava.endpoint` (default: `"/api/generate"`)

**Code locations**:
- `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`
- `shared/unified_alt_generator.py::FlexibleAltGenerator.generate_alt_text()`

---

## 2. Local/Remote Services

### 2.1 Ollama HTTP API

**Type**: Local HTTP service  
**Default URL**: `http://127.0.0.1:11434`  
**Protocol**: HTTP REST API  
**Purpose**: Provides access to LLaVA and other local AI models

**Endpoints Used**:

**`/api/generate`** (Primary endpoint)
- **Method**: POST
- **Purpose**: Generate ALT text from image
- **Request Format**: JSON payload with:
  - `model`: Model name (e.g., `"llava"`)
  - `prompt`: Text prompt string (not object)
  - `images`: Array of base64-encoded image strings
  - `stream`: `false` (non-streaming)
  - `options`: Deterministic generation options (temperature=0.0, seed=42)
- **Response Format**: JSON with `response` field containing generated text
- **Timeout**: Configurable (default: 60 seconds, max: 120 seconds)

**`/api/chat`** (Alternative endpoint)
- **Method**: POST
- **Purpose**: Chat-style API for generation
- **Request Format**: JSON payload with:
  - `model`: Model name
  - `messages`: Array of message objects (system + user)
  - `images`: Array of base64-encoded image strings
  - `stream`: `false`
  - `options`: Generation options
- **Response Format**: JSON with `message.content` field
- **Usage**: Used when `endpoint` config ends with `/api/chat`

**`/api/tags`** (Health check endpoint)
- **Method**: GET
- **Purpose**: Check service availability and list available models
- **Response Format**: JSON with `models` array
- **Usage**: Pre-flight validation, connectivity testing

**Code locations**:
- `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`
- `shared/llava_connectivity.py::HealthChecker.check_ollama_health()`
- `shared/llava_connectivity.py::HealthChecker.check_model_availability()`

**Connection Management**:
- Uses `requests.Session()` with connection pooling (`ConnectionPool` class)
- Retry strategy: 3 retries with exponential backoff
- Retriable status codes: `[429, 500, 502, 503, 504]`
- Circuit breaker pattern for failure handling
- Health check caching (TTL: 30 seconds)

---

## 3. File System Interactions

### 3.1 Input Files

**PPTX Files** (PowerPoint presentations)
- **Location**: `config.yaml` → `paths.input_folder` (default: `"Slides to Review"`)
- **Format**: `.pptx` (Office Open XML)
- **Usage**: Source presentations to process for ALT text generation
- **Read operations**: 
  - Load presentation structure
  - Extract images and shapes
  - Read existing ALT text
  - Extract slide text and notes
- **Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`

**Configuration Files**
- **Primary**: `config.yaml` (or `config.yml`, `config.json`)
- **Location**: Project root directory
- **Format**: YAML or JSON
- **Usage**: Loads all system configuration (paths, AI settings, prompts, etc.)
- **Code locations**: `shared/config_manager.py::ConfigManager._load_config()`

**Manifest Files** (JSON)
- **Location**: Artifact directories (`.alt_pipeline_{session_id}/`)
- **Files**: `visual_index.json`, `current_alt_by_key.json`, `generated_alt_by_key.json`, `final_alt_map.json`
- **Purpose**: Cache and track ALT text generation state
- **Code locations**: `shared/pipeline_artifacts.py::RunArtifacts`

**Cache Files**
- **ALT Cache**: `config.yaml` → `paths.alt_cache` (default: `"alt_cache.json"`)
- **Purpose**: Store generated ALT text for reuse across runs
- **Format**: JSON mapping image hashes to ALT text
- **Code locations**: `shared/alt_manifest.py::AltManifest`

### 3.2 Output Files

**Processed PPTX Files**
- **Location**: `config.yaml` → `paths.output_folder` (default: `"Reviewed Reports"`)
- **Format**: `.pptx` (modified with new ALT text)
- **Write operations**:
  - Inject ALT text into shape XML
  - Save modified presentation
- **Code locations**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**Review Documents** (DOCX)
- **Location**: Same as output folder
- **Naming**: `{original_name}_ALT_Review.docx`
- **Purpose**: Human-readable review document with ALT text comparisons
- **Code locations**: `shared/manifest_docx_builder.py`, `shared/docx_review_builder.py`

**Coverage Reports** (JSON)
- **Location**: Output folder
- **Naming**: `{original_name}_coverage_report.json`
- **Purpose**: Statistics on ALT text coverage and generation metrics
- **Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`

### 3.3 Temporary Files

**Image Files** (PNG, JPEG)
- **Location**: `config.yaml` → `paths.temp_folder` (default: `"Temp"`)
- **Purpose**: 
  - Normalized images for LLaVA processing
  - Rendered shape images
  - Thumbnails for manifest
- **Lifecycle**: Created during processing, cleaned up after completion
- **Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor._normalize_image_format()`

**Thumbnail Files** (JPEG)
- **Location**: Artifact directories → `thumbs/` subdirectory
- **Purpose**: Small preview images for manifest and review documents
- **Size**: Max width 200px (configurable via `output.thumbnail_max_width`)
- **Code locations**: `shared/manifest_processor.py::ManifestProcessor._create_thumbnail()`

**Crop Files** (PNG)
- **Location**: Artifact directories → `crops/` subdirectory
- **Purpose**: Extracted image regions for processing
- **Code locations**: `shared/manifest_processor.py::ManifestProcessor._create_crop()`

**Lock Files**
- **Location**: Same directory as input PPTX file
- **Naming**: `.{filename}.lock`
- **Purpose**: Prevent concurrent processing of same file
- **Format**: Plain text file containing process ID
- **Code locations**: `shared/file_lock_manager.py::FileLock`

### 3.4 Artifact Directories

**Session Artifacts**
- **Location**: `.alt_pipeline_{session_id}/`
- **Structure**:
  - `scan/` - Phase 1 scan artifacts
  - `generate/` - Phase 2 generation artifacts
  - `resolve/` - Phase 3 resolution artifacts
  - `thumbs/` - Thumbnail images
  - `crops/` - Cropped image regions
  - `selector/` - Selector manifest files
- **Lifecycle**: Created at pipeline start, cleaned up based on `artifact_management` config
- **Code locations**: `shared/pipeline_artifacts.py::RunArtifacts`

**Log Directories**
- **Location**: `config.yaml` → `logging.log_dir` (default: `logs/`)
- **Purpose**: Store processing logs
- **Files**: `{timestamp}_processing.log`, `{session_id}_session.log`
- **Code locations**: `shared/logging_config.py::LoggingConfig`

---

## 4. Configuration Values That Affect Behavior

### 4.1 AI Provider Configuration

**`ai_providers.providers.llava.base_url`**
- **Type**: String (URL)
- **Default**: `"http://127.0.0.1:11434"`
- **Effect**: Determines where Ollama API requests are sent
- **Usage**: Can be changed to point to remote Ollama instance

**`ai_providers.providers.llava.model`**
- **Type**: String
- **Default**: `"llava"` or `"llava:latest"`
- **Effect**: Specifies which LLaVA model variant to use
- **Usage**: Must match a model available in Ollama (`ollama list`)

**`ai_providers.providers.llava.endpoint`**
- **Type**: String (path)
- **Default**: `"/api/generate"`
- **Effect**: Determines API endpoint (generate vs chat)
- **Options**: `"/api/generate"` or `"/api/chat"`

**`ai_providers.providers.llava.timeout`**
- **Type**: Integer (seconds)
- **Default**: `60` (max: `120`)
- **Effect**: HTTP request timeout for generation calls
- **Usage**: Prevents hanging on slow/unresponsive models

**`ai_providers.providers.llava.seed`**
- **Type**: Integer
- **Default**: `42`
- **Effect**: Ensures deterministic generation (same image → same ALT text)
- **Usage**: Included in `options` payload for reproducible results

**`ai_providers.fallback_chain`**
- **Type**: Array of strings
- **Default**: `["llava"]`
- **Effect**: Order of providers to try if primary fails
- **Usage**: Currently only LLaVA supported, but extensible

**`provider_settings.max_fallback_attempts`**
- **Type**: Integer
- **Default**: `3`
- **Effect**: Maximum number of provider attempts before giving up
- **Usage**: Limits retry attempts across fallback chain

### 4.2 Prompt Configuration

**`prompts.default`**
- **Type**: String (template)
- **Default**: `"Describe this image in one sentence (up to 125 characters). Focus on essential visual content."`
- **Effect**: Base prompt sent to LLaVA for all images
- **Usage**: Can be customized for different use cases

**`prompts.anatomical`**
- **Type**: String (template)
- **Effect**: Specialized prompt for anatomical images
- **Usage**: Selected when image context suggests anatomical content

**`prompts.diagnostic`**
- **Type**: String (template)
- **Effect**: Specialized prompt for diagnostic/medical images
- **Usage**: Selected when image context suggests diagnostic content

**`prompts.chart`**, **`prompts.diagram`**, **`prompts.clinical_photo`**, **`prompts.unified_medical`**
- **Type**: String (templates)
- **Effect**: Specialized prompts for different image types
- **Usage**: Selected based on image classification or context

**Prompt Selection Logic**:
- Determined by `_determine_prompt_type()` in `core/pptx_processor.py`
- Based on image filename patterns, slide context, and shape type
- Falls back to `default` if no match

### 4.3 Path Configuration

**`paths.input_folder`**
- **Type**: String (directory path)
- **Default**: `"Slides to Review"`
- **Effect**: Where to look for input PPTX files
- **Usage**: Can be absolute or relative to project root

**`paths.output_folder`**
- **Type**: String (directory path)
- **Default**: `"Reviewed Reports"`
- **Effect**: Where to save processed PPTX files
- **Usage**: Created if doesn't exist

**`paths.temp_folder`**
- **Type**: String (directory path)
- **Default**: `"Temp"`
- **Effect**: Where to store temporary image files
- **Usage**: Created if doesn't exist, cleaned up after processing

**`paths.thumbnail_folder`**
- **Type**: String (directory path)
- **Default**: `"output/thumbnails"` (derived from output_folder)
- **Effect**: Where to store thumbnail images
- **Usage**: Used for manifest and review documents

**`paths.alt_cache`**
- **Type**: String (file path)
- **Default**: `"alt_cache.json"`
- **Effect**: Location of ALT text cache file
- **Usage**: Stores hash-to-ALT mappings for reuse

### 4.4 Output Configuration

**`output.char_limit`**
- **Type**: Integer
- **Default**: `125`
- **Effect**: Maximum characters in generated ALT text
- **Usage**: Hard limit enforced after generation
- **Code locations**: `shared/unified_alt_generator.py::FlexibleAltGenerator._shrink_to_char_limit()`

**`output.thumbnail_max_width`**
- **Type**: Integer (pixels)
- **Default**: `200`
- **Effect**: Maximum width for thumbnail images
- **Usage**: Controls thumbnail size in manifest/review docs

**`output.smart_truncate`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to use AI summarization for long ALT text
- **Usage**: If enabled, long ALT text is summarized via second LLaVA call

**`output.smart_truncate_prompt`**
- **Type**: String (template)
- **Default**: `"Rewrite the following as one complete sentence of at most 125 characters, ending with a period:"`
- **Effect**: Prompt for smart truncation summarization
- **Usage**: Only used if `smart_truncate: true`

**`output.max_summary_words`**
- **Type**: Integer
- **Default**: `30`
- **Effect**: Maximum words in summarized ALT text
- **Usage**: Fallback limit if smart truncation fails

### 4.5 Processing Configuration

**`pptx_processing.include_slide_notes`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to include slide notes in context sent to LLaVA
- **Usage**: Provides additional context for generation

**`pptx_processing.include_slide_text`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to include slide text in context sent to LLaVA
- **Usage**: Provides slide content context for generation

**`pptx_processing.max_context_length`**
- **Type**: Integer (characters)
- **Default**: `200`
- **Effect**: Maximum length of context text included in prompt
- **Usage**: Prevents prompt from becoming too long

**`pptx_processing.skip_decorative_images`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to skip ALT generation for decorative images
- **Usage**: Reduces unnecessary LLaVA calls

**`pptx_processing.decorative_size_threshold`**
- **Type**: Integer (pixels)
- **Default**: `50`
- **Effect**: Images smaller than this are considered decorative
- **Usage**: Heuristic for decorative detection

**`pptx_processing.convert_wmf_to_png`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to convert WMF/EMF vector images to PNG
- **Usage**: LLaVA cannot process WMF/EMF directly

### 4.6 Mode Configuration

**`alt_text_handling.mode`**
- **Type**: String (enum)
- **Options**: `"preserve"` or `"replace"`
- **Default**: `"preserve"`
- **Effect**: 
  - `preserve`: Keep existing ALT text if meaningful, only generate for empty/missing
  - `replace`: Always generate new ALT text, overwriting existing
- **Usage**: Controls whether existing ALT text is preserved

**`alt_text_handling.fallback_policy`**
- **Type**: String (enum)
- **Options**: `"none"`, `"doc-only"`, `"ppt-gated"`
- **Default**: `"none"`
- **Effect**: Controls when fallback ALT text is used
- **Usage**: Determines quality gates for ALT text injection

### 4.7 Decorative Detection Configuration

**`decorative_overrides.decorative_rules.contains`**
- **Type**: Array of strings
- **Default**: `["logo", "watermark", "border", "divider", "separator", "footer", "header", "bg", "line", "accent"]`
- **Effect**: Filename patterns that mark images as decorative
- **Usage**: Case-insensitive substring matching

**`decorative_overrides.decorative_rules.exact`**
- **Type**: Array of strings
- **Default**: `["utsw_logo.png", "utsw_logo.jpg", ...]`
- **Effect**: Exact filename matches that mark images as decorative
- **Usage**: Case-insensitive exact matching

**`decorative_overrides.never_decorative`**
- **Type**: Array of strings
- **Default**: `["anatomy", "pathology", "xray", "mri", "ct", "microscopy", "diagram", "chart", "graph"]`
- **Effect**: Filename patterns that prevent decorative marking
- **Usage**: Overrides decorative rules for educational content

### 4.8 File Locking Configuration

**`file_locking.enabled`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to use file locking to prevent concurrent access
- **Usage**: Prevents multiple processes from modifying same file

**`file_locking.timeout_seconds`**
- **Type**: Integer (seconds)
- **Default**: `30`
- **Effect**: Maximum time to wait for lock acquisition
- **Usage**: Prevents indefinite blocking

**`file_locking.retry_attempts`**
- **Type**: Integer
- **Default**: `3`
- **Effect**: Number of retry attempts if lock acquisition fails
- **Usage**: Handles transient lock conflicts

**`file_locking.retry_delay_seconds`**
- **Type**: Integer (seconds)
- **Default**: `2`
- **Effect**: Delay between retry attempts
- **Usage**: Prevents rapid retry loops

**`file_locking.cleanup_stale_locks`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to remove stale lock files on startup
- **Usage**: Handles locks from crashed processes

**`file_locking.stale_threshold_hours`**
- **Type**: Integer (hours)
- **Default**: `1`
- **Effect**: Age threshold for considering locks stale
- **Usage**: Locks older than this are removed

### 4.9 Artifact Management Configuration

**`artifact_management.auto_cleanup`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to automatically cleanup artifacts after processing
- **Usage**: Prevents disk space accumulation

**`artifact_management.keep_finals`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to keep final artifacts (final_alt_map.json, visual_index.json)
- **Usage**: Preserves important results even with cleanup enabled

**`artifact_management.max_age_days`**
- **Type**: Integer (days)
- **Default**: `7`
- **Effect**: Maximum age before auto-cleanup
- **Usage**: Artifacts older than this are removed

**`artifact_management.cleanup_on_success`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to cleanup temporary artifacts on successful processing
- **Usage**: Keeps only final results on success

**`artifact_management.cleanup_on_failure`**
- **Type**: Boolean
- **Default**: `false`
- **Effect**: Whether to cleanup artifacts on failure
- **Usage**: Preserves artifacts for debugging failed runs

**`artifact_management.warn_threshold_gb`**
- **Type**: Float (gigabytes)
- **Default**: `5.0`
- **Effect**: Warn if total artifact disk usage exceeds this
- **Usage**: Alerts to excessive disk usage

### 4.10 Batch Processing Configuration

**`batch_processing.default_max_workers`**
- **Type**: Integer
- **Default**: `1` (sequential)
- **Effect**: Number of concurrent file processing workers
- **Usage**: Controls parallelism in batch operations

**`batch_processing.max_lock_wait_seconds`**
- **Type**: Integer (seconds)
- **Default**: `30`
- **Effect**: Maximum time to wait for file locks during batch
- **Usage**: Prevents batch from hanging on locked files

**`batch_processing.file_timeout_seconds`**
- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Effect**: Timeout for individual file processing
- **Usage**: Prevents single slow file from blocking entire batch

**`batch_processing.stop_on_error_threshold`**
- **Type**: Float (0.0-1.0)
- **Default**: `0.5` (50%)
- **Effect**: Stop batch if failure rate exceeds this
- **Usage**: Prevents continuing with high failure rate

**`batch_processing.dry_run_validates_ollama`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to check LLaVA connectivity during dry-run
- **Usage**: Validates setup before actual batch run

### 4.11 Logging Configuration

**`logging.level`**
- **Type**: String (enum)
- **Options**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **Default**: `"INFO"`
- **Effect**: Minimum log level to output
- **Usage**: Controls verbosity

**`logging.log_to_file`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to write logs to files
- **Usage**: Enables persistent log storage

**`logging.show_prompts`**
- **Type**: Boolean
- **Default**: `false`
- **Effect**: Whether to log prompts sent to LLaVA
- **Usage**: Useful for debugging prompt issues

**`logging.show_responses`**
- **Type**: Boolean
- **Default**: `false`
- **Effect**: Whether to log full LLaVA responses
- **Usage**: Useful for debugging generation issues

**`logging.log_system_state`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to log system resource usage
- **Usage**: Helps diagnose performance issues

**`logging.log_configuration`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to log configuration at startup
- **Usage**: Helps verify configuration is loaded correctly

### 4.12 Pre-Flight Configuration

**`pre_flight.enabled`**
- **Type**: Boolean
- **Default**: `true`
- **Effect**: Whether to run connectivity tests before processing
- **Usage**: Validates LLaVA availability upfront

**`pre_flight.timeout`**
- **Type**: Integer (seconds)
- **Default**: `30`
- **Effect**: Timeout for pre-flight tests
- **Usage**: Prevents long startup delays

**`pre_flight.sample_image_path`**
- **Type**: String (file path) or `null`
- **Default**: `null`
- **Effect**: Path to test image for generation test
- **Usage**: If `null`, uses built-in minimal test image

**`pre_flight.test_prompt`**
- **Type**: String
- **Default**: `"Describe this test image in one sentence."`
- **Effect**: Prompt used for generation capability test
- **Usage**: Validates model can generate text

**`pre_flight.performance_baseline_threshold`**
- **Type**: Float (seconds)
- **Default**: `10.0`
- **Effect**: Warn if pre-flight takes longer than this
- **Usage**: Alerts to slow service performance

---

## 5. External Tools/Commands

### 5.1 Inkscape

**Purpose**: Convert WMF/EMF vector images to PNG  
**Command**: `inkscape`  
**Configuration**: `config.yaml` → `tools.inkscape` (default: `"inkscape"`)  
**Usage**: Called via `subprocess.run()` when WMF/EMF conversion is needed  
**Requirements**: Must be installed and available in PATH  
**Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor._convert_wmf_to_png_via_inkscape()`

**Command executed**:
```bash
inkscape --export-type=png --export-filename={output_path} {input_path}
```

**Fallback**: If Inkscape fails, tries LibreOffice conversion

### 5.2 LibreOffice

**Purpose**: Alternative WMF/EMF to PNG converter  
**Command**: `libreoffice` (or `soffice`)  
**Usage**: Fallback when Inkscape is unavailable  
**Requirements**: Must be installed and available in PATH  
**Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor._convert_wmf_to_png_via_libreoffice()`

**Command executed**:
```bash
libreoffice --headless --convert-to png --outdir {temp_dir} {input_path}
```

**Note**: Less reliable than Inkscape, used only as fallback

---

## 6. Python Libraries (External Dependencies)

### 6.1 Core Processing Libraries

**`python-pptx`** (v1.0.2)
- **Purpose**: Read and write PowerPoint (.pptx) files
- **Usage**: 
  - Load presentation structure
  - Extract images and shapes
  - Read/write ALT text in XML
  - Access slide text and notes
- **Code locations**: Used throughout `core/pptx_processor.py` and `core/pptx_alt_injector.py`

**`pillow`** (PIL, v11.3.0)
- **Purpose**: Image processing and manipulation
- **Usage**:
  - Open and normalize image formats
  - Convert RGB/RGBA/grayscale
  - Resize images for LLaVA
  - Create thumbnails
  - Render shapes to images
- **Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor._normalize_image_format()`

**`requests`** (v2.32.4)
- **Purpose**: HTTP client for Ollama API calls
- **Usage**:
  - POST requests to `/api/generate` or `/api/chat`
  - GET requests to `/api/tags` for health checks
  - Connection pooling and retry logic
- **Code locations**: `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`

**`lxml`** (via python-pptx)
- **Purpose**: XML manipulation for PPTX internals
- **Usage**:
  - Direct XML access for ALT text injection
  - XPath queries for shape properties
  - Decorative marking in XML
- **Code locations**: `core/pptx_alt_injector.py::PPTXAltTextInjector._write_alt_via_xml_fallback()`

### 6.2 Configuration and Data Libraries

**`PyYAML`** (v6.0.2)
- **Purpose**: Parse YAML configuration files
- **Usage**: Load `config.yaml` into Python dictionaries
- **Code locations**: `shared/config_manager.py::ConfigManager._load_config()`

**`json`** (standard library)
- **Purpose**: Parse/write JSON files
- **Usage**: 
  - Manifest files (visual_index.json, etc.)
  - Cache files (alt_cache.json)
  - Coverage reports
- **Code locations**: Used throughout for file I/O

### 6.3 System and Utility Libraries

**`psutil`** (>=5.9.0)
- **Purpose**: System resource monitoring
- **Usage**:
  - Check memory usage
  - Monitor disk space
  - CPU usage tracking
- **Code locations**: `shared/unified_alt_generator.py::FlexibleAltGenerator._log_system_state()`

**`platform`** (standard library)
- **Purpose**: Platform detection
- **Usage**: Identify OS for file locking and path handling
- **Code locations**: `shared/file_lock_manager.py` (Windows vs Unix locking)

**`subprocess`** (standard library)
- **Purpose**: Execute external commands
- **Usage**: 
  - Call Inkscape for WMF conversion
  - Call LibreOffice for WMF conversion
  - Execute batch processing subprocesses
- **Code locations**: `core/pptx_processor.py::PPTXAccessibilityProcessor._convert_wmf_to_png_via_inkscape()`

**`tempfile`** (standard library)
- **Purpose**: Create temporary files and directories
- **Usage**: 
  - Temporary image files for processing
  - Temporary directories for conversions
  - Session-specific artifact directories
- **Code locations**: Used throughout for temporary file management

**`pathlib.Path`** (standard library)
- **Purpose**: Cross-platform path handling
- **Usage**: All file path operations
- **Code locations**: Used throughout codebase

**`base64`** (standard library)
- **Purpose**: Encode images for API transmission
- **Usage**: Convert image bytes to base64 strings for Ollama API
- **Code locations**: `shared/unified_alt_generator.py::_b64_of_file()`

**`hashlib`** (standard library)
- **Purpose**: Generate image hashes for caching
- **Usage**: MD5 hashing of image data for duplicate detection
- **Code locations**: `shared/perceptual_hash.py`

**`time`** (standard library)
- **Purpose**: Timing and delays
- **Usage**: 
  - Measure generation time
  - Retry delays
  - Cache TTL calculations
- **Code locations**: Used throughout for timing operations

**`threading`** (standard library)
- **Purpose**: Background monitoring
- **Usage**: Background health check monitoring thread
- **Code locations**: `shared/llava_connectivity.py::LLaVAConnectivityManager.start_background_monitoring()`

**`logging`** (standard library)
- **Purpose**: Logging infrastructure
- **Usage**: All logging throughout codebase
- **Code locations**: Used throughout

### 6.4 Optional/Supporting Libraries

**`python-docx`** (v1.2.0)
- **Purpose**: Generate DOCX review documents
- **Usage**: Create Word documents with ALT text comparisons
- **Code locations**: `shared/manifest_docx_builder.py`, `shared/docx_review_builder.py`

**`numpy`** (v1.26.4)
- **Purpose**: Numerical operations (if needed)
- **Usage**: Image processing calculations (if used)
- **Code locations**: May be used in image processing utilities

**`tqdm`** (v4.67.1)
- **Purpose**: Progress bars
- **Usage**: Display progress during batch processing
- **Code locations**: `core/pptx_batch_processor.py` (if used)

**`pandas`** (v2.3.1)
- **Purpose**: Data analysis (if needed)
- **Usage**: Statistics and reporting (if used)
- **Code locations**: May be used in reporting utilities

**`opencv-python`** (v4.10.0.84)
- **Purpose**: Advanced image processing (if needed)
- **Usage**: Image analysis and manipulation (if used)
- **Code locations**: May be used in image processing utilities

**`ollama`** (v0.5.1)
- **Purpose**: Ollama Python client (if used)
- **Usage**: Alternative to direct HTTP requests
- **Code locations**: Not currently used (uses `requests` directly)

**`reportlab`** (>=4.0.0)
- **Purpose**: PDF generation (for PDF processing workflow)
- **Usage**: Recreate PDFs with accessibility features
- **Code locations**: `core/backup/pdf_accessibility_recreator.py` (if PDF workflow enabled)

**`PyMuPDF`** (>=1.23.0)
- **Purpose**: PDF manipulation (for PDF processing workflow)
- **Usage**: Extract images and text from PDFs
- **Code locations**: `core/backup/pdf_processor.py` (if PDF workflow enabled)

**`rich`** (>=13.0.0)
- **Purpose**: Rich text formatting (if used)
- **Usage**: Enhanced console output
- **Code locations**: May be used in CLI output

**`jsonschema`** (>=4.0.0)
- **Purpose**: JSON schema validation
- **Usage**: Validate manifest schemas
- **Code locations**: `shared/selector/selector.py` (if selector validation enabled)

---

## Summary: Dependency Categories

**Required for Core Functionality**:
1. Ollama service running locally (or accessible remotely)
2. LLaVA model installed in Ollama
3. `config.yaml` configuration file
4. Input PPTX files
5. Python libraries: `python-pptx`, `pillow`, `requests`, `PyYAML`

**Optional but Recommended**:
1. Inkscape (for WMF/EMF conversion)
2. File system write permissions (for output and temp directories)
3. Network connectivity (if using remote Ollama)

**Optional/Supporting**:
1. LibreOffice (fallback for WMF conversion)
2. Additional Python libraries for extended features
3. Logging directory write permissions

**Configuration-Driven**:
- All paths, timeouts, and behavior settings are configurable via `config.yaml`
- Defaults are provided but can be overridden
- Configuration is validated on startup
