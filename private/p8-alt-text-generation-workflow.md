# ALT Text Generation Workflow: Complete Description

This document provides a concise but complete description of the ALT text generation workflow as implemented today, structured from entry point through to final outputs.

---

## Entry Point

### Primary Entry Points

**1. `altgen.py::main()`** (Unified CLI Dispatcher)
- Command: `python altgen.py process <file>`
- Routes to appropriate processor script via `ProcessorDispatcher`
- For batch operations: Calls `PPTXBatchProcessor.process_batch()`

**2. `pptx_alt_processor.py::main()`** (Full-Featured Processor)
- Command: `python pptx_alt_processor.py process <file>`
- Creates `PPTXAltProcessor` instance
- Calls `process_single_file()` → `PPTXAccessibilityProcessor.process_pptx()`

**3. `pptx_clean_processor.py::main()`** (Three-Phase Pipeline)
- Command: `python pptx_clean_processor.py process <file>`
- Calls `run_pipeline()` → Three-phase workflow (scan, generate, resolve)

**4. `pptx_manifest_processor.py::main()`** (Manifest-Driven)
- Command: `python pptx_manifest_processor.py process <file>`
- Calls `ManifestProcessor.process()` → Manifest-based workflow

**All paths converge on:**
- `FlexibleAltGenerator.generate_alt_text()` → LLaVA API calls
- `PPTXAltTextInjector.inject_alt_text_from_mapping()` → XML injection

---

## Per-File Flow

### Step 1: File Validation and Setup

**Function**: `pptx_alt_processor.py::PPTXAltProcessor.process_single_file()`

**Actions:**
1. Validates input file exists (`Path(pptx_path).exists()`)
2. Validates system resources (`validate_system_resources()` - checks 200MB memory, 500MB disk)
3. Acquires file lock (`FileLock.acquire()` - prevents concurrent processing)
4. Creates artifact directories (`RunArtifacts.create_for_run()` - session-specific `.alt_pipeline_{id}/`)
5. Enters smart recovery context (`smart_recovery_context()` - error recovery strategies)

**Outputs:**
- Lock file: `.{filename}.lock`
- Artifact directory: `.alt_pipeline_{session_id}/`
- Resource context: Temporary file manager

### Step 2: Presentation Loading

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`

**Actions:**
1. Loads presentation: `Presentation(pptx_path)` (python-pptx library)
2. Creates resource context (`ResourceContext` - manages temporary files)
3. Calls `_extract_all_visual_elements(pptx_path)`

**Outputs:**
- Presentation object (in-memory)
- Resource context for temp file management

### Step 3: Visual Element Extraction

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_all_visual_elements()`

**Actions:**
1. Iterates through all slides in presentation
2. For each slide:
   - Extracts slide text (if enabled)
   - Extracts slide notes (if enabled)
   - Calls `_extract_visual_elements_from_shapes()` recursively
3. Processes group ALT text roll-up (`_process_group_alt_rollup()`)

**Outputs:**
- `visual_elements` list: `List[PPTXVisualElement]` containing all visual elements
- Each element includes: shape reference, slide_idx, shape_idx, element_type, image_data, dimensions, slide_text context

### Step 4: ALT Text Generation

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()` (continued)

**Actions:**
1. Iterates through `visual_elements` list
2. For each element:
   - Calls `_generate_alt_text_for_visual_element()`
   - Stores result in `alt_text_mapping` dictionary
3. Handles generation failures with fallback descriptions

**Outputs:**
- `alt_text_mapping` dictionary: `Dict[str, Dict]` mapping element keys to ALT text and metadata
- Statistics: processed count, failed count, generation time

### Step 5: ALT Text Injection

**Function**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**Actions:**
1. Loads presentation again (for injection)
2. Builds image identifier mapping (`_build_image_identifier_mapping()`)
3. Matches element keys from mapping to shapes in presentation
4. For each match:
   - Determines ALT decision (`_determine_alt_decision()`)
   - Normalizes ALT text (`_normalize_alt_universal()`)
   - Injects into XML (`_write_alt_text_to_shape()`)
5. Saves presentation: `presentation.save(output_path)`

**Outputs:**
- Modified PPTX file with ALT text in XML structure
- Injection statistics: preserved count, written count, skipped count

### Step 6: Cleanup

**Function**: `pptx_alt_processor.py::PPTXAltProcessor.process_single_file()` (finally block)

**Actions:**
1. Marks artifacts as success (if processing succeeded)
2. Exits artifact context manager (triggers cleanup)
3. Releases file lock
4. Returns result dictionary

**Outputs:**
- Cleaned up temporary files (if cleanup enabled)
- Released lock file
- Result dictionary with statistics

---

## Per-Slide Flow

### Slide Processing Sequence

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_all_visual_elements()`

