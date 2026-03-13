# Implementation Plan: Conversion-First LLaVA Gate (Revised)

**Goal:** Single unified gate at the LLaVA entrypoint with default convert-then-proceed, optional strict rejection, safe path validation, atomic conversion, structured logging, and backwards-compatible metadata. Minimal scope: no architecture rewrite.

---

## What changed from the current plan

- **Runtime policy made explicit:** Default is convert-then-proceed (not fail-closed reject); strict mode is opt-in via `paths.strict_llava_gate: false`. Rationale for default stated in plan.
- **Path validation tightened:** Containment uses only `Path.resolve()` plus relative containment (e.g. `is_relative_to`); rejection only by containment under configured thumbnail folder and/or exact path segment `"thumbs"` (no substring). Allowed dirs are primarily resolved known dirs (temp_folder, allowed_extra_dirs, system temp); any “crops” segment rule is secondary/fallback.
- **Symlink policy added:** One approach specified (resolve input path once; compare resolved path to resolved allowed dirs; no inode check). Brief justification included.
- **Atomic conversion made explicit:** Unique temp filename (e.g. UUID), atomic write/rename, location under temp_folder, and note that converted files are covered by existing temp cleanup.
- **Structured logging and metadata contract:** Single structured log payload with required fields; manifest optional fields use exact names `llava_image_path`, `llava_image_source`, `llava_normalized_path`, `llava_image_width`, `llava_image_height`, `llava_image_size_bytes`; all explicitly optional for backwards compatibility.
- **Size/readability acceptance:** Test that normalized image width is at or above a configurable threshold (e.g. 512 px); test that thumbnail remains distinctly smaller (by dimensions or path/artifact type). Threshold location in config specified.
- **Windows / mixed-path coverage:** Tests for Windows-style paths and path normalization; validator correctness across platforms (e.g. parametrized or PureWindowsPath).
- **Provider-call assertions strengthened:** Tests explicitly assert: default mode → provider called only with normalized path; strict mode → provider not called for thumbnail path; legacy callers do not silently pass thumbs.
- **Legacy caller strategy clarified:** Fix known legacy manifest caller to prefer `crop_path`; for pipeline phases that still carry `thumbnail_path`, either convert at the unified gate by default or skip cleanly when strict; note what users observe.
- **Scope preserved:** Single gate at unified LLaVA entrypoint only; minimal local changes; docs/config/test additions only as needed.

---

## Revised implementation checklist

- **shared/llava_image_paths.py** (new) — Implement `validate_llava_image_path` (containment via `Path.resolve()` and relative containment; reject only by containment under thumbnail folder or exact segment `"thumbs"`; allow by resolved temp_folder, system temp, allowed_extra_dirs; crops-segment rule only as secondary fallback). Implement `convert_thumbnail_to_normalized` (UUID temp filename, atomic write then rename, under temp_folder). Single call site: `unified_alt_generator.generate_alt_outcome`. *Rationale: One module for gate and conversion; path logic in one place.*

- **shared/config_manager.py** — Add `paths.strict_llava_gate: bool` (default `false`) and getter; add `llava.min_normalized_width` (default `512`) and getter; support optional CLI override for strict mode. *Rationale: Config-driven default vs strict; threshold for size/readability.*

- **config.yaml** — Add `paths.strict_llava_gate: false` and `llava.min_normalized_width: 512` with one-line comments. *Rationale: Document default and threshold.*

- **shared/unified_alt_generator.py** — In `generate_alt_outcome`: call validator; if thumbnail and strict → return error outcome (provider not called); if thumbnail and not strict → call conversion, then proceed with normalized path; after gate/conversion get dimensions and size, emit structured log, call provider with normalized path only; return metadata for manifest. *Rationale: Single entry point; default convert, optional strict.*

- **shared/alt_manifest.py** — Add optional fields with defaults: `llava_image_path`, `llava_image_source`, `llava_normalized_path`, `llava_image_width`, `llava_image_height`, `llava_image_size_bytes`. All optional for backwards compatibility. *Rationale: Observability without breaking readers.*

- **shared/manifest_processor.py** — Phase4: prefer `crop_path` (already does); set entry’s llava_* fields from generator metadata. Fix known legacy caller that used `thumbnail_path` for LLaVA to use `crop_path` only (or skip if missing). *Rationale: Legacy uses crop; metadata and coverage populated.*

- **pptx_alt_processor.py** (or shared) — Coverage report: include optional llava_* fields when present. *Rationale: Coverage reflects normalized usage.*

