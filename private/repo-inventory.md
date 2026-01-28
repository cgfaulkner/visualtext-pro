# Repository Inventory: VisualText Pro

This document provides a comprehensive inventory of the VisualText Pro repository as it exists today, describing the structure, modules, entry points, and organization without proposing changes.

---

## 1. Repository Overview

### Repository Name
**visualtext-pro**

### High-Level Purpose
Based on code analysis, this repository provides:

- **PowerPoint (PPTX) Processing**: Extracts visual elements (images, shapes, charts) from PowerPoint presentations, generates alternative text using AI vision models (LLaVA), and injects ALT text back into PPTX files for accessibility compliance.

- **Document Processing**: Processes PowerPoint presentations and optionally generates Word (DOCX) review documents for human oversight of generated ALT text.

- **Batch Processing**: Supports sequential processing of multiple PPTX files with file locking, error recovery, and progress tracking.

- **Manifest-Driven Workflows**: Provides manifest-based processing pipelines that cache results and enable resume capabilities.

- **PDF Processing** (archived): Contains archived code for PDF accessibility processing, though this appears to be legacy functionality stored in `core/backup/`.

The system focuses on generating meaningful ALT text for visual elements while filtering placeholder content and handling complex grouped shapes intelligently.

---

## 2. Directory Structure

```
visualtext-pro/
├── .claude_docs/              # Documentation artifacts (Claude-generated)
│   ├── artifact_integration_verification.md
│   ├── batch_processing_implementation.md
│   ├── bugfix_absolute_path_validation.md
│   ├── file_locking_implementation.md
│   └── phase_2b1_enhancement_complete.md
│
├── .github/                   # GitHub Actions workflows
│   └── workflows/
│       ├── python-app.yml
│       └── validate-selector-schema.yml
│
├── approval/                  # Approval workflow module (Python package)
│   ├── __init__.py
│   ├── approval_pipeline.py
│   ├── docx_alt_review.py
│   └── llava_adapter.py
│
├── core/                      # Core processing pipelines (Python package)
│   ├── __init__.py            # Empty (package marker)
│   ├── backup/                # Archived/backup processors
│   │   ├── pdf_accessibility_recreator.py
│   │   ├── pdf_alt_injector.py
│   │   ├── pdf_context_extractor.py
│   │   ├── pdf_processor.py
│   │   ├── pptx_alt_injector.py
│   │   └── pptx_processor.py
│   ├── batch_processor.py     # Batch processing orchestration
│   ├── docx_processor.py      # DOCX file processing
│   ├── pptx_alt_injector.py   # ALT text injection into PPTX
│   ├── pptx_batch_processor.py # Batch PPTX processing
│   └── pptx_processor.py      # Main PPTX processing logic
│
├── docs/                      # Project documentation
│   ├── alt-text-generation-workflow.md
│   ├── batch-operational-resilience.md
│   ├── batch-processing-audit.md
│   ├── batch-processing-remediation-plan.md
│   ├── entry-points-and-call-flow.md
│   ├── execution-path-trace.md
│   ├── external-dependencies.md
│   ├── image-processing-flow.md
│   ├── repo-inventory.md      # This file
│   ├── slide-by-slide-processing.md
│   ├── smart-selector-contract.md
│   └── workflow-assumptions-and-limitations.md
│
├── documents_to_review/       # Sample/test files
│   ├── test1_llava_latest_backup test names_coverage_report.json
│   └── test1_llava_latest_backup test names.pptx
│
├── old_project/               # Legacy code archive
│   ├── batch_pptx_processor_linked.py
│   ├── concepts.py
│   ├── config_manager.py
│   ├── config.yaml
│   ├── llava_alt_generator.py
│   ├── pptx_alt.py
│   └── unified_alt_generator.py
│
├── schemas/                   # JSON schemas
│   └── selector_manifest.schema.json
│
├── shared/                    # Shared utilities and infrastructure (Python package)
│   ├── __init__.py            # Empty (package marker)
│   ├── selector/              # Smart selector subpackage
│   │   ├── __init__.py
│   │   ├── selector.py
│   │   └── types.py
│   ├── alt_cleaner.py
│   ├── alt_manifest.py
│   ├── alt_text_reader.py
│   ├── artifact_cleaner.py
│   ├── batch_manifest.py
│   ├── batch_queue.py
│   ├── concept_detector.py
│   ├── config_manager.py
│   ├── decorative_filter.py
│   ├── docx_review_builder.py
│   ├── error_reporter.py
│   ├── fallback_policies.py
│   ├── file_lock_manager.py
│   ├── llava_connectivity.py
│   ├── lock_monitor.py
│   ├── logging_config.py
│   ├── manifest_docx_builder.py
│   ├── manifest_injector.py
│   ├── manifest_processor.py
│   ├── path_validator.py
│   ├── perceptual_hash.py
│   ├── pipeline_artifacts.py
│   ├── pipeline_phases.py
│   ├── processing_exceptions.py
│   ├── recovery_strategies.py
│   ├── resource_manager.py
│   ├── shape_renderer.py
│   ├── shape_utils.py
│   ├── sync_validator.py
│   └── unified_alt_generator.py
│
├── tools/                     # Utility scripts
│   └── validate_selector_manifest.py
│
├── .flake8                    # Flake8 linting configuration
├── .gitignore                 # Git ignore patterns
├── AGENTS.md                  # Agent instructions and coding guidelines
├── altgen.py                  # Unified CLI dispatcher (main entry point)
├── analyze_pdf_structure.py   # PDF analysis utility script
├── config.yaml                # Main configuration file
├── extract_content_streams.py # PDF content stream extraction utility
├── LICENSE                    # License file
├── pptx_alt_processor.py      # Original full-featured processor
├── pptx_clean_processor.py     # Three-phase pipeline processor
├── pptx_manifest_processor.py # Manifest-driven processor
├── README.md                  # Project README
└── requirements.txt           # Python dependencies
```