**For each slide:**

**1. Slide Access**
- Reads: `slide.shapes` (collection of top-level shapes)
- Reads: `slide_idx` (zero-based index)
- Reads: `slide.notes_slide` (if available)

**2. Slide Text Extraction** (if `include_slide_text: true`)
- Reads: `shape.text` from all shapes on slide
- Transforms: Joins all text with single spaces
- Retains: `slide_text` string (truncated to 200 chars max)

**3. Slide Notes Extraction** (if `include_slide_notes: true`)
- Reads: `slide.notes_slide.notes_text_frame.text`
- Transforms: Strips whitespace, prefixes with "Notes: "
- Retains: `slide_notes` string (combined with slide_text)

**4. Shape Recursive Processing**
- For each shape in `slide.shapes`:
  - Reads: `shape.shape_type`, `shape.id`, `shape.name`, dimensions (EMU), position (EMU)
  - Reads: `shape.image.blob` (if picture), `shape.fill` (if image fill), `shape.text_frame.text` (if text)
  - Transforms: Converts EMU to pixels (`int(emu / 914400 * 96)`), computes MD5 hash of image data
  - Creates: `PPTXVisualElement` object with all extracted data
  - Retains: Element added to `visual_elements` list

**5. Group Processing** (after all slides processed)
- For each group shape:
  - Analyzes child shapes (`_analyze_group_children_for_rollup()`)
  - Decides parent ALT text (`_decide_group_alt_rollup()`)
  - Creates parent `PPTXVisualElement` with generated ALT text
  - Marks children as decorative (if applicable)

**6. ALT Text Generation** (after all slides processed)
- For each visual element:
  - Generates ALT text via LLaVA (if image) or fallback (if shape)
  - Stores in `alt_text_mapping[element_key]`

**7. ALT Text Injection** (after all generation complete)
- Reloads presentation
- For each slide:
  - Matches element keys to shapes
  - Injects ALT text into shape XML
  - Marks decorative children (if group parent)

**Data Retained Per Slide:**
- Slide index
- Slide text context (truncated)
- List of visual elements with metadata
- ALT text mappings for each element
- Modified XML structure with injected ALT text

---

## Per-Image Flow

### Image Detection

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()`

**Detection Methods** (checked in order):
1. **Direct picture**: `hasattr(shape, 'image') and shape.image` → Classified as `"image"`
2. **Image fill**: `shape.fill.type == MSO_FILL_TYPE.PICTURE` → Extracts fill image
3. **Chart images**: `hasattr(shape, 'chart')` → Extracts chart plot/area fills
4. **OLE objects**: XML inspection → Extracts embedded images
5. **Shape rendering**: `_should_render_shape_to_image()` → Renders visual shapes to PNG

**Result**: Creates `PPTXVisualElement` with `element_type="image"` and `image_data` bytes

### Image Data Extraction

**Location**: `core/pptx_processor.py::PPTXVisualElement.__init__()`

**For direct picture shapes:**
- Reads: `shape.image.blob` (raw bytes), `shape.image.ext` (extension), `shape.image.filename` (if available)
- Transforms: Computes MD5 hash (`get_image_hash(image_data)`)
- Retains: `image_data` (bytes), `filename` (generated or original), `image_hash` (MD5 string)

**For rendered shapes:**
- Reads: Shape dimensions, fill, line, text properties
- Transforms: Renders to PNG using PIL (`Image.new()`, `ImageDraw.Draw()`, shape-specific rendering)
- Retains: PNG bytes, `is_rendered=True` flag, hash of rendered image

### Image Format Normalization

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._normalize_image_format()`

**Actions:**
1. Detects problematic formats: `.tiff`, `.tif`, `.wmf`, `.emf` (by filename or header bytes)
2. Opens image with PIL: `Image.open(io.BytesIO(image_data))`
3. Converts color mode: RGBA/CMYK → RGB, grayscale → L
4. Resizes if needed: If `max(original_size) > 1600px`, resizes maintaining aspect ratio
5. Saves as PNG: `img.save(output_buffer, format='PNG', optimize=True)`
6. **For WMF/EMF**: Attempts external conversion via Inkscape/LibreOffice; if fails, uses contextual fallback (no API call)

