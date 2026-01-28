# Image Processing Flow: What Happens When an Image is Encountered

## Overview

When the system encounters an image or image-like object on a slide, it performs detection, extraction, ALT text generation, and injection. This document describes the exact sequence of operations.

---

## Step 1: Image Detection

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()`

**Detection Methods** (checked in order):

### Method 1: Direct Picture Shape Detection
**Check**: `hasattr(shape, 'image') and shape.image`

**What is checked:**
- `shape.shape_type == MSO_SHAPE_TYPE.PICTURE` (from `pptx.enum.shapes`)
- Presence of `shape.image` attribute
- Non-None value of `shape.image` object

**Result if detected:**
- Element type classified as `"image"`
- Proceeds to image data extraction (Step 2)

### Method 2: Image Fill Detection
**Check**: `hasattr(shape, 'fill') and shape.fill.type == MSO_FILL_TYPE.PICTURE`

**What is checked:**
- Shape has `fill` attribute
- Fill type is `MSO_FILL_TYPE.PICTURE` (from `pptx.enum.dml`)
- Found in text boxes, auto shapes, or any shape with picture fill

**Result if detected:**
- Attempts to extract image from fill via `_extract_images_from_fill()`
- May create `PPTXImageInfo` object if image data can be extracted

### Method 3: Chart Image Detection
**Check**: `hasattr(shape, 'chart')`

**What is checked:**
- Shape contains chart object
- Chart plot area fill (`chart.plot_area.fill`)
- Chart area fill (`chart.chart_area.fill`)
- Series fills (`chart.series[].fill`)

**Result if detected:**
- Extracts images from chart fills via `_extract_images_from_chart()`
- Creates `PPTXImageInfo` objects for each chart image found

### Method 4: OLE Object Detection
**Check**: `hasattr(shape, '_element')` and XML inspection

**What is checked:**
- XML element structure for embedded objects
- Relationship IDs pointing to image parts

**Result if detected:**
- Attempts to extract embedded images via `_extract_images_from_ole()`
- May create `PPTXImageInfo` objects if extraction succeeds

### Method 5: Shape Rendering (For Non-Image Visual Shapes)
**Check**: `_should_render_shape_to_image(shape)`

**What is checked:**
- Shape type is `AUTO_SHAPE`, `LINE`, `FREEFORM`, or `TEXT_BOX`
- Shape does NOT already have `shape.image`
- Shape is NOT a group (`hasattr(shape, 'shapes')` is False)
- Shape has visual significance (fill, border, or size >= 30x30px)

**Result if detected:**
- Shape is rendered to PNG image via `_render_shape_to_image()`
- Creates `PPTXImageInfo` with `is_rendered=True` flag
- Rendered image becomes the image data for processing

---

## Step 2: Image Data Extraction

**Location**: `core/pptx_processor.py::PPTXVisualElement.__init__()` (for direct images)
**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_images_from_shapes()` (for fills/charts)

### Direct Picture Shape Extraction

**What is read:**
- `shape.image.blob` - Raw image bytes (binary data)
- `shape.image.ext` - File extension string (e.g., "png", "jpg", "jpeg")
- `shape.image.filename` - Original filename if available (may be None)

**Transformations:**
- Image bytes stored directly as `self.image_data`
- Filename generated: `f"image_{slide_idx}_{shape_idx}.{shape.image.ext}"`
- MD5 hash computed: `get_image_hash(self.image_data)` → stored as `self.image_hash`

**Information retained:**
- `image_data` - Raw bytes (unchanged from PPTX)
- `filename` - Generated or original filename
- `image_hash` - MD5 hash string (first 8 characters used for matching)

### Image Fill Extraction

**What is read:**
- `shape.fill._fill.blipFill.blip.rId` - Relationship ID to image part
- Presentation relationships to resolve image part
- Image part blob data

**Transformations:**
- Relationship ID resolved to actual image part
- Image blob extracted from part
- Creates `PPTXImageInfo` object

**Information retained:**
- Same as direct picture extraction
- Source marked as "fill" in metadata

### Shape Rendering (For Visual Shapes)

**What is read:**
- `shape.width` - Width in EMU units
- `shape.height` - Height in EMU units
- `shape.fill` - Fill color/pattern
- `shape.line` - Border/outline properties
- `shape.auto_shape_type` - Specific shape type (oval, rectangle, etc.)
- `shape.text` - Text content if text box

**Transformations:**

1. **Dimension conversion:**
   - EMU to pixels: `width_px = int(width_emu / 914400 * 96)`
   - Minimum size enforced: `max(width_px, 50)`