### Top-Level Directory Descriptions

**`core/`**: Contains the main processing pipelines and orchestrators. Includes PPTX processing logic, ALT text injection, batch processing, and DOCX processing. The `backup/` subdirectory contains archived PDF and PPTX processors.

**`shared/`**: Contains shared utilities, infrastructure, and reusable components. Includes configuration management, manifest handling, pipeline phases, artifact management, error handling, file locking, and AI provider integration. The `selector/` subdirectory contains smart selector functionality.

**`approval/`**: Contains approval workflow functionality for generating review documents and managing ALT text approval processes.

**`docs/`**: Contains project documentation including workflow descriptions, execution traces, dependency documentation, and technical specifications.

**`old_project/`**: Contains legacy code from previous versions. Files appear to be older implementations of processors and generators.

**`core/backup/`**: Contains archived/backup versions of processors. Includes PDF processing code and older PPTX processors.

**`schemas/`**: Contains JSON schema definitions for manifest validation.

**`tools/`**: Contains utility scripts for validation and analysis.

**`.claude_docs/`**: Contains documentation artifacts generated during development.

**`.github/`**: Contains GitHub Actions workflows for CI/CD and validation.

---

## 3. Python Packages & Modules

### Python Packages (with `__init__.py`)

**`core/`** (Python package)
- **Purpose**: Core processing pipelines and orchestration
- **Key Modules**:
  - `pptx_processor.py`: Main PPTX processing logic (`PPTXAccessibilityProcessor` class)
  - `pptx_alt_injector.py`: ALT text injection into PPTX XML (`PPTXAltTextInjector` class)
  - `pptx_batch_processor.py`: Batch PPTX file processing (`PPTXBatchProcessor` class)
  - `docx_processor.py`: DOCX file processing
  - `batch_processor.py`: Batch processing orchestration
- **Subdirectory**: `backup/` - Contains archived processors (not imported by main code)

**`shared/`** (Python package)
- **Purpose**: Shared utilities, infrastructure, and reusable components
- **Key Modules**:
  - `config_manager.py`: Configuration loading and management (`ConfigManager` class)
  - `unified_alt_generator.py`: AI provider integration (`FlexibleAltGenerator`, `LLaVAProvider` classes)
  - `manifest_processor.py`: Manifest-based processing (`ManifestProcessor` class)
  - `pipeline_phases.py`: Three-phase pipeline orchestration (`run_pipeline()` function)
  - `pipeline_artifacts.py`: Artifact management (`RunArtifacts` class)
  - `llava_connectivity.py`: LLaVA connectivity hardening (`LLaVAConnectivityManager` class)
  - `file_lock_manager.py`: File locking (`FileLock` class)
  - `recovery_strategies.py`: Error recovery (`SmartRecoveryManager` class)
  - `processing_exceptions.py`: Structured exception types
  - `alt_manifest.py`: Manifest data structures (`AltManifest` class)
  - `manifest_injector.py`: Manifest-based injection
  - `manifest_docx_builder.py`: DOCX review document generation from manifest
  - `docx_review_builder.py`: DOCX review document generation from artifacts
  - `path_validator.py`: Path validation and sanitization
  - `resource_manager.py`: Resource validation and temp file management
  - `shape_renderer.py`: Shape-to-image rendering (`ShapeRenderer` class)
  - `shape_utils.py`: Shape utility functions
  - `decorative_filter.py`: Decorative image detection
  - `alt_text_reader.py`: ALT text reading utilities
  - `alt_cleaner.py`: ALT text cleaning/normalization
  - `fallback_policies.py`: Fallback ALT text policies
  - `perceptual_hash.py`: Image hashing utilities
  - `batch_manifest.py`: Batch manifest management
  - `batch_queue.py`: Batch queue management
  - `concept_detector.py`: Concept detection from notes
  - `error_reporter.py`: Error reporting and result objects
  - `logging_config.py`: Logging configuration
  - `lock_monitor.py`: Lock file monitoring
  - `artifact_cleaner.py`: Artifact cleanup utilities
  - `sync_validator.py`: Synchronization validation
