# Full Execution Path Trace: PPTX ALT Text Processing

## Happy Path: Single File Processing via pptx_alt_processor.py

### Entry Point and Initialization

1. **`pptx_alt_processor.py::main()`** - CLI entry point
   - Parses command-line arguments
   - Validates input file path using `shared/path_validator::sanitize_input_path()`
   - Creates `PPTXAltProcessor` instance

2. **`pptx_alt_processor.py::PPTXAltProcessor.__init__()`**
   - Initializes `ConfigManager` from config file
   - Creates `PPTXAccessibilityProcessor` instance
   - Creates `PPTXAltTextInjector` instance
   - Sets up logging and artifact management

3. **`pptx_alt_processor.py::PPTXAltProcessor.process_single_file()`**
   - Validates input file exists
   - Validates system resources via `shared/resource_manager::validate_system_resources()`
   - Acquires file lock via `shared/file_lock_manager::FileLock.acquire()`
   - Creates `RunArtifacts` context manager if artifacts enabled
   - Enters smart recovery context via `shared/recovery_strategies::smart_recovery_context()`

### Visual Element Extraction

4. **`core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`**
   - Validates PPTX file exists
   - Creates resource context via `shared/resource_manager::ResourceContext`
   - Calls `_extract_all_visual_elements()`

5. **`core/pptx_processor.py::PPTXAccessibilityProcessor._extract_all_visual_elements()`**
   - Loads presentation via `pptx::Presentation(pptx_path)`
   - Iterates through slides
   - For each slide:
     - Extracts slide text via `_extract_slide_text()` (if enabled)
     - Extracts slide notes via `_extract_slide_notes()` (if enabled)
     - Calls `_extract_visual_elements_from_shapes()`

6. **`core/pptx_processor.py::PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()`**
   - Recursively processes shapes
   - For each shape:
     - Checks if picture shape → creates `PPTXVisualElement` with image data
     - Checks if group shape → recursively processes child shapes
     - Checks if chart shape → extracts chart images
     - Checks if shape has image fill → extracts fill images
     - Checks if OLE object → extracts embedded images
     - If visual shape with no image → renders shape to image via `_render_shape_to_image()`
   - Returns list of `PPTXVisualElement` objects

7. **`core/pptx_processor.py::PPTXAccessibilityProcessor._process_group_alt_rollup()`**
   - Processes group shapes for ALT text roll-up
   - Creates parent ALT text elements for groups
   - Marks child elements as decorative

### ALT Text Generation

8. **`core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`** (continued)
   - Iterates through visual elements
   - For each element, calls `_generate_alt_text_for_visual_element()`

9. **`core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_visual_element()`**
   - **If element is image:**
     - Creates temporary `PPTXImageInfo` object
     - Calls `_generate_alt_text_for_image_with_validation()`
   - **Else (shape element):**
     - Calls `_generate_alt_text_for_shape_element()`

10. **`core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`**
    - Writes image data to temporary file
    - Gets prompt from config via `ConfigManager.get_prompt()`
    - Calls `FlexibleAltGenerator.generate_alt_text()`

11. **`shared/unified_alt_generator.py::FlexibleAltGenerator.generate_alt_text()`**
    - Builds prompt (custom or from config)
    - Determines provider chain (default: ['llava'])
    - Iterates through providers in fallback chain
    - For each provider, calls `provider.generate_alt_text()`

12. **`shared/unified_alt_generator.py::LLaVAProvider.generate_alt_text()`**
    - Runs pre-flight validation via `_run_pre_flight_validation()`
    - **If connectivity manager available:**
      - Calls `connectivity_manager.execute_with_hardening()`
    - **Else:**
      - Calls `_execute_generation_request()` directly

13. **`shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`**
    - Reads image file and converts to base64
    - Builds prompt text via `_build_prompt_text()`
    - Constructs JSON payload for Ollama API
    - Makes HTTP POST request to `http://127.0.0.1:11434/api/generate`
    - Parses response (extracts "response" field)
    - Normalizes response via `_normalize_to_complete_sentences()`
    - Returns `(generation_result, metadata)` tuple