2. **Image creation:**
   - Creates PIL Image: `Image.new('RGB', (width_px, height_px), 'white')`
   - Creates ImageDraw context: `ImageDraw.Draw(img)`

3. **Shape rendering (based on type):**
   - **AUTO_SHAPE (oval):** Draws ellipse with fill and outline
   - **AUTO_SHAPE (rectangle):** Draws rectangle with fill and outline
   - **AUTO_SHAPE (hexagon):** Draws polygon with calculated points
   - **LINE:** Draws line from (0,0) to (width-1, height-1)
   - **FREEFORM:** Draws simplified polygon
   - **TEXT_BOX:** Draws rectangle background, attempts to render text

4. **Image serialization:**
   - Converts PIL Image to bytes: `img.save(img_bytes, format='PNG')`
   - Gets PNG bytes: `image_data = img_bytes.getvalue()`

**Information retained:**
- `image_data` - PNG bytes of rendered shape
- `filename` - `f"rendered_shape_{slide_idx}_{shape_idx}.png"`
- `is_rendered` - Flag set to `True`
- `image_hash` - MD5 hash of rendered PNG bytes

---

## Step 3: Existing ALT Text Handling

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._get_existing_alt_text()`
**Location**: `shared/alt_text_reader.py::read_existing_alt()`

### When Existing ALT Text is Read

**During extraction phase:**
- Existing ALT text is NOT read during initial extraction
- Only shape properties and image data are extracted

**During injection phase:**
- Existing ALT text is read for each shape before injection
- Read via `_get_existing_alt_text(shape)` or `read_existing_alt(shape)`

### How Existing ALT Text is Read

**Method 1: Direct property access**
- Checks: `hasattr(shape, 'descr')`
- Reads: `shape.descr` (if available)
- Returns: String value or empty string

**Method 2: XML element access**
- Accesses: `shape._element._nvXxPr.cNvPr`
- Reads: `cNvPr.get('descr', '')` attribute
- Returns: ALT text string from XML

**Method 3: XPath search (via `read_existing_alt()`)**
- Searches XML for `cNvPr` elements using XPath patterns:
  - `.//p:nvPicPr/p:cNvPr` - For pictures
  - `.//p:nvSpPr/p:cNvPr` - For autoshapes
  - `.//p:nvGraphicFramePr/p:cNvPr` - For charts/tables
  - `.//p:nvCxnSpPr/p:cNvPr` - For connectors
  - `.//p:nvGrpSpPr/p:cNvPr` - For groups
  - `.//p:cNvPr` - Generic fallback
- Prefers `@descr` attribute, falls back to `@title` attribute
- Returns: First non-empty ALT text found

### How Existing ALT Text Affects Processing

**During ALT text generation:**
- Existing ALT text is NOT checked before generation
- Generation always proceeds regardless of existing ALT text
- Generated ALT text is stored in `alt_text_mapping` dictionary

**During injection (preserve mode):**
- Existing ALT text is read via `_read_current_alt(shape)`
- Checked for meaningfulness via `_is_meaningful(existing_alt)`
- **If meaningful:** Injection is skipped, existing ALT text preserved
- **If not meaningful:** Generated ALT text is injected

**During injection (replace mode):**
- Existing ALT text is read but ignored
- Generated ALT text always overwrites existing

**Meaningfulness check (`_is_meaningful()`):**
- Checks if ALT text is empty or whitespace-only
- Checks against skip patterns: `""`, `"undefined"`, `"(None)"`, `"N/A"`, `"Not reviewed"`, `"n/a"`
- Checks minimum length (15 characters for meaningful)
- Checks against placeholder patterns (regex matching "click to add", "image", "placeholder", etc.)

---

## Step 4: AI/Vision Model Invocation

**Location**: `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`

### When AI Models are Invoked

**For image elements:**
- AI model is ALWAYS invoked (no existing ALT text check before generation)
- Invoked via `FlexibleAltGenerator.generate_alt_text(image_path, prompt_type, context)`

**For shape elements (rendered to image):**
- AI model is invoked if shape was rendered to image
- Uses same generation path as image elements

**For shape elements (not rendered):**
- AI model is NOT invoked
- Uses text-based generation via `generate_text_response(context_prompt)` (no image)

### Pre-Flight Validation

**Function**: `shared/unified_alt_generator.py::LLaVAProvider._run_pre_flight_validation()`

**What is checked:**
- LLaVA service connectivity via `connectivity_manager.validate_connectivity()`
- Service health status
- Cached validation result (TTL: 300 seconds)