**Outputs:**
- Normalized PNG bytes (or original data if normalization fails for non-problematic formats)
- Temporary file path (written to disk for API call)

### Existing ALT Text Reading

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._read_current_alt()`

**When**: During injection phase (not during generation)

**Methods:**
1. Direct property: `shape.descr` (if available)
2. XML attribute: `shape._element.find(".//p:cNvPr").get('descr', '')`
3. XPath search: `read_existing_alt(shape)` - searches multiple XML paths

**Result**: Existing ALT text string (or empty string if none)

### AI/Vision Model Invocation

**Location**: `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`

**Pre-flight validation:**
- Checks LLaVA connectivity (if connectivity manager available)
- Caches validation result (TTL: 300 seconds)
- **If validation fails**: Returns degradation response (no API call)

**API request construction:**
1. Reads temp image file: `Path(image_path).read_bytes()`
2. Base64 encodes: `base64.b64encode(image_bytes).decode("ascii")`
3. Builds prompt: Combines config prompt + slide context + instruction
4. Constructs JSON payload:
   ```json
   {
     "model": "llava",
     "prompt": "<prompt_text>",
     "images": ["<base64_image>"],
     "stream": false,
     "options": {"temperature": 0.0, "seed": 42, "num_predict": 100, ...}
   }
   ```
5. POSTs to: `http://127.0.0.1:11434/api/generate` (default)
6. Timeout: 60 seconds

**Response processing:**
1. Parses JSON: `data = resp.json()`
2. Extracts text: `data.get("response", "")` (or `data.get("message", {}).get("content", "")` for `/api/chat`)
3. Validates: Raises `ValueError` if empty
4. Normalizes: `_normalize_to_complete_sentences()` - ensures 1-2 sentences, truncates to 125 chars
5. Returns: `({"status": "ok", "text": "<normalized>"}, metadata)`

**Error handling:**
- **If API call fails**: Tries next provider in fallback chain; if all fail, returns `None`
- **If response contains error patterns**: Detects via `_is_llava_error()`, uses contextual fallback
- **If normalization fails**: Uses shape description fallback

### ALT Text Normalization

