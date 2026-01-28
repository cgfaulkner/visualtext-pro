# Slide-by-Slide Processing: What Happens to Each Slide

## Overview

For each slide in a PowerPoint presentation, the system performs a series of extraction, transformation, and injection operations. This document describes exactly what data is read, what transformations occur, and what information is retained at each step.

---

## Per-Slide Processing Sequence

### Step 1: Slide Access and Initial Data Extraction

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_all_visual_elements()`

**What is read from the slide:**
- `slide.shapes` - Collection of all top-level shapes on the slide
- `len(slide.shapes)` - Count of shapes for logging
- `slide_idx` - Zero-based index of the slide in the presentation

**Transformations:**
- None at this step

**Information retained:**
- `slide_idx` - Stored for all subsequent operations
- Slide object reference - Passed to extraction functions

---

### Step 2: Slide Text Extraction

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_slide_text()`

**What is read from the slide:**
- For each shape in `slide.shapes`:
  - `shape.text` - Text content if shape has text attribute
  - Text is stripped of leading/trailing whitespace

**Transformations:**
- All shape text strings are collected into a list
- Text parts are joined with single spaces: `" ".join(text_parts)`
- Result is a single string containing all slide text

**Information retained:**
- `slide_text` - String containing all text from all shapes on the slide
- This string is truncated to `max_context_length` (default: 200 characters) when attached to visual elements
- Stored in each `PPTXVisualElement` object as `slide_text` attribute

**Conditional behavior:**
- Only extracted if `self.include_slide_text` is True (from config: `pptx_processing.include_slide_text`)
- If disabled, `slide_text` is empty string `""`

---

### Step 3: Slide Notes Extraction

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_slide_notes()`

**What is read from the slide:**
- `slide.notes_slide` - Notes slide object (may be None)
- `slide.notes_slide.notes_text_frame` - Text frame containing notes (may be None)
- `slide.notes_slide.notes_text_frame.text` - Raw notes text content

**Transformations:**
- Notes text is stripped of leading/trailing whitespace
- If notes exist, prefixed with "Notes: " when combined with slide text

**Information retained:**
- `slide_notes` - String containing notes text (empty string if no notes)
- Combined with slide text to create `slide_context_str`:
  - Format: `"{slide_text} Notes: {slide_notes}"` if both exist
  - Format: `"{slide_text}"` if only slide text exists
  - Format: `"Notes: {slide_notes}"` if only notes exist
- Stored in each `PPTXVisualElement` object as part of context

**Conditional behavior:**
- Only extracted if `self.include_slide_notes` is True (from config: `pptx_processing.include_slide_notes`)
- If disabled, `slide_notes` is empty string `""`
- If `slide.notes_slide` is None or `notes_text_frame` is None, returns empty string

---

### Step 4: Shape Recursive Processing

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()`

**What is read from each shape:**
- `shape.shapes` - Child shapes if this is a group (recursive check)
- `shape.shape_type` - Type enumeration (PICTURE, GROUP, CHART, AUTO_SHAPE, etc.)
- `shape.name` - Shape name attribute (may be 'unnamed')
- `shape.id` - Shape ID from XML (via `_extract_robust_shape_id()`)
- `shape.width` - Width in EMU units
- `shape.height` - Height in EMU units
- `shape.left` - Left position in EMU units
- `shape.top` - Top position in EMU units
- `shape.text_frame` - Text frame if shape contains text
- `shape.text_frame.text` - Text content if text frame exists
- `shape.image` - Image object if shape is a picture
- `shape.image.blob` - Raw image bytes if picture shape
- `shape.image.ext` - Image file extension
- `shape.image.filename` - Image filename if available
- `shape.fill` - Fill object (may contain image fills)
- `shape.line` - Line/border properties
- `shape._element` - XML element for deep inspection

**Transformations:**

1. **Shape ID extraction:**
   - Attempts to read `shape.id` from XML
   - Falls back to `shape_idx` (enumerated index) if no ID found
   - For grouped shapes: Creates hierarchical ID like `"{parent_group_idx}_{shape_idx}"`