- **Subpackage**: `selector/` - Smart selector functionality (`selector.py`, `types.py`)

**`approval/`** (Python package)
- **Purpose**: Approval workflow functionality
- **Key Modules**:
  - `approval_pipeline.py`: Approval pipeline orchestration
  - `docx_alt_review.py`: DOCX review document generation
  - `llava_adapter.py`: Legacy LLaVA adapter (`LegacyLLaVAAdapter` class)

### Standalone Scripts (Not in Packages)

**Root-level executable scripts:**
- `altgen.py`: Unified CLI dispatcher
- `pptx_alt_processor.py`: Original full-featured processor
- `pptx_clean_processor.py`: Three-phase pipeline processor
- `pptx_manifest_processor.py`: Manifest-driven processor
- `analyze_pdf_structure.py`: PDF structure analysis utility
- `extract_content_streams.py`: PDF content stream extraction utility

**Tools:**
- `tools/validate_selector_manifest.py`: Manifest schema validation utility

### Legacy/Archived Areas

**`old_project/`**: Contains legacy code from previous versions
- `pptx_alt.py`: Legacy PPTX processor
- `unified_alt_generator.py`: Legacy ALT generator
- `llava_alt_generator.py`: Legacy LLaVA generator
- `batch_pptx_processor_linked.py`: Legacy batch processor
- `config_manager.py`: Legacy config manager
- `concepts.py`: Legacy concept detection

**`core/backup/`**: Contains archived/backup processors
- `pptx_processor.py`: Archived PPTX processor
- `pptx_alt_injector.py`: Archived PPTX injector
- `pdf_processor.py`: Archived PDF processor
- `pdf_alt_injector.py`: Archived PDF injector
- `pdf_accessibility_recreator.py`: PDF recreation workflow
- `pdf_context_extractor.py`: PDF context extraction

**Evidence of legacy patterns:**
- Code comments reference "legacy" compatibility fields
- `shared/unified_alt_generator.py` has "legacy callers" fallback imports
- `shared/pipeline_artifacts.py` normalizes "legacy and new" payloads
- `shared/manifest_processor.py` updates "legacy compatibility fields"
- `.flake8` excludes `old_project` from linting

---

## 4. CLI / Entry Points

### Primary Entry Points

**1. `altgen.py`** (Unified CLI Dispatcher)
- **Purpose**: Routes commands to appropriate processor scripts
- **Commands**:
  - `process <file>`: Processes single file or batch (routes to processor)
  - `analyze <file>`: Generates review document only
  - `inject <file>`: Injects ALT text from manifest
  - `batch <target>`: Batch processes files
  - `cleanup`: Cleans up old artifacts
  - `locks`: Shows/manages file locks
- **Processor Selection**: Selects processor based on flags (`--use-manifest`, `--use-clean`, etc.)
- **Routes To**: `pptx_manifest_processor.py`, `pptx_clean_processor.py`, or `pptx_alt_processor.py`

**2. `pptx_alt_processor.py`** (Original Full-Featured Processor)
- **Purpose**: Complete PPTX processing with all features
- **Commands**:
  - `process <file>`: Full processing pipeline (extract → generate → inject)
  - `batch-process <dir>`: Batch processing
  - `extract <file>`: Extract images only
  - `inject <file>`: Inject from JSON mapping
- **Pipeline**: `PPTXAltProcessor.process_single_file()` → `PPTXAccessibilityProcessor.process_pptx()` → `PPTXAltTextInjector.inject_alt_text_from_mapping()`

**3. `pptx_clean_processor.py`** (Three-Phase Pipeline)
- **Purpose**: Clean three-phase pipeline with JSON artifacts
- **Commands**:
  - `process <file>`: Full three-phase pipeline
  - `inject <file>`: Inject from final_alt_map.json
  - `review`: Generate review document from artifacts
