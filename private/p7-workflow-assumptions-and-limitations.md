# Workflow Assumptions and Limitations

This document lists assumptions and limitations evident from the code implementation. These are derived from actual code behavior, not documentation or inferred intent.

---

## 1. Image Format and Quality Assumptions

### 1.1 DPI Assumption
**Assumption**: All PPTX files use 96 DPI for pixel conversion  
**Location**: `core/pptx_processor.py:153-157`  
**Code Evidence**:
```python
# Convert EMU to pixels (1 EMU = 1/914400 inch, assume 96 DPI)
self.width_px = int(self.width / 914400 * 96) if self.width else 0
```
**Limitation**: If PPTX files use different DPI settings, pixel calculations will be incorrect. No validation or detection of actual DPI.

### 1.2 Image Format Normalization Assumption
**Assumption**: PIL can successfully convert all non-problematic formats to PNG  
**Location**: `core/pptx_processor.py:4735-4736`  
**Code Evidence**:
```python
# For other formats that PIL can't handle, return original data
return image_data
```
**Limitation**: If PIL fails for non-problematic formats (not TIFF/WMF/EMF), original image data is returned without validation. This may cause LLaVA to fail silently or produce poor results.

### 1.3 Image Conversion Failure Handling
**Assumption**: External conversion tools (Inkscape/LibreOffice) are available and functional  
**Location**: `core/pptx_processor.py:4710-4721`  
**Code Evidence**:
```python
if filename_lower.endswith(('.wmf', '.emf')):
    logger.info(f"Attempting external conversion for {filename}")
    try:
        converted_data = self._convert_vector_image_external(image_data, filename, debug)
        if converted_data:
            return converted_data
        else:
            logger.warning(f"External conversion returned no data for {filename}")
    except Exception as ext_error:
        logger.warning(f"External conversion failed for {filename}: {ext_error}")
        # Continue to contextual fallback instead of failing
```
**Limitation**: 
- No validation that Inkscape/LibreOffice are installed before attempting conversion
- Conversion failures fall back to contextual ALT text (not image-based generation)
- No verification that converted PNG is valid or readable

### 1.4 Image Size Limits
**Assumption**: Images larger than 1600px can be safely resized without quality loss  
**Location**: `core/pptx_processor.py:4681-4694`  
**Code Evidence**:
```python
max_dimension = self.processing_config.get('max_image_dimension', 1600)
if max(original_size) > max_dimension:
    # Calculate new size maintaining aspect ratio
    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
```
**Limitation**: 
- No validation that resized image maintains sufficient detail for LLaVA analysis
- Hard-coded 1600px limit may be too small for detailed medical/scientific images
- No user notification when images are resized

### 1.5 Zero Dimension Handling
**Assumption**: Images with zero width or height should be skipped  
**Location**: `core/pptx_processor.py:4027-4028`, `core/pptx_processor.py:759-760`  
**Code Evidence**:
```python
if width <= 0 or height <= 0:
    return False
```
**Limitation**: No validation that zero dimensions indicate a corrupted image vs. intentionally hidden shape. Processing continues without ALT text.

---

## 2. LLaVA Model Availability Assumptions

### 2.1 Pre-Flight Validation Can Be Skipped
**Assumption**: If connectivity manager is unavailable, pre-flight validation can be skipped  
**Location**: `shared/unified_alt_generator.py:217-220`  
**Code Evidence**:
```python
# Skip if no connectivity manager
if not self.connectivity_manager:
    logger.debug("No connectivity manager available, skipping pre-flight validation")
    return True
```
**Limitation**: Processing proceeds without validating LLaVA availability, leading to failures later in the workflow.

### 2.2 Model Name Matching
**Assumption**: Model name in config exactly matches model name in Ollama  
**Location**: `shared/llava_connectivity.py:302-305`  
**Code Evidence**:
```python
for model in models:
    if model_name in model.get('name', ''):
        model_found = True
```
**Limitation**: Uses substring matching (`in` operator), which may match wrong models (e.g., "llava" matches "llava:latest" and "llava:7b"). No exact match validation.