2. **Element type classification:**
   - Maps `shape.shape_type` to string: "image", "chart", "table", "shape", "line", "text_box", "text_placeholder", "media", "embedded_object", "group", "connector", "unknown"
   - Uses `_classify_visual_element()` function

3. **Text content extraction:**
   - If `shape.text_frame` exists and has text:
     - Reads `shape.text_frame.text`
     - Stores in `PPTXVisualElement.text_content`
     - Sets `has_text = True`

4. **Image data extraction:**
   - If `shape.image` exists:
     - Reads `shape.image.blob` (raw bytes)
     - Reads `shape.image.ext` (extension)
     - Reads `shape.image.filename` (if available)
     - Creates MD5 hash of image bytes: `get_image_hash(image_data)`
     - Stores all in `PPTXVisualElement` object

5. **Dimension conversion:**
   - Converts EMU to pixels: `int(width.emu / 914400 * 96)`
   - Stores as `width_px`, `height_px`, `left_px`, `top_px`

6. **Element key generation:**
   - Creates stable identifier: `f"slide_{slide_idx}_shape_{shape_identifier}"`
   - Used for matching during injection phase

**Information retained:**

For each shape, creates a `PPTXVisualElement` object containing:
- `shape` - Reference to original shape object
- `slide_idx` - Slide index (0-based)
- `shape_idx` - Shape identifier (ID or index)
- `element_type` - String classification ("image", "shape", etc.)
- `slide_text` - Slide text context (truncated to max_context_length)
- `image_data` - Raw image bytes (if picture shape)
- `filename` - Image filename (if picture shape)
- `image_hash` - MD5 hash of image bytes (if picture shape)
- `width_px`, `height_px`, `left_px`, `top_px` - Pixel dimensions and position
- `has_text` - Boolean indicating if shape contains text
- `text_content` - Text content string (if has_text is True)
- `element_key` - Stable identifier string (e.g., "slide_0_shape_1")
- `element_hash` - Hash for duplicate detection

**Conditional behavior:**
- **Group shapes:** Recursively processes `shape.shapes` collection first, then processes group parent
- **Text placeholders:** Skips if `element_type == "text_placeholder"` and `_has_visual_significance()` returns False
- **Visual significance check:** Evaluates fills, borders, and dimensions to determine if text-only shape should be processed

---

### Step 5: Visual Element Creation

**Function**: `core/pptx_processor.py::PPTXVisualElement.__init__()`

**What is read:**
- All data from Step 4 (shape properties, dimensions, text, images)

**Transformations:**

1. **Image data extraction (if picture shape):**
   - Reads `shape.image.blob` → stores as `self.image_data`
   - Reads `shape.image.ext` → creates filename like `f"image_{slide_idx}_{shape_idx}.{ext}"`
   - Computes hash: `get_image_hash(self.image_data)` → stores as `self.image_hash`

2. **Dimension conversion:**
   - Converts EMU to pixels for all dimensions
   - Handles missing dimensions gracefully (defaults to 0)

3. **Text extraction:**
   - Reads `shape.text_frame.text` if available
   - Stores as `self.text_content`
   - Sets `self.has_text = True` if text exists

4. **Element key creation:**
   - Generates: `f"slide_{slide_idx}_shape_{shape_idx}"`
   - Stored as `self.element_key`

**Information retained:**

`PPTXVisualElement` object with all attributes listed above, added to `visual_elements` list for the slide.

---