**If validation fails:**
- Creates degradation response via `_create_degradation_response()`
- Returns fallback ALT text without calling API
- Does NOT invoke vision model

### Image Preparation for API

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._normalize_image_format()`

**What happens:**

1. **Format detection:**
   - Checks filename extension: `.tiff`, `.tif`, `.wmf`, `.emf`
   - Checks file header bytes: `b'TIFF'`, `b'WMF'`, `b'EMF'` in first 100 bytes

2. **Image normalization:**
   - Opens image with PIL: `Image.open(io.BytesIO(image_data))`
   - Converts color mode to RGB (if RGBA, CMYK, etc.)
   - Resizes if larger than `max_image_dimension` (default: 1600px)
   - Saves as PNG: `img.save(output_buffer, format='PNG', optimize=True)`

3. **Vector format handling:**
   - **WMF/EMF:** Attempts external conversion via `_convert_vector_image_external()`
   - If conversion fails: Generates contextual fallback ALT text (no API call)
   - If conversion succeeds: Uses converted PNG for API call

4. **Temporary file creation:**
   - Creates temp file: `temp_manager.create_temp_file(suffix='.png')`
   - Writes normalized image bytes to temp file
   - Temp file path passed to API call

### API Request Construction

**Function**: `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`

**What is built:**

1. **Image encoding:**
   - Reads temp file: `Path(image_path).read_bytes()`
   - Base64 encodes: `base64.b64encode(image_bytes).decode("ascii")`
   - Stores as `img_b64` string

2. **Prompt construction:**
   - Gets base prompt from config: `ConfigManager.get_prompt(prompt_type, context)`
   - Combines with context: `f"{prompt}\n\nContext:\n{context}\n\nDescribe the image precisely in one concise sentence."`
   - Context includes: slide text, slide number, filename (if meaningful)

3. **Payload construction:**
   - **For `/api/generate` endpoint:**
     ```json
     {
       "model": "llava",
       "prompt": "<prompt_text>",
       "images": ["<base64_image>"],
       "stream": false,
       "options": {
         "temperature": 0.0,
         "top_p": 1.0,
         "top_k": 1,
         "num_predict": 100,
         "repeat_penalty": 1.0,
         "seed": 42
       }
     }
     ```
   - **For `/api/chat` endpoint:**
     ```json
     {
       "model": "llava",
       "messages": [
         {"role": "system", "content": "You are an expert accessibility captioner."},
         {"role": "user", "content": "<prompt_text>"}
       ],
       "images": ["<base64_image>"],
       "stream": false,
       "options": {...}
     }
     ```

4. **HTTP request:**
   - Method: `POST`
   - URL: `http://127.0.0.1:11434/api/generate` (default)
   - Headers: `{"Content-Type": "application/json"}`
   - Body: JSON-serialized payload
   - Timeout: 60 seconds

### API Response Processing

**Function**: `shared/unified_alt_generator.py::LLaVAProvider._execute_generation_request()`

**What happens:**

1. **Response parsing:**
   - Parses JSON response: `data = resp.json()`
   - Extracts text:
     - **For `/api/chat`:** `data.get("message", {}).get("content", "")`
     - **For `/api/generate`:** `data.get("response", "")`
   - Strips whitespace: `content.strip()`

2. **Response validation:**
   - Checks if empty: Raises `ValueError("Empty response from provider.")` if empty
   - Checks for error patterns: "error", "failed", "cannot", "unable", "sorry", etc.
   - If error pattern detected: Routes to contextual fallback (no retry)

3. **Normalization:**
   - Calls `_normalize_to_complete_sentences(content)`
   - Ensures 1-2 complete sentences
   - Truncates to 125 characters (config: `output.char_limit`)
   - Ensures ends with sentence punctuation (`.`, `!`, `?`)

4. **Return value:**
   - Returns: `({"status": "ok", "text": "<normalized_alt>"}, metadata)`
   - Metadata includes: generation time, model, endpoint, success flag

### Error Handling

**If API call fails:**
- Exception caught in `FlexibleAltGenerator.generate_alt_text()`
- Tries next provider in fallback chain (if configured)
- If all providers fail: Returns `None`

**If response contains error:**
- Detects error patterns in response text
- Calls `_generate_vector_fallback_alt()` for contextual fallback
- Returns fallback ALT text instead of error message

**If normalization fails:**
- Falls back to contextual description
- Uses shape properties to generate descriptive ALT text

---