- **Pipeline**: `run_pipeline()` → Phase 1 (scan) → Phase 2 (generate) → Phase 3 (resolve) → Injection

**4. `pptx_manifest_processor.py`** (Manifest-Driven Workflow)
- **Purpose**: Manifest-based processing with caching and resume capability
- **Commands**:
  - `process <file>`: Manifest-based processing
  - `inject <file>`: Inject from manifest
  - `review`: Generate review from manifest
  - `validate <manifest>`: Validate manifest schema
- **Pipeline**: `ManifestProcessor.process()` → Phase 1 (discover) → Phase 2 (render/generate) → Phase 4 (LLaVA generation) → Injection

### Secondary Entry Points

**5. `core/pptx_processor.py`** (Direct Core Module)
- **Purpose**: Can be executed directly for core processing
- **Function**: `main()` - Direct PPTX processing without wrapper
- **Usage**: Typically called via `pptx_alt_processor.py`, but can be executed directly

**6. `core/pptx_alt_injector.py`** (Direct Injection Module)
- **Purpose**: Can be executed directly for ALT text injection
- **Function**: `main()` - Direct injection from JSON mapping
- **Usage**: Typically called via processors, but can be executed directly

**7. `core/pptx_batch_processor.py`** (Direct Batch Module)
- **Purpose**: Can be executed directly for batch processing
- **Function**: `main()` - Direct batch processing
- **Usage**: Typically called via `altgen.py` or `pptx_alt_processor.py`

**8. `core/docx_processor.py`** (DOCX Processing)
- **Purpose**: DOCX file processing
- **Function**: `main()` - Processes DOCX files for ALT text

### Utility Scripts

**9. `tools/validate_selector_manifest.py`**
- **Purpose**: Validates selector manifest JSON against schema
- **Usage**: `python tools/validate_selector_manifest.py <manifest> [--schema <schema>]`

**10. `analyze_pdf_structure.py`**
- **Purpose**: Analyzes PDF structure (utility script)
- **Usage**: Standalone script for PDF analysis

**11. `extract_content_streams.py`**
- **Purpose**: Extracts PDF content streams (utility script)
- **Usage**: Standalone script for PDF content extraction

---

## 5. Core Processing Pipelines

### Pipeline 1: Original Full-Featured Pipeline

**Orchestrator**: `pptx_alt_processor.py::PPTXAltProcessor.process_single_file()`

**Flow**:
1. File validation and resource checking
2. File lock acquisition
3. Artifact directory creation
4. `PPTXAccessibilityProcessor.process_pptx()`:
   - Visual element extraction
   - ALT text generation (via `FlexibleAltGenerator`)
   - ALT text mapping creation
5. `PPTXAltTextInjector.inject_alt_text_from_mapping()`:
   - ALT text injection into PPTX XML
   - Presentation save
6. Cleanup and lock release

**Modules Involved**:
- `core/pptx_processor.py` (extraction and generation)
- `shared/unified_alt_generator.py` (AI provider integration)
- `core/pptx_alt_injector.py` (injection)

### Pipeline 2: Three-Phase Clean Pipeline

**Orchestrator**: `shared/pipeline_phases.py::run_pipeline()`

**Flow**:
1. **Phase 1 (Scan)**: `phase1_scan()`
   - Calls `ManifestProcessor.phase1_discover_and_classify()`
   - Creates `visual_index.json` and `current_alt_by_key.json`
2. **Phase 1.5 (Render Thumbnails)**: `phase1_5_render_thumbnails()`
   - Calls `ManifestProcessor.phase2_render_and_generate_crops()`
   - Creates thumbnails and crops
3. **Phase 1.9 (Selector)**: `phase1_9_run_selector()`
   - Calls `selector.run_selector()`
   - Creates selector manifest
4. **Phase 2 (Generate)**: `phase2_generate()`
   - Calls `FlexibleAltGenerator.generate_alt_text()`
   - Creates `generated_alt_by_key.json`
5. **Phase 3 (Resolve)**: `phase3_resolve()`
   - Merges current + generated ALT text
   - Creates `final_alt_map.json`
6. **Injection**: `inject_from_map()`
   - Calls `PPTXAltTextInjector.inject_alt_text_from_mapping()`

**Modules Involved**:
- `shared/pipeline_phases.py` (orchestration)
- `shared/manifest_processor.py` (manifest processing)
- `shared/pipeline_artifacts.py` (artifact management)
- `shared/unified_alt_generator.py` (AI generation)
- `core/pptx_alt_injector.py` (injection)

