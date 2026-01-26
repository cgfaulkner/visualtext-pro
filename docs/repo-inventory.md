# Repository Inventory

**Generated:** 2026-01-26  
**Last Updated:** 2026-01-26 (Selector migration completed)  
**Repository Root:** `pdf-alt`

## 1. Repository Overview

### Root Folder Name
`pdf-alt`

### Python Packages (folders containing `__init__.py`)

1. `approval/` - Approval pipeline and review tools
2. `core/` - Core processing modules (PPTX, DOCX, PDF processors)
3. `shared/` - Shared utilities and pipeline infrastructure (includes `shared/selector/` for Smart Selector)

## 2. Directory Tree (Depth 4)

```
pdf-alt/
├── .claude_docs/
│   ├── artifact_integration_verification.md
│   ├── batch_processing_implementation.md
│   ├── bugfix_absolute_path_validation.md
│   └── file_locking_implementation.md
├── .github/
│   └── workflows/
│       └── validate-selector-schema.yml
├── approval/
│   ├── __init__.py
│   ├── approval_pipeline.py
│   ├── docx_alt_review.py
│   └── llava_adapter.py
├── core/
│   ├── __init__.py
│   ├── backup/
│   │   ├── pdf_accessibility_recreator.py
│   │   ├── pdf_alt_injector.py
│   │   ├── pdf_context_extractor.py
│   │   ├── pdf_processor.py
│   │   ├── pptx_alt_injector.py
│   │   └── pptx_processor.py
│   ├── batch_processor.py
│   ├── docx_processor.py
│   ├── pptx_alt_injector.py
│   ├── pptx_batch_processor.py
│   └── pptx_processor.py
├── docs/
│   ├── repo-inventory.md (this file)
│   └── smart-selector-contract.md
├── old_project/
│   ├── batch_pptx_processor_linked.py
│   ├── concepts.py
│   ├── config_manager.py
│   ├── config.yaml
│   ├── llava_alt_generator.py
│   ├── pptx_alt.py
│   └── unified_alt_generator.py
├── schemas/
│   └── selector_manifest.schema.json
├── shared/
│   ├── __init__.py
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
├── tests/
│   ├── __init__.py
│   ├── fixtures/
│   │   └── selector/
│   │       ├── group_basic/
│   │       ├── overlay_arrow_on_image/
│   │       └── placeholder_alt_cases/
│   └── test_selector.py
├── tools/
│   └── validate_selector_manifest.py
├── .gitignore
├── AGENTS.md
├── altgen.py
├── analyze_pdf_structure.py
├── BATCH_PROCESSING_REVIEW.md
├── config.yaml
├── extract_content_streams.py
├── LICENSE
├── pptx_alt_processor.py
├── pptx_clean_processor.py
├── pptx_manifest_processor.py
├── README.md
└── requirements.txt
```

## 3. CLI Entry Points

Files that define `main()` or use `argparse`/`typer`/`click`:

### Primary CLI Entry Points

1. **`altgen.py`** (line 341: `def main()`)
   - Uses `argparse` (line 7, 243)
   - Imports pipeline from: `core.batch_processor` (line 349)
   - Imports shared utilities: `shared.path_validator` (line 350)
   - Main dispatcher for all processing commands

2. **`pptx_clean_processor.py`** (line 139: `def main()`)
   - Uses `argparse` (line 16)
   - Imports pipeline from: `shared.pipeline_phases` (line 34: `run_pipeline`)
   - Imports pipeline artifacts: `shared.pipeline_artifacts` (line 33: `RunArtifacts`)
   - Imports shared utilities: `shared.config_manager`, `shared.docx_review_builder`, `shared.path_validator`

3. **`pptx_alt_processor.py`** (line 1146: `def main()`)
   - Uses `argparse` (line 21)
   - Imports from: `core.pptx_processor` (PPTXAccessibilityProcessor)
   - Legacy processor (not using new pipeline architecture)

4. **`pptx_manifest_processor.py`** (line 51: `def main()`)
   - Uses `argparse` (line 16)
   - Imports from: `shared.manifest_processor` (ManifestProcessor)
   - Uses manifest-based processing