## Step 5: Output Production

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`

### ALT Text Storage

**During generation phase:**
- Generated ALT text stored in `alt_text_mapping` dictionary:
  ```python
  alt_text_mapping[element_key] = {
      'alt_text': normalized_alt_text,
      'shape': visual_element.shape,
      'slide_idx': visual_element.slide_idx,
      'shape_idx': visual_element.shape_idx
  }
  ```

**During injection phase:**
- ALT text mapping converted to enriched format:
  ```python
  alt_text_mapping[element_key] = {
      'existing_alt': existing_alt_text,  # From XML
      'generated_alt': generated_alt_text,  # From LLaVA
      'final_alt': chosen_alt_text,  # Based on mode
      'decision': 'written_generated' | 'preserved_existing' | etc.,
      'source_existing': 'pptx' | None,
      'source_generated': 'llava' | None
  }
  ```

### Final ALT Text Selection

**Function**: `core/pptx_alt_injector.py::PPTXAltTextInjector._determine_alt_decision()`

**Decision logic:**

1. **If mode is 'preserve':**
   - Checks if `existing_alt` is meaningful
   - **If meaningful:** Decision = `'preserved_existing'`, final_alt = existing_alt
   - **If not meaningful:** Decision = `'written_generated'`, final_alt = generated_alt

2. **If mode is 'replace':**
   - Decision = `'written_generated'`
   - final_alt = generated_alt (always overwrites)

3. **If no generated ALT:**
   - Decision = `'skipped_no_content'`
   - final_alt = None or empty string

### ALT Text Normalization Before Injection

**Function**: `core/pptx_alt_injector.py::PPTXAltTextInjector._normalize_alt_universal()`

**Transformations:**

1. **Whitespace collapse:**
   - `" ".join(text.split())` - Collapses all whitespace to single spaces

2. **Sentence deduplication:**
   - Splits on sentence boundaries: `re.split(r'(?<=[.!?])\s+', text)`
   - Removes duplicate sentences (case-insensitive comparison)
   - Joins remaining sentences

3. **Final cleanup:**
   - Strips leading/trailing whitespace
   - Ensures proper sentence structure

### XML Injection

**Function**: `core/pptx_alt_injector.py::PPTXAltTextInjector._write_alt_text_to_shape()`

**What happens:**

1. **XML element location:**
   - Finds or creates `<a:desc>` element in shape XML
   - For pictures: `p:pic/p:nvPicPr/p:cNvPr` or `p:pic/p:nvPicPr/p:cNvPr/a:desc`
   - For shapes: `p:sp/p:nvSpPr/p:cNvPr` or creates `a:desc` child

2. **ALT text writing:**
   - Sets element text: `desc_element.text = normalized_alt_text`
   - For groups: Sets `p:nvGrpSpPr/p:cNvPr[@descr]` attribute

3. **Validation:**
   - Reads back ALT text to verify injection
   - Logs success/failure

### Final Output

**What is produced:**

1. **Modified PPTX file:**
   - Original file overwritten (or saved to output path)
   - All shapes have ALT text in XML structure
   - ALT text accessible to screen readers

2. **Statistics:**
   - `processed_visual_elements` - Count of elements processed
   - `failed_visual_elements` - Count of generation failures
   - `preserved_existing` - Count of preserved ALT text
   - `written_generated` - Count of generated ALT text written

3. **Artifacts (if enabled):**
   - `visual_index.json` - Catalog of all visual elements
   - `current_alt_by_key.json` - Existing ALT text mapping
   - `generated_alt_by_key.json` - Generated ALT text mapping
   - `final_alt_map.json` - Final ALT text decisions

---

## Summary: Complete Flow for an Image

1. **Detection:** Shape checked for `shape.image` attribute → classified as "image"
2. **Extraction:** `shape.image.blob` read → stored as bytes → MD5 hash computed
3. **Normalization:** Image converted to PNG → resized if needed → saved to temp file
4. **Generation:** Temp file path → base64 encoded → sent to LLaVA API → response parsed
5. **Normalization:** Response normalized → truncated to 125 chars → sentence structure ensured
6. **Injection:** Normalized ALT text → written to XML `<a:desc>` element → PPTX saved

**Existing ALT text handling:**
- Read during injection phase (not generation phase)
- Checked for meaningfulness
- Preserved if meaningful (preserve mode) or overwritten (replace mode)

**No OCR or image analysis:**
- System does NOT perform OCR on images
- System does NOT analyze image content beyond LLaVA vision model
- System does NOT extract text from images
- Only LLaVA vision model analyzes image content