- **docs/artifacts_thumbs_vs_normalized.md** — Define thumbs vs normalized; config keys; default = convert, strict = reject; conversion lifecycle (temp_folder, existing cleanup); permissions on conversion failure. *Rationale: Single reference for operators.*

- **tests/test_llava_image_path_gate.py** — Validator (containment, no substring, exact segment “thumbs”, Windows/mixed paths, symlink); conversion (atomic, UUID, permissions); min_normalized_width; thumbnail vs normalized size/readability. *Rationale: Gate and conversion covered.*

- **tests/test_llava_gate_integration.py** — Mock provider; assert provider called only with normalized path in default mode; assert provider not called for thumbnail in strict mode; assert legacy callers do not silently pass thumbs; manifest fields and structured log. *Rationale: End-to-end and provider-call guarantees.*

- **CLI** — Add `--strict-llava-gate` override where pipeline is invoked. *Rationale: One-off strict runs.*

- **CI** — Smoke: run pipeline with default config and assert every LLaVA generation uses normalized path (e.g. manifest or log check). *Rationale: No thumbs passed to provider in default run.*

---

## Revised gate policy and API

**Runtime policy**

- **Default behavior:** If a thumbnail path reaches the LLaVA entrypoint, convert it to a normalized image under temp/crops (temp_folder) and proceed with that path. Provider is never given the thumbnail path. *Reason: Reduces breakage for legacy flows that still pass thumbnail_path; keeps LLaVA input quality consistent (normalized only) without failing those flows.*
- **Strict mode:** When `paths.strict_llava_gate` is true (or CLI `--strict-llava-gate`), reject thumbnail input: return an error outcome and do not call the provider. No conversion. *Reason: Opt-in strictness for environments that must never use thumbnails.*

**Validator**

- **Name:** `validate_llava_image_path`
- **Args:** `image_path: str | Path`, `config_manager: ConfigManager`, `*, allowed_extra_dirs: Optional[Sequence[Path]] = None`
- **Return:** `tuple[bool, str]` → `(allowed, source_label)` with `source_label` in `("normalized", "thumbnail", "unknown")`.
- **Containment:** Use `Path(image_path).resolve()`; for each candidate dir use the same type and `resolve()`; check containment via relative containment (e.g. `resolved.is_relative_to(Path(d).resolve())`). No substring matching.
- **Rejection:** Path is rejected (thumbnail) if: (1) resolved path is contained under the configured thumbnail folder (resolved), and/or (2) any path segment equals exactly `"thumbs"` (e.g. `"thumbs" in resolved.parts`). Not loose substring (e.g. `thumbs_up` is not rejected).
- **Allowed:** Path is allowed (normalized) if resolved path is contained under: configured temp_folder (resolved), system temp (resolved), or any of `allowed_extra_dirs` (resolved). A rule that allows paths under a directory whose path has a segment `"crops"` may be used as a secondary/fallback only (e.g. when allowed_extra_dirs is not provided); primary allowed set is resolved known dirs.

**Symlink policy**

- **Approach:** Resolve the input path once with `Path.resolve()`. Compare the resolved path to resolved allowed/thumbnail dirs for containment. Do not add special symlink or inode logic.
- **Justification:** Symlinks are followed by `resolve()`, so the resolved path is the real location; a symlink to a file under thumbs is rejected, and a symlink to a file under temp/crops is allowed. Keeps behavior simple and consistent with existing path_validator; avoids platform-dependent inode checks.

**Conversion**

- **Name:** `convert_thumbnail_to_normalized`
- **Args:** `thumbnail_path: str | Path`, `config_manager: ConfigManager`, `*, temp_base: Optional[Path] = None`
- **Return:** `tuple[Optional[Path], Optional[str]]` → `(normalized_path, error_message)`.
- **Behavior:** Unique temp filename (e.g. `llava_norm_<uuid>.png`); write to a temporary file in the same directory, then atomic rename (`os.replace`) to final name; place under `temp_base` or config `temp_folder`. On permission error, return `(None, "…")` and log. Converted files are under temp_folder and are covered by existing temp cleanup (lifecycle note in docs).

**Where called**

- Only from `FlexibleAltGenerator.generate_alt_outcome` in [shared/unified_alt_generator.py](shared/unified_alt_generator.py).

---

## Revised logging and metadata contract

**Structured log payload (one per generation attempt)**

Emit a single structured payload per LLaVA generation with at least:

- `event` (e.g. `"llava_generation"`)
- `image_source` (`"thumbnail"` | `"normalized"`)
- `image_path` (path passed in or attempted)
- `normalized_path` (path actually used; if conversion occurred, this is the converted path)
- `conversion_performed` (boolean or `"true"`/`"false"`; true if thumbnail was converted)
- `width`, `height` (dimensions of image used)
- `size_bytes` (file size of image used)