5. **`tools/validate_selector_manifest.py`** (line 12: `def main()`)
   - Uses `argparse` (line 2)
   - Standalone validation tool (no pipeline imports)
   - Validates selector manifest JSON against schema

### Secondary/Utility Entry Points

6. **`core/pptx_processor.py`** (line 6095: `def main()`)
   - Legacy processor entry point

7. **`core/pptx_alt_injector.py`** (line 3581: `def main()`)
   - Uses `argparse` (line 42)
   - ALT text injection utility

8. **`core/docx_processor.py`** (line 422: `def main()`)
   - Uses `argparse` (line 28)
   - DOCX processing utility

9. **`core/pptx_batch_processor.py`** (line 393: `def main()`)
   - Uses `argparse` (line 395)
   - Batch processing utility

## 4. String Reference Inventory

### `visualtext_pro`

**Total:** 0 references in code/tests/config

**Note:** `visualtext_pro` only appears in this documentation file (for historical reference). All code now uses `shared.selector`.

### `run_selector`

| File | Line | Context |
|------|------|---------|
| `shared/pipeline_phases.py` | 457 | Function name: `def phase1_9_run_selector(...)` |
| `shared/pipeline_phases.py` | 462 | Docstring: "Calls run_selector() to generate selector_manifest.json" |
| `shared/pipeline_phases.py` | 478 | Import: `from .selector import run_selector` |
| `shared/pipeline_phases.py` | 482 | Function call: `manifest_path = run_selector(pptx_path, config, output_path=artifacts.selector_manifest_path)` |
| `shared/pipeline_phases.py` | 590 | Function call: `selector_result = phase1_9_run_selector(pptx_path, artifacts, config)` |
| `shared/selector/selector.py` | 95 | Function definition: `def run_selector(pptx_path: Path, config: Dict[str, Any], output_path: Path | None = None) -> Path:` |
| `shared/selector/__init__.py` | 3 | Import: `from .selector import run_selector` |
| `shared/selector/__init__.py` | 13 | Export: `"run_selector",` |
| `tests/test_selector.py` | 86 | Import: `from shared.selector import run_selector` |
| `tests/test_selector.py` | 143 | Import: `from shared.selector import run_selector` |
| `tests/test_selector.py` | 186 | Import: `from shared.selector import run_selector` |

**Total:** 11 references

### `selector_manifest`

| File | Line | Context |
|------|------|---------|
| `.github/workflows/validate-selector-schema.yml` | 7 | Path in workflow: `'schemas/selector_manifest.schema.json'` |
| `.github/workflows/validate-selector-schema.yml` | 13 | Path in workflow: `'schemas/selector_manifest.schema.json'` |
| `.github/workflows/validate-selector-schema.yml` | 34 | Path in command: `tests/fixtures/selector/group_basic/selector_manifest.json.golden` |
| `.github/workflows/validate-selector-schema.yml` | 35 | Path in command: `tests/fixtures/selector/overlay_arrow_on_image/selector_manifest.json.golden` |
| `.github/workflows/validate-selector-schema.yml` | 36 | Path in command: `tests/fixtures/selector/placeholder_alt_cases/selector_manifest.json.golden` |
| `shared/pipeline_phases.py` | 462 | Docstring: "Calls run_selector() to generate selector_manifest.json" |
| `shared/pipeline_phases.py` | 481 | Comment: "# Run selector - writes to artifacts.selector_manifest_path" |
| `shared/pipeline_phases.py` | 482 | Function call: `manifest_path = run_selector(..., output_path=artifacts.selector_manifest_path)` |
| `shared/pipeline_phases.py` | 489 | Path construction: `"schemas" / "selector_manifest.schema.json"` |
| `shared/pipeline_artifacts.py` | 120 | Field comment: `# selector/selector_manifest.json` |
| `shared/pipeline_artifacts.py` | 170 | Path construction: `run_dir / "selector" / "selector_manifest.json"` |
| `visualtext_pro/selector/selector.py` | 102 | Docstring: "output_path: Optional path to write selector_manifest.json" |
| `visualtext_pro/selector/selector.py` | 105 | Docstring: "Path to written selector_manifest.json file" |
| `visualtext_pro/selector/selector.py` | 161 | Path construction: `output_path = Path(output_dir) / "selector_manifest.json"` |
| `visualtext_pro/selector/selector.py` | 164 | Path construction: `output_path = pptx_path.parent / "selector_manifest.json"` |
| `tools/validate_selector_manifest.py` | 15 | Default schema path: `Path("schemas/selector_manifest.schema.json")` |
| `config.yaml` | 148 | Config entry: `schema_path: "schemas/selector_manifest.schema.json"` |