### 2.3 Default Service Location
**Assumption**: Ollama is running at `http://127.0.0.1:11434`  
**Location**: `shared/unified_alt_generator.py:311`  
**Code Evidence**:
```python
base_url = self.config.get('base_url', 'http://127.0.0.1:11434')
```
**Limitation**: No validation that service is accessible before processing starts. Failures occur during generation, not upfront.

### 2.4 Model Loaded State
**Assumption**: If model appears in `/api/tags`, it is loaded and ready  
**Location**: `shared/llava_connectivity.py:288-336`  
**Code Evidence**: Only checks model name in tags list, does not verify model is actually loaded/ready for inference  
**Limitation**: Model may be listed but not loaded, causing generation failures.

### 2.5 Connectivity Manager Optional
**Assumption**: Connectivity hardening is optional; basic mode works without it  
**Location**: `shared/unified_alt_generator.py:302-304`  
**Code Evidence**:
```python
else:
    # Fallback to original execution without hardening
    return self._execute_generation_request(custom_prompt, image_path)
```
**Limitation**: No retry logic, circuit breaker, or health checks if connectivity manager unavailable. Single-attempt failures.

---

## 3. ALT Text Presence and Format Assumptions

### 3.1 Existing ALT Text Format
**Assumption**: Existing ALT text is stored in `cNvPr/@descr` or `cNvPr/@title` attributes  
**Location**: `shared/alt_text_reader.py` (via XPath queries)  
**Code Evidence**: XPath queries assume standard PPTX XML structure  
**Limitation**: 
- No handling for ALT text stored in non-standard locations
- No validation that read ALT text matches what PowerPoint displays
- Assumes XML structure is valid and accessible

### 3.2 ALT Text Persistence
**Assumption**: Written ALT text persists in PPTX file  
**Location**: `core/pptx_alt_injector.py:1126-1133`  
**Code Evidence**:
```python
written_descr = self._read_current_alt(shape)
if written_descr.strip() == final_alt.strip():
    logger.info(f"✅ READBACK SUCCESS: Write verified for {element_key}")
else:
    logger.warning(f"❌ READBACK MISMATCH: {element_key} expected={final_alt!r} actual={written_descr!r}")
```
**Limitation**: 
- Readback verification only logs warnings; does not retry or fail
- Mismatches are logged but processing continues
- No validation that ALT text will persist after file save/reopen

### 3.3 Empty ALT Text Handling
**Assumption**: Empty or whitespace-only ALT text should be treated as missing  
**Location**: `core/pptx_alt_injector.py:1064-1066`  
**Code Evidence**:
```python
if not text or not text.strip():
    logger.debug(f"INJECT_ALT: Skipping empty text for {element_key}")
    return False
```
**Limitation**: No distinction between intentionally empty ALT text (decorative) and missing ALT text. Both trigger generation.

### 3.4 Meaningful ALT Text Detection
**Assumption**: ALT text with >10 characters is meaningful  
**Location**: `core/pptx_alt_injector.py:2632`  
**Code Evidence**:
```python
if len(existing_alt_text.strip()) > 10:  # Meaningful length
```
**Limitation**: 
- Arbitrary 10-character threshold
- No validation that text is actually descriptive (could be placeholder like "image123")
- Generic placeholder detection exists but may miss patterns

### 3.5 Skip Token Detection
**Assumption**: Specific skip tokens indicate non-meaningful ALT text  
**Location**: `shared/pipeline_phases.py:39-48`  
**Code Evidence**:
```python
skip_tokens = {
    "(none)",
    "n/a",
    "not reviewed",
    "undefined",
    "image.png",
    "picture",
    "",
}
```
**Limitation**: 
- Hard-coded list; may miss other placeholder patterns
- Case-sensitive matching (lowercase conversion applied, but list is lowercase)
- No fuzzy matching for variations