### Pipeline 3: Manifest-Driven Pipeline

**Orchestrator**: `shared/manifest_processor.py::ManifestProcessor.process()`

**Flow**:
1. **Phase 1**: `phase1_discover_and_classify()`
   - Discovers visual elements
   - Classifies shapes
   - Creates manifest entries
2. **Phase 2**: `phase2_render_and_generate_crops()`
   - Renders shapes to images
   - Creates thumbnails and crops
3. **Phase 4**: `phase4_single_pass_llava_generation()`
   - Generates ALT text via LLaVA
   - Updates manifest entries
4. **Injection**: `inject_from_manifest()`
   - Calls `manifest_injector.inject_from_manifest()`
   - Uses manifest as single source of truth

**Modules Involved**:
- `shared/manifest_processor.py` (orchestration)
- `shared/alt_manifest.py` (manifest data structures)
- `shared/unified_alt_generator.py` (AI generation)
- `shared/manifest_injector.py` (manifest-based injection)

### Pipeline 4: Batch Processing Pipeline

**Orchestrator**: `core/batch_processor.py::PPTXBatchProcessor.process_batch()`

**Flow**:
1. File discovery (`discover_files()`)
2. Sequential processing (`_process_single()` for each file):
   - Executes `pptx_alt_processor.py process <file>` as subprocess
   - Captures stdout/stderr
   - Tracks success/failure
3. Progress reporting
4. Summary statistics

**Modules Involved**:
- `core/batch_processor.py` (orchestration)
- `pptx_alt_processor.py` (executed as subprocess)
- `shared/batch_manifest.py` (batch manifest management)

### Format-Specific Processing