**Location**: `shared/unified_alt_generator.py::LLaVAProvider._normalize_to_complete_sentences()`
**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._normalize_alt_universal()`

**Transformations:**
1. Sentence extraction: Splits on `[.!?]+` patterns
2. Sentence filtering: Removes empty, ensures minimum 3 characters
3. Capitalization: Ensures first letter uppercase
4. Sentence limit: Takes first 1-2 sentences only
5. Terminal punctuation: Ensures ends with `.`, `!`, or `?`
6. Character limit: Truncates to 125 characters (config: `output.char_limit`)
7. Deduplication: Removes duplicate sentences (case-insensitive)
8. Whitespace collapse: `" ".join(text.split())`

**Outputs:**
- Normalized ALT text string (1-2 sentences, ≤125 chars, proper punctuation)

### ALT Text Injection

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Actions:**
1. Normalizes ALT text: `_apply_final_normalization_gate()`
2. Reads existing ALT text: `_read_current_alt(shape)`
3. **Preserve mode check**: If `mode == 'preserve'` and existing is meaningful, skips injection
4. **Idempotent check**: If normalized texts are equivalent, skips injection
5. **Duplicate hash check**: If same hash already written, skips injection
6. Writes to XML: `_write_descr_and_title(shape, text)`
7. Verifies write: Reads back ALT text, logs success/failure

**XML injection:**
- Finds or creates `<a:desc>` element in shape XML
- Sets text: `desc_element.text = normalized_alt_text`
- For groups: Sets `p:nvGrpSpPr/p:cNvPr[@descr]` attribute

**Outputs:**
- Modified shape XML with ALT text
- Write statistics (success/failure logged)

---

## Decision Points

### Element Selection Decisions

**D1: Should shape be processed as visual element?**
- **Condition**: `element_type == "text_placeholder" and not _has_visual_significance(shape)`
- **True**: Skip shape (no processing)
- **False**: Add to visual_elements list

**D2: Should shape be rendered to image?**
- **Condition**: Shape has no image but is visual (AUTO_SHAPE, LINE, FREEFORM, TEXT_BOX) with visual significance
- **True**: Render to PNG image, process as image element
- **False**: Process as shape element (text-based description)

**D3: Should generate ALT text for shape type?**
- **Condition**: `shape_type in {"PICTURE"}` (manifest processor)
- **True**: Generate via LLaVA
- **False**: Use shape fallback description

### Generation Decisions

**D4: Should generate ALT text?** (Manifest-based)
- **Condition**: `mode == "preserve" and current_alt.strip()`
- **True**: Use existing ALT, skip generation
- **False**: Check cache, then generate if needed

**D5: Does thumbnail exist?**
- **Condition**: `entry.thumbnail_path and Path(entry.thumbnail_path).exists()`
- **True**: Call LLaVA with thumbnail
- **False**: Skip generation, log warning

**D6: Is generated ALT text empty?**
- **Condition**: `alt_text and alt_text.strip()`
- **True**: Store ALT text, increment success count
- **False**: Log error, mark as failed, continue

**D7: Is LLaVA response an error?**
- **Condition**: Response contains error patterns ("error", "failed", "cannot", etc.)
- **True**: Use fallback description, mark as degraded
- **False**: Use generated ALT text

### Mode and Meaningfulness Decisions

**D8: What is the ALT text mode?**
- **Condition**: `config.alt_text_handling.mode` or parameter
- **"preserve"**: Proceed to preserve logic (check existing meaningful)
- **"replace"**: Proceed to replace logic (always use generated)

**D9: Is existing ALT text meaningful?**
- **Condition**: `_is_meaningful(existing_alt)` - checks length, skip tokens, placeholder patterns
- **True**: Treat as meaningful (preserve in preserve mode)
- **False**: Treat as missing (generate new)

**D10: Should replace existing ALT text?**
- **Condition**: `_should_replace_alt_text_normalized(existing, new)` - normalized comparison
- **True**: Replace existing with new
- **False**: Skip injection (texts are equivalent)

### Injection Decisions

**D11: Should write ALT text?** (Preserve mode guard)
- **Condition**: `mode == 'preserve' and _is_meaningful(existing) and not preserve_override`
- **True**: Skip injection, preserve existing
- **False**: Continue to injection

**D12: Should write ALT text?** (Idempotent guard)
- **Condition**: `not _should_replace_alt_text_normalized(existing, text)`
- **True**: Skip injection (texts equivalent)
- **False**: Continue to injection

**D13: Should write ALT text?** (Duplicate hash check)
- **Condition**: `element_key in final_writes and text_hash == existing_hash`
- **True**: Skip injection (already written)
- **False**: Continue to injection

### Group Processing Decisions

**D14: Should group get parent ALT text?**
- **Condition**: Number of meaningful children (0, 1, or >1)
- **0 meaningful**: Create generic parent ALT ("Group containing N elements")
- **1 meaningful**: Create composite ALT ("Group containing {element_type}")
- **>1 meaningful**: Create composite ALT ("Group of N {type}s" or "Group containing N visual elements")

**D15: Should mark children decorative?**
- **Condition**: Group roll-up policy and child analysis
- **True**: Mark children as decorative in XML
- **False**: Children keep individual ALT text

---

## Outputs

### Primary Outputs

**1. Modified PPTX File**
- **Location**: Output path (default: overwrites input, or `paths.output_folder`)
- **Content**: 
  - All shapes have ALT text in XML structure (`<a:desc>` elements)
  - Group parents have ALT text in `p:nvGrpSpPr/p:cNvPr[@descr]`
  - Decorative children marked with decorative extension elements
- **Format**: `.pptx` (Office Open XML)

### Secondary Outputs

**2. Coverage Report** (if `generate_coverage_report: true`)
- **Location**: `{output_folder}/{filename}_coverage_report.json`
- **Content**:
  ```json
  {
    "total_slides": N,
    "total_visual_elements": N,
    "processed_visual_elements": N,
    "failed_visual_elements": N,
    "generation_time": seconds,
    "injection_time": seconds,
    "total_time": seconds,
    "coverage_percent": percentage
  }
  ```

**3. Review Document** (if `--review-doc` or `--approval-doc-only` flag)
- **Location**: `{output_folder}/{filename}_ALT_Review.docx`
- **Content**: Word document with:
  - Thumbnails of all images
  - Existing ALT text (if any)
  - Generated ALT text
  - Comparison and decision notes
- **Format**: `.docx` (Word document)

**4. Artifact Files** (if artifact management enabled)
- **Location**: `.alt_pipeline_{session_id}/`
- **Files**:
  - `visual_index.json` - Catalog of all visual elements
  - `current_alt_by_key.json` - Existing ALT text mapping
  - `generated_alt_by_key.json` - Generated ALT text mapping
  - `final_alt_map.json` - Final ALT text decisions
  - `thumbs/` - Thumbnail images (JPEG)
  - `crops/` - Cropped image regions (PNG)

**5. Manifest File** (if manifest processor used)
- **Location**: `{output_folder}/{filename}_manifest.json`
- **Content**: Complete manifest with all entries, metadata, generation results
- **Format**: JSON (validated against schema)

### Statistics Output

**6. Processing Statistics**
- **Dictionary returned from `process_pptx()`**:
  ```python
  {
    'success': bool,
    'total_slides': int,
    'total_visual_elements': int,
    'processed_visual_elements': int,
    'failed_visual_elements': int,
    'generation_time': float,
    'injection_time': float,
    'total_time': float,
    'errors': List[str]
  }
  ```

**7. Injection Statistics**
- **Dictionary returned from `inject_alt_text_from_mapping()`**:
  ```python
  {
    'statistics': {
      'preserved_existing': int,
      'written_generated': int,
      'skipped_existing': int,
      'skipped_no_content': int,
      'failed': int
    },
    'total_shapes': int,
    'matched_shapes': int
  }
  ```

### Log Outputs

**8. Processing Logs**
- **Location**: `logs/` directory (if `logging.log_to_file: true`)
- **Files**: `{timestamp}_processing.log`, `{session_id}_session.log`
- **Content**: Detailed processing logs, errors, warnings, debug information

**9. Console Output**
- **Content**: Progress messages, success/failure indicators, statistics summary
- **Format**: Human-readable text output

---

## Complete Flow Summary

```
Entry Point (altgen.py / pptx_alt_processor.py)
  ↓
