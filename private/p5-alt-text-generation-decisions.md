# ALT Text Generation Workflow: All Decision Points

This document identifies every conditional branch (decision point) in the ALT text generation workflow that affects whether ALT text is generated, how it's generated, or whether it's injected.

---

## Phase 1: Element Selection and Classification

### Decision 1.1: Should Shape Be Processed as Visual Element?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._extract_visual_elements_from_shapes()`

**Condition**: `element_type == "text_placeholder" and not _has_visual_significance(shape)`

**If TRUE:**
- Shape is skipped (not added to visual_elements list)
- No ALT text processing occurs for this shape

**If FALSE:**
- Shape is added to visual_elements list
- Processing continues

**Visual significance check** (`_has_visual_significance()`):
- Checks for `shape.fill` (fill colors/patterns)
- Checks for `shape.line` (borders/outlines)
- Checks dimensions: `width_px > 200 or height_px > 200`

---

### Decision 1.2: Should Shape Be Rendered to Image?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._should_render_shape_to_image()`

**Conditions checked (in order):**

**Condition 1.2a**: `hasattr(shape, 'image') and shape.image`
- **If TRUE:** Returns `False` (already has image, don't render)
- **If FALSE:** Continues to next check

**Condition 1.2b**: `hasattr(shape, 'shapes')` (is group)
- **If TRUE:** Returns `False` (groups processed recursively, don't render)
- **If FALSE:** Continues to next check

**Condition 1.2c**: `shape.fill.type == MSO_FILL_TYPE.PICTURE`
- **If TRUE:** Returns `True` (has picture fill, render it)
- **If FALSE:** Continues to next check

**Condition 1.2d**: `shape_type in [AUTO_SHAPE, LINE, FREEFORM, TEXT_BOX]` AND `_has_visual_significance_for_rendering(shape)`
- **If TRUE:** Returns `True` (visual shape with significance, render it)
- **If FALSE:** Continues to next check

**Condition 1.2e**: `shape_type == TEXT_BOX` AND `len(shape.text.strip()) > 10`
- **If TRUE:** Returns `True` (text box with substantial content, render it)
- **If FALSE:** Returns `False` (don't render)

**Visual significance for rendering** (`_has_visual_significance_for_rendering()`):
- Checks `shape.fill.type == MSO_FILL_TYPE.SOLID` → Returns `True`
- Checks `shape.fill.type != MSO_FILL_TYPE.NO_FILL` → Returns `True`
- Checks `shape.line.width > 0` → Returns `True`
- Checks `width_px >= 30 and height_px >= 30` → Returns `True`
- Otherwise returns `False`

---

### Decision 1.3: Should Generate ALT Text for Image? (Legacy Function)

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._should_generate_alt_text()`

**Note**: This function exists but is NOT called in current workflow (generation always proceeds)

**Conditions checked (if called):**

**Condition 1.3a**: `is_force_decorative_by_filename(image_info.filename, config)`
- **If TRUE:** Returns `False` (skip generation, marked decorative by config)
- **If FALSE:** Continues

**Condition 1.3b**: `not self.skip_decorative`
- **If TRUE:** Returns `True` (decorative detection disabled, always generate)
- **If FALSE:** Continues

**Condition 1.3c**: `_is_educational_content(image_info)`
- **If TRUE:** Returns `True` (educational content, always generate)
- **If FALSE:** Continues

**Condition 1.3d**: `_is_content_by_size_and_context(image_info, dimensions)`
- **If TRUE:** Returns `True` (content by size analysis, generate)
- **If FALSE:** Continues

**Condition 1.3e**: `is_decorative_image(...)` (heuristic detection)
- **If TRUE:** Returns `False` (marked decorative, skip generation)
- **If FALSE:** Returns `True` (generate ALT text)

---

### Decision 1.4: Should Generate ALT Text for Shape Type? (Manifest Processor)

**Location**: `shared/alt_manifest.py::AltManifest.should_generate_for_shape_type()`

**Condition**: `shape_type in {"PICTURE"}`

**If TRUE:**
- Returns `True` (generate via LLaVA)
- ALT text generated using vision model

**If FALSE:**
- Returns `False` (use fallback description)
- ALT text created from shape properties (no LLaVA call)

**Note**: Only `PICTURE` type triggers LLaVA generation. All other types use fallback descriptions.

---

## Phase 2: Generation Phase Decisions

### Decision 2.1: Should Generate ALT Text? (Manifest-Based)

**Location**: `shared/alt_manifest.py::AltManifest.should_generate_alt()`

**Condition 2.1a**: `mode == "preserve" and current_alt.strip()`
- **If TRUE:** Returns `(False, current_alt)` (use existing, don't call LLaVA)
- **If FALSE:** Continues

**Condition 2.1b**: `existing_entry and existing_entry.suggested_alt`
- **If TRUE:** Returns `(False, existing_entry.suggested_alt)` (use cached, don't call LLaVA)
- **If FALSE:** Continues

**Condition 2.1c**: `cached_entry and cached_entry.suggested_alt` (by image hash)
- **If TRUE:** Returns `(False, cached_entry.suggested_alt)` (use cached by hash, don't call LLaVA)
- **If FALSE:** Continues

**Condition 2.1d**: (Default)
- Returns `(True, None)` (need to generate, call LLaVA)

---

### Decision 2.2: Does Thumbnail Exist? (Manifest Processor)

**Location**: `shared/manifest_processor.py::ManifestProcessor._generate_missing_alt_text()`

**Condition**: `entry.thumbnail_path and Path(entry.thumbnail_path).exists()`

**If TRUE:**
- Calls `alt_generator.generate_alt_text(entry.thumbnail_path)`
- LLaVA API invoked with thumbnail image

**If FALSE:**
- Logs warning: "No thumbnail available, skipping LLaVA generation"
- Skips generation for this entry
- Continues to next entry

---

### Decision 2.3: Is Generated ALT Text Empty?

**Location**: `shared/manifest_processor.py::ManifestProcessor._generate_missing_alt_text()`

**Condition**: `alt_text and alt_text.strip()`

**If TRUE:**
- Increments `generated_count`
- Records ALT text in manifest entry
- Continues processing

**If FALSE:**
- Appends error: "Empty ALT text generated for {key}"
- Logs warning
- Continues to next entry (does not retry)

---

### Decision 2.4: Is LLaVA Response an Error?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._is_llava_error()`

**Condition**: Checks if description contains error patterns:
- Patterns: `'error'`, `'failed'`, `'cannot'`, `'unable'`, `'sorry'`, `'i cannot'`, `'i am unable'`, `'no description'`, `'not available'`, `'description not available'`, `'image could not be processed'`, `'cannot describe'`, `'unable to describe'`, `'failed to process'`, `'api error'`, `'request failed'`, `'timeout'`

**If TRUE:**
- Calls `_handle_llava_error_with_fallback()`
- Creates fallback description from shape properties
- Returns fallback ALT text instead of error message

**If FALSE:**
- Uses generated ALT text as-is
- Continues with normalization

---

### Decision 2.5: Should Use Vector Fallback? (WMF/EMF Handling)

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`

**Condition**: `filename.lower().endswith(('.wmf', '.emf'))` AND normalization fails

**If TRUE:**
- Calls `_generate_vector_fallback_alt(image_info, format_name)`
- Creates contextual description: "Vector graphic ({format_name} format)"
- Returns fallback ALT text (no LLaVA call)

**If FALSE:**
- Continues with image normalization
- Proceeds to LLaVA API call

---

### Decision 2.6: Should Use Contextual Fallback? (Error Patterns)

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`

**Condition**: Generated ALT text contains error patterns (same as Decision 2.4)

**If TRUE:**
- Calls `_generate_vector_fallback_alt(image_info, "Unknown")`
- Returns contextual fallback ALT text
- Does NOT return error message to user

**If FALSE:**
- Uses generated ALT text
- Applies normalization

---

### Decision 2.7: Should Use Emergency Fallback? (Final Guard)

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`

**Condition**: `not normalized_alt_text or 'error' in normalized_alt_text.lower()`

**If TRUE:**
- Calls `_generate_vector_fallback_alt(image_info, "Unknown")`
- Returns emergency fallback ALT text
- Logs: "IMPOSSIBLE-TO-MISS: Used emergency fallback"

**If FALSE:**
- Returns normalized ALT text
- Processing complete

---

### Decision 2.8: Should Use Shape Fallback? (Non-Picture Elements)

**Location**: `shared/manifest_processor.py::ManifestProcessor._generate_missing_alt_text()`

**Condition**: `not manifest.should_generate_for_shape_type(entry.shape_type)`

**If TRUE:**
- Calls `manifest.get_shape_fallback_alt(shape_type, is_group_child, width_px, height_px)`
- Creates descriptive ALT text from shape properties
- No LLaVA API call
- Normalizes fallback text

**If FALSE:**
- Proceeds with LLaVA generation (Decision 2.2)

---

### Decision 2.9: Should Use Connector/Line Bypass?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._check_element_bypass()`

**Condition**: `visual_element.element_type in ['connector', 'line']`

**If TRUE:**
- Returns bypass reason: "Using descriptive text for {element_type}"
- Calls `_create_connector_line_description()` instead of LLaVA
- Creates direct descriptive ALT text (no AI analysis)

**If FALSE:**
- Continues with normal generation path

**Additional bypass conditions:**
- `width_px < 5 or height_px < 5` → Returns "Element too small"
- `not hasattr(visual_element, 'shape') or visual_element.shape is None` → Returns "No shape data available"

---

## Phase 3: Mode and Meaningfulness Decisions

### Decision 3.1: What is the ALT Text Mode?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._determine_alt_decision()`

**Condition**: `normalized_mode` (from parameter or config)

**If mode == 'preserve':**
- Proceeds to Decision 3.2 (preserve logic)

**If mode == 'replace':**
- Proceeds to Decision 3.3 (replace logic)

**If mode == 'overwrite':**
- Normalized to 'replace' → Proceeds to Decision 3.3

**If mode not in {'preserve', 'replace'}:**
- Logs warning: "Unknown mode, defaulting to replace"
- Sets mode to 'replace' → Proceeds to Decision 3.3

---

### Decision 3.2: Preserve Mode - Which ALT Text to Use?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._determine_alt_decision()`

**Condition 3.2a**: `stored_final_alt` exists
- **If TRUE:** Decision = `'written_final'`, final_alt = stored_final_alt, should_write = True
- **If FALSE:** Continues

**Condition 3.2b**: `existing_alt` exists
- **If TRUE:** Decision = `'preserved_existing'`, final_alt = existing_alt, should_write = False
- **If FALSE:** Continues

**Condition 3.2c**: `candidate_generated` exists
- **If TRUE:** Decision = `'written_generated'`, final_alt = candidate_generated, should_write = True
- **If FALSE:** Decision = `'skipped_no_content'`, final_alt = '', should_write = False

---

### Decision 3.3: Replace Mode - Which ALT Text to Use?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._determine_alt_decision()`

**Condition 3.3a**: `candidate_generated` exists
- **If TRUE:** Decision = `'written_generated'`, final_alt = candidate_generated, should_write = True
- **If FALSE:** Continues

**Condition 3.3b**: `existing_alt` exists
- **If TRUE:** Decision = `'written_existing'`, final_alt = existing_alt, should_write = False
- **If FALSE:** Decision = `'skipped_no_content'`, final_alt = '', should_write = False

---

### Decision 3.4: Is Existing ALT Text Meaningful?

**Location**: `core/pptx_alt_injector.py::_is_meaningful()`
**Location**: `shared/pipeline_phases.py::_is_meaningful()`

**Condition 3.4a**: `value is None`
- **If TRUE:** Returns `False` (not meaningful)
- **If FALSE:** Continues

**Condition 3.4b**: `value.strip() == ""`
- **If TRUE:** Returns `False` (not meaningful)
- **If FALSE:** Continues

**Condition 3.4c**: `value.lower() in skip_tokens`
- Skip tokens: `{"(none)", "n/a", "not reviewed", "undefined", "image.png", "picture", ""}`
- **If TRUE:** Returns `False` (not meaningful)
- **If FALSE:** Returns `True` (meaningful)

**Note**: `_is_skip_token()` also checks minimum length (15 characters) and placeholder patterns.

---

### Decision 3.5: Is ALT Text Generic Placeholder?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._is_generic_placeholder_alt()`

**Condition 3.5a**: `text is None or text.strip() == ""`
- **If TRUE:** Returns `True` (is placeholder)
- **If FALSE:** Continues

**Condition 3.5b**: Matches any regex in `GENERIC_ALT_REGEXES`:
- `r"^\s*(a|an)\s+(picture|image|graphic|photo)\b"`
- `r"^\s*screenshot\b"`
- `r"^\s*(picture|image)\s*\d+\s*$"`
- `r"\(\s*\d+\s*x\s*\d+\s*px\s*\)\s*$"`
- `r"^\s*This is a PowerPoint shape\b"`
- `r"^\s*Image of\b"`
- `r"^\s*(picture|graphic|shape|object)\s*\.?\s*$"`
- `r"\bunknown\b"`
- `r"^\s*\w{1,4}\s*$"` (very short)

**If TRUE:**
- Returns `True` (is placeholder)
- Treated as not meaningful

**If FALSE:**
- Continues

**Condition 3.5c**: `len(words) > 6 and not text.endswith(('.', '!', '?'))`
- **If TRUE:** Returns `True` (low-value, no sentence termination)
- **If FALSE:** Returns `False` (not placeholder)

---

### Decision 3.6: Should Replace Existing ALT Text? (Normalized Comparison)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._should_replace_alt_text_normalized()`

**Condition 3.6a**: `not new_text or not new_text.strip()`
- **If TRUE:** Returns `False` (don't replace with empty)
- **If FALSE:** Continues

**Condition 3.6b**: `not current_text or not current_text.strip()`
- **If TRUE:** Returns `True` (replace empty with new)
- **If FALSE:** Continues

**Condition 3.6c**: `normalized_new.lower() != normalized_current.lower()`
- Normalizes both texts via `_normalize_alt_universal()`
- **If TRUE:** Returns `True` (texts differ, replace)
- **If FALSE:** Returns `False` (texts equivalent, don't replace)

---

## Phase 4: Injection Decisions

### Decision 4.1: Should Write ALT Text? (Preserve Mode Guard)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Condition**: `self.mode == 'preserve' and _is_meaningful(existing) and not preserve_override`

**If TRUE:**
- Logs: "Preserving existing ALT text"
- Increments `statistics['skipped_existing']`
- Returns `False` (injection skipped)

**If FALSE:**
- Continues to next decision

---

### Decision 4.2: Should Write ALT Text? (Preserve Override)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Condition**: `preserve_override and self.mode == 'preserve' and _is_meaningful(existing)`

**If TRUE:**
- Logs: "PRESERVE_OVERRIDE: Forcing write despite existing ALT"
- Continues to injection (override applied)

**If FALSE:**
- Continues to next decision

---

### Decision 4.3: Should Write ALT Text? (Idempotent Guard)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Condition**: `not _should_replace_alt_text_normalized(existing, text)`

**If TRUE:**
- Logs: "Skipping equivalent text (normalized texts are identical)"
- Returns `False` (injection skipped)

**If FALSE:**
- Continues to next decision

---

### Decision 4.4: Should Write ALT Text? (Duplicate Hash Check)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Condition**: `element_key in self.final_writes and text_hash == existing_hash`

**If TRUE:**
- Logs: "Skipping duplicate hash"
- Returns `False` (injection skipped, already written)

**If FALSE:**
- Continues to injection

---

### Decision 4.5: Should Skip ALT Text? (Reinjection Rules)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._should_skip_alt_text()`

**Condition**: `alt_text_stripped == skip_pattern` (for each pattern in `skip_alt_text_if`)

**Skip patterns** (from config: `reinjection.skip_alt_text_if`):
- `""`, `"undefined"`, `"(None)"`, `"N/A"`, `"Not reviewed"`, `"n/a"`

**If TRUE:**
- Returns `True` (skip this ALT text)
- Injection does not occur

**If FALSE:**
- Continues checking other patterns
- If no patterns match, returns `False` (don't skip)

---

### Decision 4.6: Which Candidate ALT Text to Use?

**Location**: `core/pptx_alt_injector.py::_choose_candidate()`

**Condition 4.6a**: `record is None`
- **If TRUE:** Returns `None` (no candidate)
- **If FALSE:** Continues

**Condition 4.6b**: `isinstance(record, str)`
- **If TRUE:** Returns `record.strip()` (use string directly)
- **If FALSE:** Continues

**Condition 4.6c**: Checks fields in order: `"final_alt"`, `"generated_alt"`, `"existing_alt"`
- For each field, checks: `isinstance(value, str) and _is_meaningful(value)`
- **If TRUE:** Returns `value.strip()` (first meaningful field found)
- **If FALSE:** Continues to next field

**Condition 4.6d**: `record.get("final_alt")` exists (even if not meaningful)
- **If TRUE:** Returns `final_alt.strip()` (use final_alt as fallback)
- **If FALSE:** Returns `None` (no candidate)

---

### Decision 4.7: Should Write Based on Decision?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector.inject_alt_text_from_mapping()`

**Condition**: `decision == 'preserved_existing'`

**If TRUE:**
- Increments `statistics['preserved_existing']`
- Skips injection (continues to next element)

**If FALSE:**
- Continues to next check

**Condition**: `decision == 'skipped_no_content'`

**If TRUE:**
- Increments `statistics['skipped_no_content']`
- Skips injection (continues to next element)

**If FALSE:**
- Continues to injection

**Condition**: `plan.should_write` (from `_determine_alt_decision()`)

**If TRUE:**
- Proceeds with injection via `_inject_alt_text_single()`

**If FALSE:**
- Skips injection (continues to next element)

---

### Decision 4.8: Should Write? (Write Guard in _write_descr_and_title)

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._write_descr_and_title()`

**Condition**: `mode == "preserve" and _has_meaningful_alt(shape) and not preserve_override`

**If TRUE:**
- Logs: "WRITE_GUARD TRIGGERED: Preserve mode, existing ALT found"
- Returns early (no write occurs)

**If FALSE:**
- Continues with XML write

**Condition**: `preserve_override and mode == "preserve" and _has_meaningful_alt(shape)`

**If TRUE:**
- Logs: "WRITE_GUARD OVERRIDDEN: Writing despite preserve mode"
- Continues with XML write

**If FALSE:**
- Continues with XML write

---

## Phase 5: Group Processing Decisions

### Decision 5.1: Should Group Get Parent ALT Text?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._decide_group_alt_rollup()`

**Condition 5.1a**: `meaningful_count == 0` (no meaningful children)
- **If TRUE:** 
  - Checks `semantic_type = _detect_group_semantic_type()`
  - **If semantic_type exists:** Parent ALT = `"Group representing {semantic_type} icon"`
  - **Else if text_children_count > 0:** Parent ALT = `"Group containing {N} text element(s)"`
  - **Else if decorative_children_count > 0:** Parent ALT = `"Group containing {N} decorative element(s)"`
  - **Else:** Parent ALT = `"Group containing {N} element(s)"`
  - Returns `(True, parent_alt, [])` (create parent ALT, no children marked decorative)
- **If FALSE:** Continues

**Condition 5.1b**: `meaningful_count == 1` (single meaningful child)
- **If TRUE:**
  - Checks `parent_semantic_type = _detect_group_semantic_type()`
  - **If parent_semantic_type exists:** Parent ALT = `"Group representing {semantic_type} icon"`, mark child decorative
  - **Else:** Parent ALT = `"Group containing {element_type}"`, both keep ALT
  - Returns `(True, parent_alt, children_to_mark_decorative)`
- **If FALSE:** Continues

**Condition 5.1c**: `meaningful_count > 1` (multiple meaningful children)
- **If TRUE:**
  - Checks `parent_semantic_type = _detect_group_semantic_type()`
  - **If parent_semantic_type exists:** Parent ALT = `"Group representing {semantic_type} icon with {N} elements"`
  - **Else:** Checks if all children same type
    - **If same type:** Parent ALT = `"Group of {N} {type}s"`
    - **Else:** Parent ALT = `"Group containing {N} visual elements"`
  - Returns `(True, parent_alt, [])` (no children marked decorative)
- **If FALSE:** Returns `(False, "", [])` (no parent ALT)

---

### Decision 5.2: Should Detect Semantic Icon Type?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._detect_group_semantic_type()`

**Condition**: `getattr(self, "enable_semantic_icon_labels", False)`

**If TRUE:**
- Analyzes group dimensions and child patterns
- Checks aspect ratios and child counts
- May return: "lightbulb", "brain", "lungs", "graduation cap", "complex icon", "composite icon"
- **If detected:** Returns semantic type string
- **If not detected:** Returns `None`

**If FALSE:**
- Returns `None` immediately (semantic detection disabled)

**Semantic detection patterns** (if enabled):
- Lightbulb: `0.8 <= aspect_ratio <= 1.4 and total_children >= 3 and decorative_count >= 2`
- Brain: `0.9 <= aspect_ratio <= 1.6 and total_children >= 5`
- Lungs: `1.2 <= aspect_ratio <= 2.0 and total_children >= 2`
- Graduation cap: `0.7 <= aspect_ratio <= 1.5 and total_children >= 2`
- Complex icon: `total_children >= 5`
- Composite icon: `total_children >= 3`

---

## Phase 6: Error and Fallback Decisions

### Decision 6.1: Should Use Fallback Description? (Shape Elements)

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor.process_pptx()`

**Condition**: Generation failed OR `visual_element.element_type in ['shape', 'text_placeholder', 'text_box', 'line', 'connector']`

**If TRUE:**
- Calls `_create_enhanced_fallback_description(visual_element)`
- Checks `_check_element_bypass(visual_element)`
- **If bypass reason exists:** Composes ALT with bypass annotation
- **Else:** Uses fallback description directly
- Stores in `alt_text_mapping` with `'fallback_used': True`

**If FALSE:**
- Uses generated ALT text (if available)
- Or marks as failed if no generation occurred

---

### Decision 6.2: Should Use Degradation Response? (LLaVA Unavailable)

**Location**: `shared/unified_alt_generator.py::LLaVAProvider.generate_alt_text()`

**Condition**: `not _run_pre_flight_validation()`

**If TRUE:**
- Calls `_create_degradation_response(custom_prompt, image_path)`
- Returns fallback ALT text without calling API
- Metadata marked as `"degraded": True`

**If FALSE:**
- Proceeds with API call

---

### Decision 6.3: Should Use Hardened Execution?

**Location**: `shared/unified_alt_generator.py::LLaVAProvider.generate_alt_text()`

**Condition**: `self.connectivity_manager` exists

**If TRUE:**
- Calls `connectivity_manager.execute_with_hardening()`
- Uses retry logic and circuit breaker
- **If hardened execution fails:** Falls back to degradation response

**If FALSE:**
- Calls `_execute_generation_request()` directly
- No retry logic or circuit breaker

---

## Phase 7: Quality and Validation Decisions

### Decision 7.1: Is Generated ALT Text Valid?

**Location**: `core/pptx_processor.py::PPTXAccessibilityProcessor._generate_alt_text_for_image_with_validation()`

**Condition 7.1a**: `alt_text is None`
- **If TRUE:** Returns `(None, "Generator returned None")`
- **If FALSE:** Continues

**Condition 7.1b**: `not isinstance(alt_text, str)`
- **If TRUE:** Returns `(None, "Generator returned non-string type")`
- **If FALSE:** Continues

**Condition 7.1c**: `not alt_text.strip()`
- **If TRUE:** Returns `(None, "Generator returned empty or whitespace-only string")`
- **If FALSE:** Continues

**Condition 7.1d**: `len(alt_text_stripped) < 3`
- **If TRUE:** Returns `(None, "Generator returned very short ALT text")`
- **If FALSE:** Continues (validation passed)

---

### Decision 7.2: Should Block Fallback Pattern?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._is_blocked_fallback_pattern()`

**Condition**: Text matches blocked patterns:
- `"This is a PowerPoint shape"`
- `"unknown ("`
- `"text placeholder ("`
- `"chart ("`
- `"table ("`
- `"group shape ("`
- `"connector ("`
- `"shape with no specific content"`
- `"[Generated description not available]"`

**If TRUE:**
- Returns `True` (pattern blocked)
- Text will be blocked by centralized gate

**If FALSE:**
- Returns `False` (pattern allowed)
- Text proceeds to injection

---

### Decision 7.3: Should Apply Centralized Gate?

**Location**: `core/pptx_alt_injector.py::PPTXAltTextInjector._inject_alt()`

**Condition**: `apply_for_ppt_injection(text, "shape", quality_flags, policy, shape)` returns `None`

**If TRUE:**
- Logs: "Text blocked by centralized gate"
- Returns `False` (injection skipped)

**If FALSE:**
- Uses gated text (may be modified by gate)
- Continues to injection

---

## Summary: Decision Flow

**Generation Phase:**
1. Element type → Render to image? → Generate via LLaVA?
2. Shape type → Use LLaVA or fallback?
3. Thumbnail exists? → Generate or skip?
4. Generation success? → Use result or fallback?
5. Error detected? → Use fallback or error?

**Mode Phase:**
1. Mode = preserve? → Check existing meaningful?
2. Mode = replace? → Use generated?
3. Existing meaningful? → Preserve or replace?

**Injection Phase:**
1. Preserve mode + meaningful existing? → Skip injection
2. Texts equivalent? → Skip injection
3. Already written? → Skip injection
4. Should write? → Inject ALT text

**Group Phase:**
1. Meaningful children count? → Determine parent ALT strategy
2. Semantic type detected? → Use semantic description
3. Mark children decorative? → Based on roll-up policy