14. **`shared/unified_alt_generator.py::FlexibleAltGenerator.generate_alt_text()`** (continued)
    - Extracts ALT text from generation result
    - Records usage statistics
    - Returns ALT text string

15. **`core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`** (continued)
    - Checks for LLaVA errors via `_is_llava_error()`
    - **If error detected:**
      - Calls `_handle_llava_error_with_fallback()`
    - Normalizes ALT text via `_normalize_alt()`
    - Returns `(alt_text, failure_reason)` tuple

16. **`core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`** (continued)
    - Stores ALT text in `alt_text_mapping` dictionary
    - **If generation fails:**
      - For shapes/text elements: Creates fallback description via `_create_enhanced_fallback_description()`
      - Checks bypass conditions via `_check_element_bypass()`
      - Composes ALT text via `_compose_alt()`
    - Tracks statistics (processed, failed, etc.)

### ALT Text Injection

17. **`core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`** (continued)
    - After all elements processed, calls `PPTXAltTextInjector.inject_alt_text_from_mapping()`

18. **`core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`**
    - Loads presentation via `pptx::Presentation(pptx_path)`
    - Builds image identifier mapping via `_build_image_identifier_mapping()`
    - Iterates through ALT text mappings
    - For each mapping:
      - Determines ALT decision via `_determine_alt_decision()`
      - Chooses candidate text via `_choose_candidate()`
      - **If mode is 'preserve' and existing ALT is meaningful:**
        - Skips injection (preserves existing)
      - **Else:**
        - Calls `_inject_alt_text_single()`

19. **`core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt_text_single()`**
    - Normalizes ALT text via `_normalize_alt_universal()`
    - Checks if should replace via `_should_replace_alt_text_normalized()`
    - Writes ALT text to shape via `_write_alt_text_to_shape()`
    - Records write statistics

20. **`core/pptx_alt_injector.py::PPTXAltTextInjector._write_alt_text_to_shape()`**
    - Gets shape XML element
    - Finds or creates `<a:desc>` element
    - Sets ALT text value
    - Registers write via `_register_write()`

21. **`core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`** (continued)
    - After all injections, saves presentation via `presentation.save(output_path)`
    - Synchronizes statistics via `_sync_legacy_statistics()`
    - Returns result dictionary with statistics

### Cleanup and Completion

22. **`core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`** (continued)
    - Calculates processing times
    - Returns result dictionary

23. **`pptx_alt_processor.py::PPTXAltProcessor.process_single_file()`** (continued)
    - Marks result as success
    - Exits artifact context manager (triggers cleanup)
    - Releases file lock
    - Returns result dictionary

24. **`pptx_alt_processor.py::main()`** (continued)
    - Prints success message
    - Returns exit code 0

---

## Alternate Paths

### Path A: Batch Processing via altgen.py

1. **`altgen.py::main()`**
   - Detects directory/glob pattern
   - Calls `run_batch()` function

2. **`altgen.py::run_batch()`**
   - Creates `PPTXBatchProcessor` instance
   - Calls `processor.discover_files()` to find PPTX files
   - Calls `processor.process_batch(files)`

3. **`core/batch_processor.py::PPTXBatchProcessor.process_batch()`**
   - Iterates through files sequentially
   - For each file, calls `_process_single()`

4. **`core/batch_processor.py::PPTXBatchProcessor._process_single()`**
   - Executes subprocess: `python pptx_alt_processor.py process <file>`
   - Captures stdout/stderr
   - Returns success/failure result

5. **Returns to step 1** of happy path (pptx_alt_processor.py::main())

### Path B: Three-Phase Pipeline via pptx_clean_processor.py

1. **`pptx_clean_processor.py::main()`**
   - Parses arguments
   - Calls `cmd_process()`

2. **`pptx_clean_processor.py::cmd_process()`**
   - Loads `ConfigManager`
   - Creates `FlexibleAltGenerator`
   - Calls `run_pipeline()`