File Validation & Setup
  ├─> File exists check
  ├─> Resource validation
  ├─> File lock acquisition
  └─> Artifact directory creation
  ↓
Presentation Loading
  ├─> Load PPTX file (python-pptx)
  └─> Create resource context
  ↓
Per-Slide Processing
  ├─> Extract slide text/notes
  ├─> Recursively process shapes
  │   ├─> Detect images (5 methods)
  │   ├─> Extract image data
  │   ├─> Render shapes to images (if needed)
  │   └─> Create PPTXVisualElement objects
  └─> Process group ALT roll-up
  ↓
Per-Image Processing
  ├─> Normalize image format (convert to PNG)
  ├─> Write to temporary file
  ├─> Generate ALT text via LLaVA API
  │   ├─> Pre-flight validation
  │   ├─> Base64 encode image
  │   ├─> Build prompt with context
  │   ├─> POST to Ollama API
  │   └─> Parse and normalize response
  └─> Store in alt_text_mapping
  ↓
ALT Text Injection
  ├─> Reload presentation
  ├─> Build identifier mapping
  ├─> Match element keys to shapes
  ├─> Determine ALT decision (preserve/replace)
  ├─> Normalize ALT text
  ├─> Inject into XML structure
  └─> Verify write success
  ↓
Save & Cleanup
  ├─> Save modified PPTX file
  ├─> Generate coverage report (if enabled)
  ├─> Generate review document (if requested)
  ├─> Cleanup artifacts (if enabled)
  └─> Release file lock
  ↓
Outputs
  ├─> Modified PPTX file
  ├─> Coverage report JSON
  ├─> Review document DOCX (optional)
  ├─> Artifact files (optional)
  └─> Statistics dictionary
```

---

## Key Implementation Details

**Image Processing:**
- All images normalized to PNG format before API call
- WMF/EMF converted via external tools (Inkscape/LibreOffice) or use contextual fallback
- Images resized if >1600px (maintains aspect ratio)
- Base64 encoding for API transmission

**ALT Text Generation:**
- Always generates for images (no pre-check of existing ALT text)
- Uses deterministic generation (temperature=0.0, seed=42)
- Response limited to 100 tokens (`num_predict: 100`)
- Normalized to 1-2 complete sentences, max 125 characters

**ALT Text Injection:**
- Existing ALT text read during injection (not generation)
- Preserve mode: Skips if existing is meaningful
- Replace mode: Always overwrites
- XML injection: Writes to `<a:desc>` element or `@descr` attribute

**Error Handling:**
- LLaVA errors detected via pattern matching (heuristic)
- Fallback descriptions created for generation failures
- Degradation responses for connectivity failures
- Processing continues on individual element failures

**No OCR or Image Analysis:**
- System does NOT perform OCR
- System does NOT analyze image content beyond LLaVA vision model
- Only LLaVA vision model analyzes image content