### Step 6: Group ALT Text Roll-Up Processing (After All Slides Processed)

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._process_group_alt_rollup()`

**What is read from each slide (second pass):**
- `slide.shapes` - All top-level shapes again
- For each group shape:
  - `shape.shapes` - Child shapes within group
  - `shape.id` - Group shape ID
  - `shape.name` - Group shape name
  - `shape.width` - Group width in EMU
  - `shape.height` - Group height in EMU
  - `shape._element` - XML element for group

**Transformations:**

1. **Group analysis:**
   - For each group, calls `_analyze_group_children_for_rollup()`
   - Matches child shapes to previously extracted `visual_elements`
   - Classifies children as:
     - `meaningful_children` - Have visual elements (images, shapes, charts)
     - `text_only_children` - Only contain text, no visual content
     - `decorative_children` - Likely decorative or structural

2. **Roll-up decision:**
   - Calls `_decide_group_alt_rollup()` with child analysis
   - Determines if group should get parent ALT text
   - Generates parent ALT text string based on:
     - Number of meaningful children (0, 1, or multiple)
     - Semantic type detection (if enabled)
     - Child element types

3. **Parent ALT text generation:**
   - **No meaningful children:** Creates generic description like "Group containing N elements"
   - **Single meaningful child:** Creates description like "Group containing {element_type}"
   - **Multiple meaningful children:** Creates composite description like "Group of N images" or "Group containing N visual elements"
   - **Semantic detection (if enabled):** Creates descriptions like "Group representing lightbulb icon"

4. **Child marking:**
   - Determines which children should be marked decorative
   - Creates list of `children_to_mark_decorative`

**Information retained:**

- New `PPTXVisualElement` objects created for group parents with:
  - `element_type = "group"`
  - `element_key = f"slide_{slide_idx}_shape_{group_id}"`
  - Generated parent ALT text stored (not yet injected)
  - Reference to child shapes that should be marked decorative

- These group parent elements are added to the `visual_elements` list

---

### Step 7: ALT Text Generation (Per Visual Element)

**Function**: `core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_visual_element()`

**What is read:**
- `visual_element.element_type` - Type of element
- `visual_element.image_data` - Image bytes (if image element)
- `visual_element.slide_text` - Slide context text
- `visual_element.filename` - Image filename
- `visual_element.width_px`, `visual_element.height_px` - Dimensions

**Transformations:**

1. **For image elements:**
   - Creates temporary `PPTXImageInfo` object
   - Writes image data to temporary file on disk
   - Gets prompt from config via `ConfigManager.get_prompt()`
   - Combines prompt with slide context text
   - Calls `FlexibleAltGenerator.generate_alt_text(image_path, prompt, context)`

2. **For shape elements:**
   - Creates element description via `_create_element_description()`
   - Combines with slide context
   - Calls `FlexibleAltGenerator.generate_text_response(context_prompt)` OR
   - Renders shape to image and calls LLaVA (if shape rendering enabled)

3. **LLaVA API call:**
   - Reads temporary image file
   - Converts to base64 encoding
   - Builds JSON payload with prompt and image
   - POSTs to `http://127.0.0.1:11434/api/generate`
   - Parses response JSON, extracts "response" field
   - Normalizes response to complete sentences

4. **Response normalization:**
   - Truncates to 125 characters (config: `output.char_limit`)
   - Ensures ends with sentence punctuation
   - Removes duplicate sentences
   - Applies smart truncation if enabled

**Information retained:**

- `alt_text` - Generated ALT text string (or None if generation failed)
- `failure_reason` - Error message if generation failed
- Stored in `alt_text_mapping` dictionary:
  ```python
  alt_text_mapping[element_key] = {
      'alt_text': normalized_alt_text,
      'shape': visual_element.shape,
      'slide_idx': visual_element.slide_idx,
      'shape_idx': visual_element.shape_idx
  }
  ```

**Conditional behavior:**
- **If LLaVA error detected:** Calls `_handle_llava_error_with_fallback()`
- **If generation empty:** Creates fallback description via `_create_enhanced_fallback_description()`
- **If shape element:** May bypass LLaVA and create direct description (connectors, lines)

---

### Step 8: ALT Text Injection (Per Slide, After All Generation)

**Function**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**What is read from the slide:**
- `presentation.slides[slide_idx]` - Slide object
- `slide.shapes` - All shapes on the slide
- For each shape:
  - `shape._element` - XML element
  - `shape.id` - Shape ID
  - Existing ALT text from XML: `shape._element.find(".//a:desc")` or `shape._element.find(".//p:cNvPr[@descr]")`

**Transformations:**

1. **Image identifier mapping:**
   - Calls `_build_image_identifier_mapping(presentation)`
   - For each slide, iterates through shapes
   - Creates identifier for each shape: `PPTXImageIdentifier.from_shape(shape, slide_idx, shape_idx)`
   - Generates key: `f"slide_{slide_idx}_shape_{shape_idx}"`
   - Stores mapping: `image_identifiers[key] = (identifier, shape)`