**PPTX Processing**:
- **Extraction**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_all_visual_elements()`
- **Generation**: `shared/unified_alt_generator.py::FlexibleAltGenerator.generate_alt_text()`
- **Injection**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**DOCX Processing**:
- **Processor**: `core/docx_processor.py::process_docx()`
- **Review Generation**: `shared/docx_review_builder.py::generate_alt_review_doc()`
- **Manifest Review**: `shared/manifest_docx_builder.py::generate_review_from_manifest()`

**PDF Processing** (Archived):
- **Processors**: `core/backup/pdf_processor.py`, `core/backup/pdf_alt_injector.py`
- **Recreation**: `core/backup/pdf_accessibility_recreator.py`
- **Context Extraction**: `core/backup/pdf_context_extractor.py`
- **Status**: Appears to be archived/legacy functionality

---

## 6. Shared Infrastructure

### Configuration Handling

**Module**: `shared/config_manager.py`
- **Class**: `ConfigManager`
- **Purpose**: Loads and manages configuration from YAML/JSON files
- **Features**:
  - Merges user config with defaults
  - Validates required keys
  - Creates necessary directories
  - Provides getter methods for paths, prompts, settings
  - Supports CLI overrides
- **Config File**: `config.yaml` (primary), also supports `config.yml`, `config.json`

### Pipeline Phases

**Module**: `shared/pipeline_phases.py`
- **Function**: `run_pipeline()` - Orchestrates three-phase pipeline
- **Phases**:
  - `phase1_scan()`: Visual element discovery and classification
  - `phase1_5_render_thumbnails()`: Thumbnail and crop generation
  - `phase1_9_run_selector()`: Smart selector execution
  - `phase2_generate()`: ALT text generation
  - `phase3_resolve()`: ALT text resolution and merging
- **Artifact Integration**: Uses `RunArtifacts` for artifact management

### Artifact Management

**Module**: `shared/pipeline_artifacts.py`
- **Class**: `RunArtifacts`
- **Purpose**: Manages paths and cleanup for pipeline artifacts
- **Features**:
  - Creates session-specific directories (`.alt_pipeline_{session_id}/`)
  - Manages paths to JSON artifacts (visual_index, current_alt, generated_alt, final_alt_map)
  - Context manager for automatic cleanup
  - Normalizes legacy and new artifact formats
- **Artifact Files**:
  - `visual_index.json`: Catalog of visual elements
  - `current_alt_by_key.json`: Existing ALT text mapping
  - `generated_alt_by_key.json`: Generated ALT text mapping
  - `final_alt_map.json`: Final ALT text decisions

**Module**: `shared/artifact_cleaner.py`
- **Functions**: `cleanup_old_artifacts()`, `get_artifact_disk_usage()`
- **Purpose**: Cleans up old artifact directories based on age and disk usage

### Error Handling

**Module**: `shared/processing_exceptions.py`
- **Purpose**: Defines structured exception types
- **Base Class**: `ProcessingError`
- **Exception Types**:
  - `ValidationError`: Input validation errors
  - `ProcessingContentError`: Content processing errors
  - `ServiceError`: External service errors
  - `LLaVAConnectionError`: LLaVA connectivity errors
  - `LLaVAGenerationError`: LLaVA generation errors
  - `PPTXParsingError`: PPTX parsing errors
  - `ImageExtractionError`: Image extraction errors
  - `InjectionError`: ALT text injection errors
- **Features**: Error codes, categories, recovery hints, recoverable flags

**Module**: `shared/recovery_strategies.py`
- **Class**: `SmartRecoveryManager`
- **Purpose**: Implements smart error recovery logic
- **Recovery Strategies**:
  - `LLaVAConnectionRecoveryStrategy`: LLaVA connection recovery
  - `FileAccessRecoveryStrategy`: File access recovery
  - `ResourceCleanupRecoveryStrategy`: Resource cleanup
  - `GeneralRetryRecoveryStrategy`: General retry logic
- **Context Manager**: `smart_recovery_context()` for automatic recovery

**Module**: `shared/error_reporter.py`
- **Classes**: `ProcessingResult`, `StandardizedLogger`
- **Purpose**: Standardized error reporting and result objects
- **Features**: Result tracking, error aggregation, logging

### Logging

**Module**: `shared/logging_config.py`
- **Class**: `LoggingConfig`
- **Purpose**: Centralized logging configuration
- **Features**:
  - Configurable log levels
  - File and console logging
  - Session-specific log files
  - ALT text mapping logging

### File Locking

**Module**: `shared/file_lock_manager.py`
- **Class**: `FileLock`
- **Purpose**: Cross-platform file locking to prevent concurrent access
- **Features**:
  - Timeout and blocking options
  - Stale lock cleanup
  - Platform-specific implementation (Windows vs Unix)
- **Usage**: Acquired before processing, released after completion

**Module**: `shared/lock_monitor.py`
- **Functions**: Lock monitoring and status checking
- **Purpose**: Monitor and manage lock files

### Resource Management

**Module**: `shared/resource_manager.py`
- **Class**: `ResourceContext`
- **Purpose**: Manages temporary files and resource validation
- **Features**:
  - Temporary file creation and tracking
  - Temporary directory management
  - Automatic cleanup on context exit
  - Resource validation (memory, disk space)

**Module**: `shared/path_validator.py`
- **Functions**: `sanitize_input_path()`, `validate_output_path()`
- **Purpose**: Path validation and sanitization
- **Features**:
  - Security validation (prevents directory traversal)
  - Absolute path validation
  - Path normalization

### Manifest Management

**Module**: `shared/alt_manifest.py`
- **Class**: `AltManifest`
- **Purpose**: Manifest data structures and management
- **Features**:
  - Manifest entry storage
  - Hash-based caching
  - Entry lookup and retrieval
  - Manifest serialization (JSONL format)

**Module**: `shared/manifest_processor.py`
- **Class**: `ManifestProcessor`
- **Purpose**: Manifest-based processing orchestration
- **Features**:
  - Phase 1: Discovery and classification
  - Phase 2: Rendering and crop generation
  - Phase 4: LLaVA generation
  - Shape inclusion policies (off/smart/all)

**Module**: `shared/manifest_injector.py`
- **Functions**: `inject_from_manifest()`, `validate_manifest_for_injection()`
- **Purpose**: Manifest-based ALT text injection
- **Features**: Reads from manifest, injects into PPTX

**Module**: `shared/manifest_docx_builder.py`
- **Functions**: `generate_review_from_manifest()`
- **Purpose**: Generates DOCX review documents from manifest
- **Features**: Reads manifest, creates Word document with ALT text comparisons

### Batch Management

**Module**: `shared/batch_manifest.py`
- **Class**: `BatchManifest`
- **Purpose**: Batch processing manifest management
- **Features**: Tracks batch progress, enables resume capability

**Module**: `shared/batch_queue.py`
- **Class**: `BatchQueue`
- **Purpose**: Batch queue management
- **Features**: Queue operations, persistence

---

## 7. External Dependencies (Conceptual)

### AI / Vision Models

**LLaVA (Large Language and Vision Assistant)**
- **Access Method**: Local inference via Ollama HTTP API
- **Default Endpoint**: `http://127.0.0.1:11434/api/generate`
- **Model Name**: `"llava"` or `"llava:latest"` (configurable)
- **Integration**: `shared/unified_alt_generator.py::LLaVAProvider`
- **Connectivity**: `shared/llava_connectivity.py::LLaVAConnectivityManager`
- **Assumptions**: Ollama service running locally, LLaVA model installed