---

## 4. PPTX File Structure Assumptions

### 4.1 Valid XML Structure
**Assumption**: PPTX file contains valid XML that can be parsed  
**Location**: `core/pptx_processor.py:395-399`  
**Code Evidence**:
```python
if not pptx_path.exists():
    error_msg = f"PPTX file not found: {pptx_path}"
    return result
```
**Limitation**: 
- Only checks file existence, not validity
- No validation that file is actually a PPTX (could be corrupted ZIP)
- XML parsing errors propagate as exceptions without structured handling

### 4.2 Shape Structure Consistency
**Assumption**: All shapes have consistent structure (width, height, shape_type attributes)  
**Location**: `core/pptx_processor.py:756-760`  
**Code Evidence**:
```python
width_emu = getattr(shape, 'width', 0)
height_emu = getattr(shape, 'height', 0)

if width_emu <= 0 or height_emu <= 0:
    return None
```
**Limitation**: 
- Uses `getattr()` with defaults, silently handles missing attributes
- No validation that shape structure matches expected type
- Processing continues if shape properties are missing

### 4.3 Slide Dimensions
**Assumption**: Standard slide dimensions are 960x720px  
**Location**: `core/pptx_processor.py:4067`  
**Code Evidence**:
```python
# Standard slide dimensions are approximately 960x720px
slide_area_estimate = 960 * 720
```
**Limitation**: 
- Hard-coded assumption; actual slide dimensions not read from PPTX
- May incorrectly calculate image coverage percentage for non-standard slide sizes
- No validation of actual slide dimensions

### 4.4 Shape ID Availability
**Assumption**: Shapes have stable IDs that persist across processing  
**Location**: `core/pptx_processor.py:162-246`  
**Code Evidence**: Uses `shape.shape_id` or extracts from XML with fallback to index  
**Limitation**: 
- If shape IDs are missing or change, image keys may not match between extraction and injection
- Fallback to index-based keys may cause mismatches if slide order changes

---

## 5. Error Handling and Validation Gaps

### 5.1 LLaVA Error Detection
**Assumption**: Error patterns in response text indicate LLaVA failures  
**Location**: `core/pptx_processor.py:5289-5312`  
**Code Evidence**:
```python
error_patterns = [
    'error', 'failed', 'cannot', 'unable', 'sorry',
    'i cannot', 'i am unable', 'no description',
    # ... more patterns
]
description_lower = description.lower().strip()
return any(pattern in description_lower for pattern in error_patterns)
```
**Limitation**: 
- Heuristic-based detection; may miss errors or false-positive on legitimate descriptions
- Pattern "error" matches any text containing "error" (e.g., "error correction code")
- No validation that detected errors are actually errors vs. descriptive text

### 5.2 Empty Response Handling
**Assumption**: Empty responses from LLaVA should raise exceptions  
**Location**: `shared/unified_alt_generator.py:377-379`  
**Code Evidence**:
```python
content = (content or "").strip()
if not content:
    raise ValueError("Empty response from provider.")
```
**Limitation**: 
- Exception is raised but may be caught and handled elsewhere
- No distinction between empty response and timeout
- No retry logic for empty responses (handled by connectivity manager if available)

### 5.3 Shape Rendering Failures
**Assumption**: Shape rendering failures are non-fatal  
**Location**: `core/pptx_processor.py:806-808`  
**Code Evidence**:
```python
except Exception as e:
    logger.warning(f"Failed to render shape {shape_idx} on slide {slide_idx}: {e}")
    return None
```
**Limitation**: 
- Returns `None` but processing continues
- No fallback ALT text generation for shapes that can't be rendered
- Shape is skipped without ALT text

### 5.4 File Write Validation
**Assumption**: Output file can be written if parent directory exists  
**Location**: `core/pptx_processor.py:405-406`  
**Code Evidence**:
```python
output_path.parent.mkdir(parents=True, exist_ok=True)
```
**Limitation**: 
- No validation that output path is writable
- No check for disk space before processing starts
- No validation that file can be opened for writing

