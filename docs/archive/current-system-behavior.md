---
name: Document Current System Behavior
overview: Create comprehensive documentation describing the current, implemented behavior of VisualText Pro, focusing on what the system actually does today without suggesting improvements or future features.
todos:
  - id: doc-overview
    content: Write system overview section describing purpose, supported formats, and main technologies
    status: pending
  - id: doc-entry-points
    content: Document all CLI entry points (altgen.py, pptx_alt_processor.py, pptx_clean_processor.py, pptx_manifest_processor.py) with actual command structures and behaviors
    status: pending
  - id: doc-pipelines
    content: Document the three-phase pipeline workflow and batch processing implementation
    status: pending
  - id: doc-components
    content: "Document key components: config management, ALT generation, file locking, artifacts, selector"
    status: pending
  - id: doc-error-handling
    content: Document error handling mechanisms, recovery strategies, and error types
    status: pending
  - id: doc-data-flow
    content: Document data structures, manifest system, and artifact file formats
    status: pending
  - id: doc-config
    content: Document configuration system structure and all configurable options
    status: pending
  - id: doc-selection
    content: Document shape/image selection logic, filtering rules, and placeholder detection
    status: pending
  - id: doc-policies
    content: Document ALT text policies (preserve/smart/overwrite_all) and meaningfulness checks
    status: pending
  - id: doc-batch-details
    content: "Document batch processing details: sequential execution, file discovery, error handling"
    status: pending
  - id: doc-llava
    content: "Document LLaVA integration: endpoint, request/response format, retry logic, connectivity"
    status: pending
  - id: doc-review-docs
    content: Document review document generation process and format
    status: pending
isProject: false
---

# Documentation Plan: Current System Behavior

## Overview

Document the VisualText Pro codebase as it exists today, describing actual implementation behavior without suggesting improvements or assuming intent beyond what the code enforces.

## Documentation Structure

### 1. System Overview

- Purpose: Extract visual elements from PowerPoint presentations, generate ALT text using LLaVA, and inject descriptions back
- Supported formats: PPTX (primary), DOCX (limited), PDF (output only)
- Main technologies: python-pptx, Ollama/LLaVA, python-docx

### 2. Entry Points and CLI Tools

Document the actual CLI entry points and their current behavior:

- **altgen.py**: Unified dispatcher that routes commands to underlying processors
  - Commands: analyze, process, inject, review, audit, cleanup, batch, locks
  - Processor selection logic (original/clean/manifest)
  - Path validation and glob pattern handling
  - Batch processing integration
- **pptx_alt_processor.py**: Original full-featured processor
  - Direct processing with PDF export
  - Approval document generation
  - Shape processing controls
- **pptx_clean_processor.py**: Three-phase pipeline implementation
  - Phase 1: Scan
  - Phase 2: Generate  
  - Phase 3: Resolve
  - Review document generation
- **pptx_manifest_processor.py**: Manifest-driven workflow
  - Caching and consistency
  - Review-only mode
  - Manifest validation

### 3. Core Processing Workflows

Document the actual processing pipelines:

**Three-Phase Pipeline** (`shared/pipeline_phases.py`):

- Phase 1: Scan PPTX, extract visual_index and current_alt_by_key
- Phase 1.5: Render thumbnails and crops
- Phase 1.9: Run Smart Selector (generates selector_manifest.json)
- Phase 2: Generate ALT text for missing entries
- Phase 3: Resolve final_alt_map by merging current + generated

**Batch Processing** (`core/batch_processor.py`):

- Sequential file processing (default max_workers: 1)
- File discovery from folders/glob patterns
- Subprocess execution with timeout (configurable, default 300s)
- Error capture from both stdout and stderr
- Path sanitization using `shared/path_validator`

**Single File Processing** (`core/pptx_processor.py`):

- Visual element extraction
- LLaVA ALT text generation
- ALT text injection back into PPTX
- File locking to prevent concurrent access

### 4. Component Architecture

Document key components and their current responsibilities:

**Configuration Management** (`shared/config_manager.py`):

- YAML/JSON config loading with defaults
- Deep merge of user config over defaults
- Path validation and directory creation
- Config validation for required keys

**ALT Text Generation** (`shared/unified_alt_generator.py`):

- LLaVAProvider class for Ollama API calls
- Pre-flight validation
- Connectivity management with retry logic
- Prompt customization based on image type
- Response normalization (125 character limit)

**File Locking** (`shared/file_lock_manager.py`):

- Cross-platform locking (fcntl on Unix, msvcrt on Windows)
- Lock file creation with PID tracking
- Timeout and retry logic
- Stale lock detection

**Artifact Management** (`shared/pipeline_artifacts.py`):

- RunArtifacts class for managing pipeline outputs
- Context manager for automatic cleanup
- Artifact directory structure (.alt_pipeline_{session_id}/)
- Final artifact retention on success

**Smart Selector** (`shared/selector/selector.py`):

- Current stub implementation (v1.0-rc2)
- Generates selector_manifest.json with "include_atomic" decisions
- Schema validation against selector_manifest.schema.json
- Escalation strategy tracking

### 5. Error Handling and Recovery