**Total:** 17 references

### `selector_manifest.schema.json`

| File | Line | Context |
|------|------|---------|
| `.github/workflows/validate-selector-schema.yml` | 7 | Workflow path trigger |
| `.github/workflows/validate-selector-schema.yml` | 13 | Workflow path trigger |
| `shared/pipeline_phases.py` | 489 | Path construction: `Path(__file__).parent.parent / "schemas" / "selector_manifest.schema.json"` |
| `tools/validate_selector_manifest.py` | 15 | Default schema path argument |

**Total:** 4 references (as literal filename)

### `validate_selector_manifest`

| File | Line | Context |
|------|------|---------|
| `.github/workflows/validate-selector-schema.yml` | 34 | Command: `python tools/validate_selector_manifest.py ...` |
| `.github/workflows/validate-selector-schema.yml` | 35 | Command: `python tools/validate_selector_manifest.py ...` |
| `.github/workflows/validate-selector-schema.yml` | 36 | Command: `python tools/validate_selector_manifest.py ...` |

**Total:** 3 references (all in CI workflow)

## 5. Selector-Related Files

### Implementation Files

1. **`shared/selector/selector.py`**
   - Main selector implementation
   - Defines `run_selector()` function
   - Location: `shared/selector/selector.py`

2. **`shared/selector/types.py`**
   - Type definitions (SelectorDecision, ContentScope, EscalationStrategy, etc.)
   - Location: `shared/selector/types.py`

3. **`shared/selector/__init__.py`**
   - Package initialization and exports
   - Location: `shared/selector/__init__.py`

### Schema & Validation

5. **`schemas/selector_manifest.schema.json`**
   - JSON Schema for selector manifest validation
   - Location: `schemas/selector_manifest.schema.json`

6. **`tools/validate_selector_manifest.py`**
   - Standalone validation script
   - Location: `tools/validate_selector_manifest.py`

### Tests

7. **`tests/test_selector.py`**
   - Test suite for selector functionality
   - Location: `tests/test_selector.py`

8. **`tests/fixtures/selector/group_basic/selector_manifest.json.golden`**
   - Golden JSON fixture
   - Location: `tests/fixtures/selector/group_basic/`

9. **`tests/fixtures/selector/overlay_arrow_on_image/selector_manifest.json.golden`**
   - Golden JSON fixture
   - Location: `tests/fixtures/selector/overlay_arrow_on_image/`

10. **`tests/fixtures/selector/placeholder_alt_cases/selector_manifest.json.golden`**
    - Golden JSON fixture
    - Location: `tests/fixtures/selector/placeholder_alt_cases/`

### Documentation

11. **`docs/smart-selector-contract.md`**
    - Selector contract specification
    - Location: `docs/smart-selector-contract.md`

### CI/CD

12. **`.github/workflows/validate-selector-schema.yml`**
    - CI workflow for schema validation
    - Location: `.github/workflows/validate-selector-schema.yml`

## 6. Canonical Location Analysis

### Existing Architecture Patterns

**`shared/` Directory:**
- Contains pipeline infrastructure: `pipeline_phases.py`, `pipeline_artifacts.py`
- Contains shared utilities: `config_manager.py`, `manifest_processor.py`, `unified_alt_generator.py`
- Contains processing helpers: `alt_manifest.py`, `docx_review_builder.py`, `shape_renderer.py`
- **Pattern:** Pipeline stages, shared utilities, cross-cutting concerns

**`core/` Directory:**
- Contains processors: `pptx_processor.py`, `docx_processor.py`, `batch_processor.py`
- Contains injectors: `pptx_alt_injector.py`
- **Pattern:** Concrete implementations of file format processors

**Root Level:**
- CLI entry points: `altgen.py`, `pptx_clean_processor.py`, `pptx_manifest_processor.py`
- **Pattern:** Executable scripts that orchestrate processing