### 5.5 Lock File Cleanup
**Assumption**: Stale lock files can be safely removed  
**Location**: `shared/file_lock_manager.py` (stale lock cleanup)  
**Code Evidence**: Removes locks older than threshold  
**Limitation**: 
- No validation that process owning lock is actually dead
- May remove active locks if process is slow/unresponsive
- Race condition possible if two processes check simultaneously

### 5.6 PIL Availability
**Assumption**: PIL (Pillow) is optional; processing continues without it  
**Location**: `core/pptx_processor.py:4648-4650`  
**Code Evidence**:
```python
if not PIL_AVAILABLE:
    logger.warning("PIL not available - cannot normalize image format")
    return image_data
```
**Limitation**: 
- Returns original image data without normalization
- May send unsupported formats to LLaVA
- No validation that image format is acceptable without PIL

---

## 6. Generation Quality Assumptions

### 6.1 Response Length Limits
**Assumption**: `num_predict: 100` is sufficient for ALT text  
**Location**: `shared/unified_alt_generator.py:333`  
**Code Evidence**:
```python
"num_predict": 100,      # Limit response length
```
**Limitation**: 
- Hard-coded limit; may truncate longer descriptions
- No validation that truncation occurs at sentence boundary
- May produce incomplete ALT text

### 6.2 Deterministic Generation
**Assumption**: Temperature 0.0 and seed 42 ensure deterministic results  
**Location**: `shared/unified_alt_generator.py:329-340`  
**Code Evidence**:
```python
deterministic_options = {
    "temperature": 0.0,      # Deterministic generation
    "top_p": 1.0,            # No nucleus sampling
    "top_k": 1,              # Always pick most likely token
    # ...
}
seed = self.config.get('seed', 42)
if seed is not None:
    deterministic_options["seed"] = seed
```
**Limitation**: 
- Assumes Ollama supports seed parameter (not validated)
- Determinism only applies if same model/version used
- No validation that results are actually deterministic

### 6.3 Character Limit Enforcement
**Assumption**: 125-character limit is appropriate for all ALT text  
**Location**: `shared/unified_alt_generator.py:1080`  
**Code Evidence**:
```python
char_limit = self.config_manager.config.get('output', {}).get('char_limit', 125)
alt_text = self._shrink_to_char_limit(alt_text, char_limit)
```
**Limitation**: 
- Hard truncation may cut off mid-word or mid-sentence
- No validation that truncated text is still meaningful
- May violate accessibility guidelines for complex images requiring longer descriptions

### 6.4 Sentence Normalization
**Assumption**: 1-2 complete sentences are sufficient  
**Location**: `shared/unified_alt_generator.py:436-479`  
**Code Evidence**:
```python
# Take first 1-2 sentences only
if len(valid_sentences) >= 2:
    result = valid_sentences[0] + ". " + valid_sentences[1]
```
**Limitation**: 
- May truncate important details in third sentence
- Sentence detection uses simple regex; may miss complex punctuation
- No validation that 1-2 sentences adequately describe image

---

## 7. Context and Prompt Assumptions

### 7.1 Slide Text Availability
**Assumption**: Slide text and notes are available and meaningful  
**Location**: `core/pptx_processor.py` (slide text extraction)  
**Code Evidence**: Extracts slide text without validation  
**Limitation**: 
- No validation that slide text is relevant to images
- May include irrelevant text (headers, footers, watermarks)
- Context length limited to 200 characters; may truncate important context

### 7.2 Context Length Limits
**Assumption**: 200 characters of context is sufficient  
**Location**: `config.yaml:197`  
**Code Evidence**: `max_context_length: 200`  
**Limitation**: 
- Hard truncation may cut off mid-word
- No validation that truncated context maintains meaning
- May exclude important contextual information