Document actual error handling mechanisms:

**Recovery Strategies** (`shared/recovery_strategies.py`):

- SmartRecoveryManager coordinates multiple strategies
- ResourceCleanupStrategy: Cleans temp files
- LLaVAConnectionRecoveryStrategy: Retries with backoff
- FileAccessRecoveryStrategy: Handles file access errors
- ProcessingRetryStrategy: General retry logic

**Error Types** (`shared/processing_exceptions.py`):

- ProcessingError base class with structured error codes
- Recoverable vs non-recoverable errors
- Error categories: processing, service, file_access, validation

**Error Reporting** (`shared/error_reporter.py`):

- ProcessingResult class tracks success/failure
- StandardizedLogger for consistent logging
- Error aggregation and reporting

### 6. Data Flow and Artifacts

Document the actual data structures and flow:

**Manifest System** (`shared/alt_manifest.py`):

- AltManifest class as single source of truth
- AltManifestEntry with instance_key, content_key, image_hash
- Caching by image hash to avoid duplicate LLaVA calls
- Schema 2.0 with instance_key and shape_type

**Artifact Files**:

- visual_index.json: Complete catalog of visual elements
- current_alt_by_key.json: Existing ALT text from PPTX
- generated_alt_by_key.json: Newly generated ALT text
- final_alt_map.json: Merged result with decision metadata
- manifest.json: Schema 2.0 manifest
- selector_manifest.json: Smart selector decisions

**Artifact Cleanup** (`shared/artifact_cleaner.py`):

- Auto-cleanup based on config (auto_cleanup: true)
- Retention of final artifacts on success (keep_finals: true)
- Age-based cleanup (max_age_days: 7)
- Stale lock cleanup

### 7. Configuration System

Document actual configuration structure (`config.yaml`):

- alt_text_handling: mode, fallback_policy, max_workers
- paths: input_folder, output_folder, temp_folder, alt_cache
- ai_providers: llava endpoint, model, timeout, retry settings
- prompts: default, anatomical, diagnostic, chart, diagram, etc.
- decorative_overrides: rules for identifying decorative images
- output: char_limit (125), thumbnail settings, truncation
- selector: enabled, schema_path, placeholder patterns
- batch_processing: default_max_workers (1), timeout, manifest retention
- file_locking: enabled, timeout, retry settings
- artifact_management: auto_cleanup, keep_finals, max_age_days

### 8. Shape and Image Selection

Document actual filtering and selection logic:

**Shape Inclusion** (`shared/manifest_processor.py`):

- Strategies: off (pictures only), smart (heuristic), all
- Per-slide limit (max_shapes_per_slide: 5)
- Minimum area threshold (min_shape_area: "1%")
- Decorative shape detection (`shared/decorative_filter.py`)
- Image-like shape detection (`shared/shape_utils.py`)

**Placeholder Filtering**:

- Empty PowerPoint placeholder text boxes skipped
- Placeholder ALT text patterns detected
- Minimum meaningful ALT text length (15 chars)

### 9. ALT Text Policies

Document actual policy implementation:

- **preserve**: Keep existing ALT text, only add to elements without any
- **smart**: Replace low-quality/placeholder ALT text, preserve meaningful descriptions
- **overwrite_all**: Replace all existing ALT text

Meaningfulness check (`core/pptx_alt_injector.py`):

- Skips empty strings, "(none)", "n/a", "undefined", etc.
- Minimum meaningful length check

### 10. Batch Processing Details

Document actual batch behavior:

- Sequential processing (no parallelization by default)
- File discovery: recursive folder scan or glob patterns
- Path validation: sanitize_input_path prevents directory traversal
- Subprocess execution: python pptx_alt_processor.py process {file}
- Timeout handling: Configurable per-file timeout (default 300s)
- Error handling: Captures both stdout and stderr, continues on failure
- Progress reporting: Prints "Processing X of Y: filename.pptx"

### 11. LLaVA Integration

Document actual LLaVA interaction:

- Endpoint: [http://127.0.0.1:11434/api/generate](http://127.0.0.1:11434/api/generate) (default)
- Model: "llava" (configurable)
- Request format: JSON with prompt, images (base64), options
- Response parsing: Extracts "response" field
- Pre-flight validation: Tests connectivity before processing
- Retry logic: Configurable retry attempts with exponential backoff
- Connectivity manager: Health checks, circuit breaker pattern
- Configurable unavailable modes: fail_fast, skip_generation, defer_generation (see config resilience)
- Batch offline behavior: When provider is offline, batch can abort (exit 2) or inject placeholders per --offline-mode and --placeholder-scope (see README)

### 12. Review Document Generation

Document actual review document creation:

- DOCX format using python-docx
- Includes thumbnails, current ALT, generated ALT, final ALT
- Visual index with slide numbers and image positions
- Approval workflow support (`approval/approval_pipeline.py`)

## Implementation Notes

- Document actual code paths and file locations
- Include specific function names and classes
- Note default values from config.yaml
- Describe actual error messages and behaviors
- Include actual data structure formats (JSON schemas)
- Document actual CLI flag behaviors and defaults