### External Tools / Services

**Ollama HTTP API**
- **Service**: Local HTTP service (default: `http://127.0.0.1:11434`)
- **Endpoints Used**:
  - `/api/generate`: Primary generation endpoint
  - `/api/chat`: Alternative chat endpoint
  - `/api/tags`: Health check and model listing
- **Protocol**: HTTP REST API with JSON payloads
- **Integration**: `requests` library for HTTP calls

**Inkscape** (Optional)
- **Purpose**: Convert WMF/EMF vector images to PNG
- **Command**: `inkscape` (must be in PATH)
- **Usage**: Called via `subprocess.run()` when WMF/EMF conversion needed
- **Fallback**: LibreOffice if Inkscape unavailable

**LibreOffice** (Optional, Fallback)
- **Purpose**: Alternative WMF/EMF to PNG converter
- **Command**: `libreoffice` or `soffice` (must be in PATH)
- **Usage**: Fallback when Inkscape unavailable

### File System Dependencies

**Input Files**:
- PPTX files (PowerPoint presentations)
- DOCX files (Word documents, for review generation)
- Configuration files (`config.yaml`, `config.yml`, `config.json`)

**Output Files**:
- Modified PPTX files (with injected ALT text)
- DOCX review documents
- JSON artifacts (visual_index, alt mappings, manifests)
- Coverage reports (JSON)

**Temporary Files**:
- Normalized image files (PNG format)
- Rendered shape images
- Thumbnail images
- Cropped image regions

**Lock Files**:
- Format: `.{filename}.lock`
- Location: Same directory as input file
- Purpose: Prevent concurrent processing

**Artifact Directories**:
- Format: `.alt_pipeline_{session_id}/`
- Structure: `scan/`, `generate/`, `resolve/`, `thumbs/`, `crops/`, `selector/`
- Lifecycle: Created per run, cleaned up based on config

**Cache Files**:
- ALT cache: `alt_cache.json` (configurable path)
- Manifest files: `{filename}_manifest.jsonl`

**Log Directories**:
- Location: `logs/` (configurable)
- Files: `{timestamp}_processing.log`, `{session_id}_session.log`

---

## 8. Redundancy / Overlap Observations

### Duplicate Processors

**PPTX Processors**:
- `core/pptx_processor.py` (active)
- `core/backup/pptx_processor.py` (archived)
- **Observation**: Archived version exists in `backup/` subdirectory

**PPTX Injectors**:
- `core/pptx_alt_injector.py` (active)
- `core/backup/pptx_alt_injector.py` (archived)
- **Observation**: Archived version exists in `backup/` subdirectory

**PDF Processors**:
- `core/backup/pdf_processor.py` (archived)
- `core/backup/pdf_alt_injector.py` (archived)
- `core/backup/pdf_accessibility_recreator.py` (archived)
- `core/backup/pdf_context_extractor.py` (archived)
- **Observation**: All PDF processing code is in `backup/` directory, suggesting it's not actively used

### Duplicate Generators

**ALT Generators**:
- `shared/unified_alt_generator.py` (active)
- `old_project/unified_alt_generator.py` (legacy)
- `old_project/llava_alt_generator.py` (legacy)
- **Observation**: Legacy versions exist in `old_project/`

### Duplicate Config Managers

**Config Managers**:
- `shared/config_manager.py` (active)
- `old_project/config_manager.py` (legacy)
- **Observation**: Legacy version exists in `old_project/`

### Duplicate Review Builders

**DOCX Review Builders**:
- `shared/docx_review_builder.py` (artifact-based)
- `shared/manifest_docx_builder.py` (manifest-based)
- `approval/docx_alt_review.py` (approval workflow)
- **Observation**: Three different implementations for generating review documents

### Overlapping Functionality

**Manifest Processing**:
- `shared/manifest_processor.py` (main manifest processor)
- `shared/manifest_injector.py` (manifest-based injection)
- `shared/manifest_docx_builder.py` (manifest-based review)
- `shared/alt_manifest.py` (manifest data structures)
- **Observation**: Multiple modules handle manifest operations, but appear to be complementary rather than duplicate

**Batch Processing**:
- `core/batch_processor.py` (generic batch orchestration)
- `core/pptx_batch_processor.py` (PPTX-specific batch processing)
- **Observation**: Two batch processors with potentially overlapping responsibilities