2. **Key matching:**
   - Matches keys from `alt_text_mapping` (generated during Step 7) with keys from `image_identifiers` (from PPTX)
   - Logs matching statistics

3. **ALT text decision:**
   - For each matched key, calls `_determine_alt_decision(image_key, alt_record, mode)`
   - **If mode is 'preserve':**
     - Reads existing ALT text from shape XML
     - Checks if existing ALT is meaningful via `_is_meaningful()`
     - If meaningful, skips injection (preserves existing)
   - **If mode is 'replace':**
     - Always injects generated ALT text

4. **ALT text normalization:**
   - Calls `_normalize_alt_universal(candidate_text)`
   - Removes duplicate sentences
   - Collapses whitespace
   - Ensures proper sentence structure

5. **XML injection:**
   - Finds or creates `<a:desc>` element in shape XML
   - Sets ALT text value: `desc_element.text = normalized_alt_text`
   - For group shapes: Injects into `p:nvGrpSpPr/p:cNvPr[@descr]`

6. **Decorative marking:**
   - For group children marked decorative:
     - Creates decorative extension element in XML
     - Sets `decorative="true"` attribute

**Information retained:**

- Modified presentation object with ALT text injected into XML
- Statistics dictionary tracking:
  - `preserved_existing` - Count of preserved ALT text
  - `written_generated` - Count of generated ALT text written
  - `skipped_existing` - Count skipped due to preserve mode
  - `failed` - Count of failed injections

**Conditional behavior:**
- **Preserve mode:** Skips injection if existing ALT text is meaningful
- **Replace mode:** Always overwrites existing ALT text
- **Group children:** May mark as decorative if parent has ALT text
- **Geometric backfill:** Adds synthesized ALT for shapes missing from mapping

---

### Step 9: Presentation Save

**Function**: `pptx::Presentation.save(output_path)`

**What is written:**
- Entire modified presentation object to disk
- All slides with injected ALT text in XML
- All group parent ALT text
- All decorative markings

**Transformations:**
- PowerPoint file format serialization
- XML structure preservation
- Relationship maintenance

**Information retained:**
- Saved PPTX file on disk with all ALT text injected

---

## Data Flow Summary

### Input Data (Read from Slide)
1. Slide index (0-based)
2. Slide shapes collection
3. Shape properties (type, ID, name, dimensions, position)
4. Shape text content
5. Image data (blob, filename, extension)
6. Slide text (all shape text combined)
7. Slide notes (if available)
8. Existing ALT text (from XML)

### Transformations
1. Text concatenation (slide text)
2. EMU to pixel conversion (dimensions)
3. Image hash computation (MD5)
4. Element key generation (stable identifiers)
5. Element type classification
6. Group child analysis
7. ALT text generation (LLaVA API calls)
8. ALT text normalization (truncation, deduplication)
9. XML structure modification (ALT text injection)

### Output Data (Retained/Stored)
1. `visual_elements` list - All extracted visual elements with metadata
2. `alt_text_mapping` dictionary - Element keys mapped to ALT text
3. Modified presentation object - With ALT text in XML
4. Statistics dictionary - Processing counts and results
5. Saved PPTX file - Final output with injected ALT text

---

## Per-Slide Retention Summary

**During extraction phase:**
- Slide index
- Slide text string (truncated)
- Slide notes string
- List of `PPTXVisualElement` objects (one per visual element)
- Group parent elements (created during roll-up phase)

**During generation phase:**
- ALT text strings for each visual element
- Generation metadata (success/failure, timing)
- Fallback descriptions (if generation failed)

**During injection phase:**
- Modified XML structure with ALT text
- Decorative markings for group children
- Injection statistics

**Final output:**
- PPTX file with all ALT text injected into XML structure
- Each shape's XML contains `<a:desc>` element with ALT text
- Group parents have ALT text in `p:nvGrpSpPr/p:cNvPr[@descr]`
- Decorative children have decorative extension elements