### 7.3 Prompt Template Validity
**Assumption**: Prompt templates produce valid prompts  
**Location**: `shared/unified_alt_generator.py:74-79`  
**Code Evidence**:
```python
def _build_prompt_text(custom_prompt: str, context: str) -> str:
    ctx = (context or "").strip()
    if ctx:
        return f"{custom_prompt.strip()}\n\nContext:\n{ctx}\n\nDescribe the image precisely in one concise sentence."
```
**Limitation**: 
- No validation that prompt is within token limits
- No validation that prompt format is correct for model
- Assumes model understands prompt structure

---

## 8. File System and Resource Assumptions

### 8.1 Temporary File Cleanup
**Assumption**: Temporary files are cleaned up automatically  
**Location**: `shared/resource_manager.py` (ResourceContext)  
**Code Evidence**: Context manager pattern for cleanup  
**Limitation**: 
- Cleanup only occurs if context manager exits normally
- Exceptions may prevent cleanup
- No validation that cleanup actually occurred

### 8.2 Disk Space Availability
**Assumption**: Sufficient disk space exists for processing  
**Location**: `core/pptx_processor.py:414`  
**Code Evidence**:
```python
validation_result = validate_system_resources(required_memory_mb=200, required_disk_mb=500)
```
**Limitation**: 
- Only checks at start; doesn't account for intermediate files
- 500MB may be insufficient for large presentations with many images
- No monitoring during processing

### 8.3 File Permissions
**Assumption**: Write permissions exist for output directory  
**Location**: `core/pptx_processor.py:406`  
**Code Evidence**:
```python
output_path.parent.mkdir(parents=True, exist_ok=True)
```
**Limitation**: 
- `exist_ok=True` silently handles existing directories
- No validation that directory is actually writable
- No check for file-level write permissions

### 8.4 Path Validity
**Assumption**: File paths are valid and accessible  
**Location**: `shared/path_validator.py` (path validation)  
**Code Evidence**: Validates paths but may allow problematic paths  
**Limitation**: 
- No validation of path length limits (Windows 260 char limit)
- No validation of special characters in paths
- May fail on network paths or special filesystem types

---

## 9. Batch Processing Assumptions

### 9.1 Sequential Processing Safety
**Assumption**: Sequential processing (max_workers=1) is safe  
**Location**: `config.yaml:235`  
**Code Evidence**: `default_max_workers: 1`  
**Limitation**: 
- No validation that sequential processing prevents all race conditions
- File locking may still have issues with rapid sequential access
- Assumes single-process execution

### 9.2 Subprocess Timeout
**Assumption**: 300-second timeout is sufficient for file processing  
**Location**: `config.yaml:241`  
**Code Evidence**: `file_timeout_seconds: 300`  
**Limitation**: 
- Hard timeout may kill processes mid-operation
- No graceful shutdown; may leave files in inconsistent state
- No validation that timeout is appropriate for file size/complexity

### 9.3 Error Threshold
**Assumption**: 50% failure rate should stop batch  
**Location**: `config.yaml:239`  
**Code Evidence**: `stop_on_error_threshold: 0.5`  
**Limitation**: 
- Arbitrary threshold; may stop on recoverable errors
- No distinction between fatal and recoverable errors
- May continue processing with high failure rate if threshold not met

---

## 10. Manifest and Caching Assumptions

### 10.1 Manifest Schema Compatibility
**Assumption**: Manifest schema version matches code expectations  
**Location**: `shared/alt_manifest.py` (manifest loading)  
**Code Evidence**: Loads manifest without version validation in some paths  
**Limitation**: 
- May fail silently if schema version mismatch
- No migration path for older manifest versions
- Assumes manifest structure is stable

### 10.2 Cache Validity
**Assumption**: Cached ALT text is still valid  
**Location**: `shared/alt_manifest.py` (cache lookup)  
**Code Evidence**: Uses cached results without validation  
**Limitation**: 
- No expiration or invalidation logic
- No validation that cached ALT text matches current image
- May use stale ALT text if image changed