Example (key=value style):

```
event=llava_generation image_source=normalized image_path=/run/crops/s1.png normalized_path=/run/crops/s1.png conversion_performed=false width=800 height=600 size_bytes=120000
```

With conversion:

```
event=llava_generation image_source=thumbnail image_path=/run/thumbs/s1.jpg normalized_path=/tmp/llava_norm_abc123.png conversion_performed=true width=200 height=200 size_bytes=15000
```

**Manifest / coverage optional fields**

Add to manifest entry and coverage output only as optional fields (defaults so existing readers remain valid):

- `llava_image_path`
- `llava_image_source`
- `llava_normalized_path`
- `llava_image_width`
- `llava_image_height`
- `llava_image_size_bytes`

Example manifest snippet:

```json
{
  "instance_key": "slide_1_shape_2",
  "llava_image_path": "/run/crops/slide_1_shape_2.png",
  "llava_image_source": "normalized",
  "llava_normalized_path": "/run/crops/slide_1_shape_2.png",
  "llava_image_width": 800,
  "llava_image_height": 600,
  "llava_image_size_bytes": 120000
}
```

---

## Revised tests

| Test name | Assertion |
|-----------|-----------|
| `test_validate_llava_image_path_containment_under_thumbnail_rejected` | Resolved path under configured thumbnail folder returns `(False, "thumbnail")`. |
| `test_validate_llava_image_path_exact_segment_thumbs_rejected` | Path with exact segment `"thumbs"` is rejected; path with substring (e.g. `thumbs_safe`) is not rejected. |
| `test_validate_llava_image_path_allowed_under_resolved_dirs` | Path under resolved temp_folder or allowed_extra_dirs returns `(True, "normalized")`; no substring matching. |
| `test_validate_llava_image_path_windows_and_mixed_separators` | Windows-style and mixed-separator paths normalize and validator correctness is unchanged (parametrized or PureWindowsPath). |
| `test_validate_llava_image_path_symlink_resolved` | Symlink targeting a path under thumbs is resolved and rejected; under temp/crops is allowed. |
| `test_convert_thumbnail_to_normalized_atomic_uuid_cleanup_note` | Conversion uses UUID filename and atomic rename; output is under temp_folder; doc note that existing temp cleanup covers it. |
| `test_convert_thumbnail_to_normalized_permission_denied` | On PermissionError, returns `(None, msg)` and does not raise. |
| `test_generate_alt_outcome_default_mode_provider_called_only_with_normalized` | When strict is false and image_path is thumbnail, provider mock is called exactly once with a normalized path (under temp or llava_norm_*), not the thumbnail path. |
| `test_generate_alt_outcome_strict_mode_provider_not_called_for_thumbnail` | When strict is true and image_path is thumbnail, provider mock is not called; outcome is error. |
| `test_legacy_caller_does_not_silently_pass_thumbs` | Legacy path that previously passed thumbnail_path either gets conversion (default) or skip/error (strict); provider never receives thumbnail path. |
| `test_structured_log_has_required_fields` | Log capture contains event, image_source, image_path, normalized_path, conversion_performed, width, height, size_bytes. |
| `test_manifest_entry_llava_fields_optional` | Phase4 populates llava_image_path, llava_image_source, llava_normalized_path, llava_image_width, llava_image_height, llava_image_size_bytes when available; missing keys are acceptable for backwards compatibility. |
| `test_normalized_width_at_least_threshold` | Normalized image used for LLaVA has width >= configurable threshold (e.g. 512); threshold from config `llava.min_normalized_width`. |
| `test_thumbnail_distinctly_smaller_than_normalized` | Thumbnail (by path/artifact type or dimensions) is distinctly smaller than normalized; e.g. thumbnail path under thumbs and normalized under crops/temp, or dimension comparison. |

---

## Backwards compatibility / risk / rollback

- **Backwards compatibility:** New manifest fields are optional with empty/default values; existing readers and JSONL without these keys are unchanged. Default behavior (convert) avoids failing legacy callers that still pass thumbnail_path; strict mode is opt-in.
- **Risk:** Conversion writes under temp_folder; ensure existing temp cleanup runs so disk does not fill. Permission errors during conversion are handled with a clear error outcome and log.
- **Rollback:** Revert gate and conversion in `unified_alt_generator.generate_alt_outcome` to restore previous behavior; set `strict_llava_gate: false` and remove conversion call if using a feature flag. Optional manifest fields remain harmless.