3. **`shared/pipeline_phases.py::run_pipeline()`**
   - Creates `RunArtifacts` context manager
   - **Phase 1:** Calls `phase1_scan()` → `ManifestProcessor.phase1_discover_and_classify()`
   - **Phase 1.5:** Calls `phase1_5_render_thumbnails()` → `ManifestProcessor.phase2_render_and_generate_crops()`
   - **Phase 1.9:** Calls `phase1_9_run_selector()` → `selector.run_selector()`
   - **Phase 2:** Calls `phase2_generate()` → `FlexibleAltGenerator.generate_alt_text()`
   - **Phase 3:** Calls `phase3_resolve()` → Merges current + generated ALT text
   - Calls `inject_from_map()` → `PPTXAltTextInjector.inject_alt_text_from_mapping()`

### Path C: Error Handling and Recovery

**If LLaVA connection fails:**
- `LLaVAProvider.generate_alt_text()` → Creates degradation response via `_create_degradation_response()`
- Returns fallback ALT text instead of failing

**If generation returns error:**
- `PPTXAccessibilityProcessor._generate_alt_text_for_visual_element()` → Detects error via `_is_llava_error()`
- Calls `_handle_llava_error_with_fallback()` → Creates descriptive fallback

**If shape has no image:**
- `PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()` → Renders shape to image via `_render_shape_to_image()`
- Creates `PPTXVisualElement` with rendered image

**If file lock acquisition fails:**
- `PPTXAltProcessor.process_single_file()` → Catches `LockError`
- Marks result as failure
- Returns without processing

**If system resources insufficient:**
- `PPTXAltProcessor.process_single_file()` → Validates resources
- Creates `InsufficientMemoryError` or `InsufficientDiskSpaceError`
- Marks result as failure
- Returns without processing

**If injection fails:**
- `PPTXAltTextInjector.inject_alt_text_from_mapping()` → Catches exceptions
- Logs error
- Continues with next element
- Returns partial success result

### Path D: Preserve Mode (Existing ALT Text)

**If mode is 'preserve' and existing ALT is meaningful:**
- `PPTXAltTextInjector._determine_alt_decision()` → Returns 'preserved_existing'
- `PPTXAltTextInjector.inject_alt_text_from_mapping()` → Skips injection
- Increments 'preserved_existing' statistic

### Path E: Review Document Generation

**If --review-doc or --approval-doc-only flag:**
- `pptx_clean_processor.py::cmd_process()` → Calls `generate_alt_review_doc()`
- `shared/docx_review_builder.py::generate_alt_review_doc()`
  - Loads visual_index.json
  - Loads current_alt_by_key.json
  - Loads final_alt_map.json
  - Creates DOCX document via `python-docx`
  - Adds thumbnails and ALT text comparisons
  - Saves review document

---

## Key Conditional Branches

### Shape Type Detection
- **Picture shape:** Extract image blob directly
- **Group shape:** Recursively process children
- **Chart shape:** Extract chart images
- **Shape with fill:** Extract fill image
- **OLE object:** Extract embedded content
- **Visual shape (no image):** Render to image

### ALT Text Generation Strategy
- **Image element:** Generate via LLaVA with image
- **Shape element:** Generate descriptive text or render to image
- **Connector/line:** Create direct description (bypass LLaVA)

### Injection Decision Logic
- **Mode 'preserve':** Keep existing meaningful ALT text
- **Mode 'replace':** Overwrite all ALT text
- **No existing ALT:** Write generated ALT text
- **Existing + Generated:** Choose based on quality score

### Error Recovery
- **LLaVA error:** Use fallback description
- **Connection failure:** Use degradation response
- **Generation empty:** Use shape description fallback
- **Injection failure:** Log and continue

---

## Module Dependencies

**Core Processing:**
- `pptx_alt_processor.py` → `core/pptx_processor.py` → `shared/unified_alt_generator.py`
- `pptx_alt_processor.py` → `core/pptx_alt_injector.py`

**Supporting Modules:**
- `shared/config_manager.py` - Configuration management
- `shared/path_validator.py` - Path sanitization
- `shared/file_lock_manager.py` - File locking
- `shared/resource_manager.py` - Resource validation
- `shared/recovery_strategies.py` - Error recovery
- `shared/pipeline_artifacts.py` - Artifact management

**External Dependencies:**
- `pptx` (python-pptx) - PowerPoint file manipulation
- `requests` - HTTP client for LLaVA API
- `PIL` (Pillow) - Image processing and rendering
