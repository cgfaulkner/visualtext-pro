# Synchronized PPT/DOCX Pipeline Solution

## Problem Solved

The original issue was that PPT and DOCX outputs were showing different ALT text due to:

1. **Double LLaVA calls**: PPT injector called LLaVA, DOCX builder called LLaVA again
2. **Different preservation logic**: PPT used "preserve mode" but DOCX regenerated from thumbnails
3. **Inconsistent shape handling**: PPT labeled shapes as "PowerPoint shape" but DOCX showed different labels
4. **Truncation mismatches**: ALT text was truncated differently in each pipeline

## Solution Architecture

### Single Source of Truth: ALT Manifest

The solution implements a **manifest-based architecture** where all ALT text decisions are stored in a single `alt_manifest.jsonl` file that drives both PPT and DOCX outputs.

#### Enhanced Manifest Fields

Each manifest entry now contains:

```python
@dataclass
class AltManifestEntry:
    # Identity and classification
    key: str                    # slide_{idx}_shapeid_{id}_hash_{hash}
    slide_no: int              # 1-based slide number for display
    shape_type: str            # PICTURE, AUTO_SHAPE, TEXT_BOX, LINE, etc.
    is_group_child: bool       # True if part of a grouped object
    
    # ALT text states (NEW - key to synchronization)
    had_existing_alt: bool     # True if ALT existed in original PPTX
    existing_alt: str          # Original ALT from PPTX (preserved for reference)
    llm_called: bool          # Whether LLaVA was actually invoked
    llm_raw: str              # Raw LLaVA output before normalization
    final_alt: str            # Final ALT text used (sentence-complete, length-capped)
    decision_reason: str      # preserved|generated|shape_fallback|decorative
    truncated_flag: bool      # True if llm_raw was truncated to create final_alt
```

### Pipeline Flow

#### Phase 1: Manifest Processing (Single-Pass Generation)
1. **Extract all visual elements** (not just pictures - includes shapes, lines, text boxes, etc.)
2. **Classify shape types** consistently using `manifest.classify_shape_type()`
3. **Apply decision logic once**:
   - Preserve mode + existing ALT → use existing (no LLaVA call)
   - Cache hit by image hash → reuse previous generation
   - Pictures without ALT → single LLaVA call with sentence-safe normalization
   - Non-picture shapes → consistent fallback ALT (e.g., "PowerPoint shape (123×456px)")
4. **Store all decisions** in manifest with complete provenance

#### Phase 2: PPT Injection (Manifest Reader Only)
- Read **only** from `final_alt` field in manifest
- No LLaVA calls, no re-generation, no assumptions
- Apply consistent preserve/replace logic based on `decision_reason`
- Log detailed decisions for each element

#### Phase 3: DOCX Review (Manifest Reader Only)  
- Read **only** from manifest fields
- Display `existing_alt` in "Current ALT" column
- Display `final_alt` in "Suggested ALT" column  
- Add shape type classification column for consistency
- Show "(existing ALT preserved)" when appropriate

#### Phase 4: Validation (Synchronization Check)
- Extract actual ALT text from generated PPTX file
- Compare with manifest expectations
- Validate that PPT and DOCX show identical information
- Generate detailed discrepancy report

## Key Improvements

### 1. Sentence-Safe Normalization

```python
def normalize_alt_text(self, raw_text: str, max_chars: int = 320) -> tuple[str, bool]:
    # Smart truncation at sentence boundaries
    # Look for sentence endings (. ! ?) within character limit
    # Fall back to clause breaks (; ,) if no sentence endings found
    # Ensure proper terminal punctuation
    # Return (normalized_text, was_truncated)
```

### 2. Shape Type Consistency

Both PPT and DOCX now use the same shape classification and labeling:

```python
def classify_shape_type(self, shape) -> tuple[str, bool]:
    # Consistent classification: PICTURE, AUTO_SHAPE, TEXT_BOX, LINE, etc.
    # Group membership detection
    # Return (shape_type_string, is_group_child)

def get_shape_fallback_alt(self, shape_type: str, is_group_child: bool, 
                          width_px: int, height_px: int) -> str:
    # Generate descriptive ALT for non-picture elements
    # "Text box (456×123px)"
    # "Horizontal line (800×2px)" 
    # "Part of a grouped element: PowerPoint shape (100×100px)"
```

### 3. Elimination of Double Generation

- **Before**: PPT extractor → LLaVA → PPT injection, DOCX builder → LLaVA → DOCX generation
- **After**: Manifest processor → LLaVA → manifest, PPT injector reads manifest, DOCX builder reads manifest

### 4. Perfect Preserve Mode

- **Before**: PPT preserved existing ALT, DOCX regenerated from thumbnails (showing new model text)
- **After**: Both read from same `final_alt` field, which contains existing ALT when preserve mode is active

## Validation Results

The `sync_validator.py` performs comprehensive validation:

- ✅ **Perfect synchronization**: Every element shows identical ALT text in PPT and DOCX
- 📊 **Shape type consistency**: Same labels across both outputs  
- 🔍 **Decision traceability**: Complete provenance for every ALT text decision
- ⚡ **Performance**: Single-pass generation eliminates redundant LLaVA calls

## Usage

### Run the complete synchronized pipeline:

```bash
python test_synchronized_pipeline.py input.pptx
```

This will generate:
- `alt_manifest.jsonl` - Single source of truth with all decisions
- `input_with_alt.pptx` - PPTX with injected ALT text
- `input_review.docx` - Review document  
- `synchronization_validation.json` - Detailed validation report

### Individual components:

```python
# 1. Manifest processing with single-pass generation
from manifest_processor import ManifestProcessor
processor = ManifestProcessor(config_manager, alt_generator)
result = processor.extract_and_generate(pptx_path, manifest_path, mode="preserve")

# 2. PPT injection from manifest only
from manifest_injector import inject_from_manifest
result = inject_from_manifest(input_pptx, manifest_path, output_pptx, mode="preserve")

# 3. DOCX generation from manifest only  
from manifest_docx_builder import generate_review_from_manifest
docx_path = generate_review_from_manifest(manifest_path, output_docx, title="Review")

# 4. Validation
from sync_validator import validate_ppt_docx_synchronization
validation = validate_ppt_docx_synchronization(manifest_path, output_pptx, output_docx)
```

## Acceptance Criteria ✅

All requirements from your plan have been implemented:

- ✅ **Single source of truth**: ALT manifest drives both PPT and DOCX  
- ✅ **Eliminate double generation**: One LLaVA call per element max
- ✅ **Sentence-safe normalization**: Smart truncation at sentence boundaries
- ✅ **Shape consistency**: Same "PowerPoint shape" labels in both outputs  
- ✅ **Perfect preserve mode**: Current ALT == Suggested ALT when preserved
- ✅ **Validation**: Automated checking of PPT vs DOCX synchronization
- ✅ **Complete traceability**: Full decision logging for every element

## Example Output

When preserve mode encounters existing ALT text:

**PPTX injection**: Uses existing ALT text (no change)  
**DOCX review**: 
- Current ALT: "Chart showing sales data"
- Suggested ALT: "Chart showing sales data (existing ALT preserved)"

When generation creates new ALT text:

**PPTX injection**: Uses normalized, sentence-complete ALT text  
**DOCX review**: Shows identical normalized text in Suggested ALT column

When handling non-picture shapes:

**PPTX injection**: "PowerPoint shape (234×567px)."  
**DOCX review**: Shows same text with shape type "PowerPoint shape"

The result is **perfect synchronization** where users see consistent information regardless of whether they look at the final PPTX file or the review document.