**`tools/` Directory:**
- Utility scripts: `validate_selector_manifest.py`
- **Pattern:** Standalone tools and utilities

**`schemas/` Directory:**
- JSON schemas: `selector_manifest.schema.json`
- **Pattern:** Schema definitions (consistent with existing structure)

**`tests/` Directory:**
- Test files: `test_selector.py`
- **Pattern:** Test code (consistent with existing structure)

### Analysis: Where Should Selector Live?

The Smart Selector is:
- A **pipeline stage** (called from `shared/pipeline_phases.py`)
- A **shared utility** (used by the pipeline infrastructure)
- **Not** a file format processor (doesn't process PPTX/DOCX/PDF directly)
- **Not** a CLI entry point

**Conclusion:** The selector should live in `shared/selector/` to match the existing architecture pattern where:
- Pipeline stages are in `shared/` (e.g., `pipeline_phases.py`)
- Shared utilities are in `shared/` (e.g., `manifest_processor.py`, `unified_alt_generator.py`)
- The selector is imported by `shared/pipeline_phases.py`, indicating it's part of the shared pipeline infrastructure

**Status:** ✅ **Migration completed** - The selector now lives in `shared/selector/` and the repository architecture is aligned.

### Current Location (Post-Migration)

| Component | Current Location | Status |
|-----------|------------------|--------|
| Selector implementation | `shared/selector/selector.py` | ✅ Migrated |
| Type definitions | `shared/selector/types.py` | ✅ Migrated |
| Package init | `shared/selector/__init__.py` | ✅ Migrated |
| Schema | `schemas/selector_manifest.schema.json` | ✅ Correct |
| Validation tool | `tools/validate_selector_manifest.py` | ✅ Correct |
| Tests | `tests/test_selector.py` | ✅ Correct |

## 7. Fix Plan

### Status: ✅ COMPLETED

**Completed on:** 2026-01-26

### Objective
Move `visualtext_pro/selector/` to `shared/selector/` to align with existing repository architecture.

### Migration Summary

#### Step 1: Move Selector Package ✅
- **Moved:** `visualtext_pro/selector/` → `shared/selector/`
- **Files moved:**
  - `visualtext_pro/selector/selector.py` → `shared/selector/selector.py`
  - `visualtext_pro/selector/types.py` → `shared/selector/types.py`
  - `visualtext_pro/selector/__init__.py` → `shared/selector/__init__.py`

#### Step 2: Remove Empty Package ✅
- **Deleted:** `visualtext_pro/__init__.py`
- **Deleted:** `visualtext_pro/` directory (now empty)

#### Step 3: Update Imports ✅

**File: `shared/pipeline_phases.py`**
- **Line 478:** Changed `from visualtext_pro.selector import run_selector` 
- **To:** `from .selector import run_selector` (relative import within shared/)

**File: `tests/test_selector.py`**
- **Lines 86, 143, 186:** Changed `from visualtext_pro.selector import run_selector`
- **To:** `from shared.selector import run_selector` (absolute import)

#### Step 4: Update Test Imports

**File: `tests/test_selector.py`**
- **Line ~80 (approx):** If imports `from visualtext_pro.selector import run_selector`
- **Change to:** `from shared.selector import run_selector`
- **OR:** Adjust sys.path if needed to import from shared/

#### Step 5: Verify No Other References
- **Search for:** `visualtext_pro` in entire codebase
- **Expected:** Only remaining reference should be in this inventory document
- **Action:** Update any remaining references

#### Step 6: Update Documentation
- **File:** `docs/smart-selector-contract.md` (if it references package location)
- **File:** `README.md` (if it references package location)
- **Action:** Update any package path references

### Import Pattern Options

**Option A: Absolute Import (Recommended)**
```python
from shared.selector import run_selector
```

**Option B: Relative Import (within shared/)**
```python
from .selector import run_selector  # In shared/pipeline_phases.py
```

**Option C: Direct Import (if shared/ is in path)**
```python
from selector import run_selector  # Requires shared/ in sys.path
```

**Recommendation:** Use Option A (absolute import) for clarity and consistency with existing code patterns in `shared/`.



---

**End of Inventory**