### 10.3 Image Hash Uniqueness
**Assumption**: MD5 hash uniquely identifies image content  
**Location**: `shared/perceptual_hash.py` (image hashing)  
**Code Evidence**: Uses MD5 hash for duplicate detection  
**Limitation**: 
- MD5 collisions possible (rare but not impossible)
- No validation that hash collision hasn't occurred
- May reuse ALT text for different images if collision occurs

---

## 11. Shape Processing Assumptions

### 11.1 Shape Type Detection
**Assumption**: Shape types can be reliably detected  
**Location**: `core/pptx_processor.py` (shape type detection)  
**Code Evidence**: Uses `shape.shape_type` with fallbacks  
**Limitation**: 
- Fallback to XML tag inspection if shape_type unavailable
- May misclassify shapes if XML structure is non-standard
- No validation that detected type matches actual shape

### 11.2 Group Shape Processing
**Assumption**: Group shapes can be processed recursively  
**Location**: `core/pptx_processor.py` (group processing)  
**Code Evidence**: Recursively processes group children  
**Limitation**: 
- No depth limit; deeply nested groups may cause stack overflow
- No validation that group structure is valid
- May process same shape multiple times if group structure is circular

### 11.3 Shape Rendering Quality
**Assumption**: Rendered shapes accurately represent original  
**Location**: `core/pptx_processor.py:737-808` (shape rendering)  
**Code Evidence**: Renders shapes to images using PIL  
**Limitation**: 
- Rendering is simplified; may miss visual details
- No validation that rendered image matches original appearance
- Complex shapes (gradients, effects) may render incorrectly

---

## 12. Network and API Assumptions

### 12.1 HTTP Timeout Sufficiency
**Assumption**: 60-second timeout is sufficient for LLaVA requests  
**Location**: `shared/unified_alt_generator.py:367`  
**Code Evidence**:
```python
resp = requests.post(full, data=json.dumps(payload), headers=headers, timeout=60)
```
**Limitation**: 
- Hard timeout; no retry for slow but successful requests
- May timeout on large images or slow models
- No adaptive timeout based on image size

### 12.2 JSON Response Format
**Assumption**: Ollama API returns JSON in expected format  
**Location**: `shared/unified_alt_generator.py:372-375`  
**Code Evidence**:
```python
if endpoint_path.endswith("/api/chat"):
    content = (data.get("message") or {}).get("content") or ""
else:
    content = data.get("response") or ""
```
**Limitation**: 
- Assumes response structure matches expected format
- No validation that JSON keys exist before access
- May fail silently if API response format changes

### 12.3 Base64 Encoding Validity
**Assumption**: Image data can be safely base64-encoded  
**Location**: `shared/unified_alt_generator.py:326`  
**Code Evidence**:
```python
img_b64 = _b64_of_file(image_path)
```
**Limitation**: 
- No validation that base64 encoding succeeded
- No check for maximum payload size
- May exceed API payload limits for very large images

---

## Summary

**Critical Assumptions** (may cause silent failures):
1. 96 DPI for all PPTX files
2. PIL can handle all non-problematic image formats
3. Pre-flight validation can be skipped if connectivity manager unavailable
4. Model name substring matching is sufficient
5. ALT text readback verification only logs warnings

**Quality Limitations** (may produce suboptimal results):
1. Hard 125-character limit may truncate important details
2. 1-2 sentence limit may exclude important information
3. Context truncation at 200 characters
4. Shape rendering may miss visual details
5. Error pattern detection is heuristic-based

**Missing Validations** (may cause unexpected behavior):
1. No validation that output file is writable before processing
2. No validation that converted images are valid
3. No validation that model is actually loaded (only checks name in list)
4. No validation that ALT text persists after file save
5. No validation that prompt is within token limits

**Resource Assumptions** (may cause failures under load):
1. 500MB disk space may be insufficient for large presentations
2. 300-second timeout may be too short for complex files
3. No monitoring of resource usage during processing
4. Temporary file cleanup depends on normal context manager exit