**Shape Utilities**:
- `shared/shape_utils.py` (shape utility functions)
- `shared/shape_renderer.py` (shape rendering)
- **Observation**: Complementary modules, not duplicates

### Legacy vs New Patterns

**Legacy Patterns** (in `old_project/`):
- Single-file processors (`pptx_alt.py`)
- Direct LLaVA integration (`llava_alt_generator.py`)
- Simple batch processing (`batch_pptx_processor_linked.py`)

**New Patterns** (in `core/` and `shared/`):
- Modular architecture with separate processors and injectors
- Provider-based AI integration (`FlexibleAltGenerator`)
- Structured error handling (`ProcessingError` hierarchy)
- Artifact-based workflows (`RunArtifacts`)
- Manifest-driven workflows (`AltManifest`, `ManifestProcessor`)

**Evidence of Transition**:
- Code comments reference "legacy compatibility"
- `shared/unified_alt_generator.py` has "legacy callers" fallback imports
- `shared/pipeline_artifacts.py` normalizes "legacy and new" payloads
- `.flake8` excludes `old_project` from linting

---

## 9. Notes for Future Cleanup

**Observational Notes**: The following observations are based on repository structure and code organization. These are observations only, not prescriptions for action.

### Archived Code Areas

**`core/backup/` Directory**:
- Contains archived PPTX and PDF processors
- PDF processing code appears to be legacy functionality
- No evidence of active imports from `backup/` directory in main codebase
- May warrant review to determine if code should be removed or if PDF functionality should be restored

**`old_project/` Directory**:
- Contains legacy implementations of processors and generators
- Files appear to be from previous versions
- Excluded from linting (`.flake8` configuration)
- May warrant archival or removal if functionality is fully replaced

### Duplicate Entry Points

**Multiple PPTX Processors**:
- `pptx_alt_processor.py` (original)
- `pptx_clean_processor.py` (three-phase)
- `pptx_manifest_processor.py` (manifest-driven)
- All three processors provide similar functionality with different architectures
- `altgen.py` dispatcher routes to appropriate processor
- May warrant consolidation or clearer documentation of when to use each

### Overlapping Review Document Generation

**Three DOCX Review Builders**:
- `shared/docx_review_builder.py` (artifact-based)
- `shared/manifest_docx_builder.py` (manifest-based)
- `approval/docx_alt_review.py` (approval workflow)
- All generate review documents but from different data sources
- May warrant consolidation or clearer separation of concerns

### Configuration Management

**Single Active Config Manager**:
- `shared/config_manager.py` is the active implementation
- `old_project/config_manager.py` is legacy
- Legacy version may be removable if functionality is fully replaced

### Batch Processing

**Two Batch Processors**:
- `core/batch_processor.py` (generic)
- `core/pptx_batch_processor.py` (PPTX-specific)
- Relationship and usage patterns may warrant clarification

### Import Patterns

**Path Manipulation in Scripts**:
- Multiple scripts manipulate `sys.path` to add `shared/` and `core/` directories
- Pattern: `sys.path.insert(0, str(project_root / "shared"))`
- Suggests packages may not be properly installed as Python packages
- May warrant proper package installation setup

### Documentation Organization

**Documentation Files**:
- Multiple documentation files in `docs/` with various naming conventions
- Some files prefixed with `p1-`, `p2-`, etc.
- Some files use descriptive names
- May warrant standardization of naming conventions

### Test Files

**Sample Files**:
- `documents_to_review/` contains sample PPTX files
- May warrant separate `tests/` or `samples/` directory organization

### Utility Scripts

**Standalone Utilities**:
- `analyze_pdf_structure.py` and `extract_content_streams.py` appear to be one-off utilities
- May warrant organization in `tools/` directory or separate utilities area

---

## Summary Statistics

**Total Python Files**: ~61 Python files
- Root-level scripts: 7
- Core package: 9 files (including backup)
- Shared package: 30+ files
- Approval package: 4 files
- Tools: 1 file
- Old project: 7 files

**Active Processors**: 3 (pptx_alt_processor, pptx_clean_processor, pptx_manifest_processor)
**Archived Processors**: 6 (in core/backup/)
**Legacy Processors**: 7 (in old_project/)

**Main Packages**: 3 (core, shared, approval)
**Subpackages**: 2 (shared/selector, core/backup)

**Entry Points**: 11 executable scripts with `main()` functions
**CLI Dispatchers**: 1 (altgen.py)

**Documentation Files**: 12+ markdown files in `docs/`
**Configuration Files**: 1 primary (`config.yaml`), 1 legacy (`old_project/config.yaml`)
