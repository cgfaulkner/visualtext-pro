# Implementation Plan: Smart Selector Contract Alignment

**Canonical plan.** This document is the single implementation plan for Smart Selector contract alignment. All revisions are made **in place** here. The plan was originally produced in planning mode and is maintained in the repo for version control and in-place edits. No separate planning document is created for this scope.

**Contract-first, deterministic, non-destructive, structural-only. No code in this doc—planning only.**

---

## 1. Current State Assessment

### 1.1 Selector-Related Code and Pipeline Hooks

| Location | Role |
|----------|------|
| [shared/selector/selector.py](../shared/selector/selector.py) | Main entry: `run_selector(pptx_path, config, output_path)`. Extracts candidates from PPTX via python-pptx; emits stub manifest (all `include_atomic`, `reason_code: "stub_v1"`). |
| [shared/selector/types.py](../shared/selector/types.py) | `SelectorDecision`, `ContentScope`, `EscalationStrategy`, `SelectorManifestRecord`, `SelectorManifest`. |
| [schemas/selector_manifest.schema.json](../schemas/selector_manifest.schema.json) | JSON Schema for manifest array; requires `parent_group_id` when `selector_decision == "exclude_redundant"`. |
| [shared/pipeline_phases.py](../shared/pipeline_phases.py) | **Phase 1.9** `phase1_9_run_selector`: runs selector, validates manifest against schema, counts `defer_to_manual_review`. Called after Phase 1.5, before Phase 2. |
| [shared/pipeline_artifacts.py](../shared/pipeline_artifacts.py) | `RunArtifacts.selector_manifest_path`; no `load_selector_manifest()` helper. |
| [tools/validate_selector_manifest.py](../tools/validate_selector_manifest.py) | CLI: validate manifest JSON against schema; used by CI. |
| [.github/workflows/validate-selector-schema.yml](../.github/workflows/validate-selector-schema.yml) | Validates golden manifests under `fixtures/selector/*/selector_manifest.json.golden`. |
| [config.yaml](../config.yaml) | `selector.*`: placeholder_alt_patterns, min_meaningful_alt_chars, schema_path, overlay/escalation/auto-mode. No explicit `inclusion_policy`. |

### 1.2 Implemented vs Stubbed / Contract-Incomplete

- **Implemented:** Phase 1.9 orchestration; schema validation after run; stub that emits one record per candidate with required top-level fields; types and schema include `preserve_conflict` and all contract enums.
- **Stubbed / partial:** All decisions are `include_atomic` with `reason_code: "stub_v1"`; no group semantics, no decorative/redundant/exclude, no escalation, no placeholder-ALT or preserve logic, no overlay/annotation metadata, no mode-specific behavior.
- **Contract-incomplete:** See gap analysis below.

### 1.3 Manifest Shape Currently Produced

- One record per candidate: `selector_version`, `element_id`, `parent_group_id: null`, `selector_decision: "include_atomic"`, `content_scope: "image"`, `reason_code: "stub_v1"`, `human_reason`, `escalation_strategy: "none"`, `metadata: { original_shape_type }`.
- **element_id** today is `slide_{slide_idx}_shape_{shape_idx}` with **enumerate index**. Phase 1 uses **shape_id** (XML) in `create_instance_key(slide_idx, shape_id)` → `slide_{slide_idx}_shape_{shape_id}`. These can differ; alignment requires selector to use the same identity scheme as Phase 1.

### 1.4 Alignment with Contract

- **Not aligned:** Stub decisions, wrong key scheme, no precedence, no gating of ALT generation, and schema/contract nuances (preserve_conflict, parent_group_id for preserve_conflict). Downstream Phase 2 does not use the selector manifest.

---

## 2. Selector Input: Phase 1 Artifacts as Primary Source of Truth

### 2.1 Requirement (Normative for This Implementation)

The selector **MUST** use the **existing Phase 1 manifest and visual index** as the **primary source of truth** for candidate identity and element IDs for this implementation. It **MUST NOT** re-walk the PPTX independently as the default path, because:

- Phase 1 already defines the canonical candidate set and `instance_key` (element identity) via `create_instance_key(slide_idx, shape_id)`.
- Selector output must be keyed by the same IDs that Phase 2 and the rest of the pipeline use; otherwise Phase 2 cannot reliably gate on selector decisions.
- A single parse/source of truth avoids drift between “what Phase 1 classified” and “what the selector decided,” and keeps element_id stable across runs and resume.

**Implementation:** Selector entry point accepts `(artifacts, config)` or equivalent (manifest path + visual_index/current_alt). It loads Phase 1 manifest (or visual_index + current_alt_by_key) and builds the candidate list from those entries. For each candidate, **element_id = entry.instance_key** (no second key scheme).

### 2.2 Fallback Path (If Any)

If a fallback path exists (e.g. running selector without a prior Phase 1 run in a special mode), it **MUST** derive element IDs **exactly** as Phase 1:

- Use **shape_id** from the shape (e.g. `getattr(shape, 'shape_id', ...)`), not the enumerate index over `slide.shapes`.
- Build **element_id** with the same formula as `create_instance_key(slide_idx, shape_id)` (i.e. `slide_{slide_idx}_shape_{shape_id}`), as defined in [shared/alt_manifest.py](../shared/alt_manifest.py).

No separate ID scheme is permitted; otherwise Phase 2 lookup and fixture stability break.

---

## 3. Distinction: Selector Decisions vs Preserve-Existing-ALT vs Downstream Behavior

The plan must not conflate “included in semantic scope” with “safe to generate or apply replacement ALT.” **“Included”** means semantically eligible/in-scope only; it does **not** by itself imply replacement of existing ALT or guaranteed generation or application of ALT. The following separation is **normative** for implementation.

### 3.1 Selector Inclusion/Exclusion Decisions

- **Selector** only decides **semantic scope**: which elements are **in scope** for ALT at all, and at what level (atomic vs group).
- **Included:** `include_atomic` or `include_group` → element (or group) is **semantically eligible** for ALT—i.e. in scope. The selector is not asserting that ALT will be generated or applied; it is asserting that this unit is a valid target for ALT. Replacement, generation, and application are downstream concerns.
- **Excluded:** `exclude_decorative`, `exclude_redundant`, or `escalate_manual_review` → element is either out of scope or deferred to manual review; no automated ALT generation for that element.
- **Preserve-conflict** is a special **child** record type: it documents a conflict when a group is selected but a child has existing meaningful ALT in preserve mode; it does **not** mean “include this child for generation.” The child remains semantically redundant with the group; the record exists for review and audit.

So: **included** = semantically eligible/in-scope only (no implication of replacement or guaranteed generation/application). **Excluded** = not in scope or deferred. **Preserve_conflict** = documentation of a conflict for review, not an inclusion for generation.

### 3.2 Preserve-Existing-ALT Behavior (Selector Level)

- **Preserve-existing-ALT** is a **selector precedence rule**: when `inclusion_policy == preserve` and the element has **meaningful** (non-placeholder) ALT, the selector “must not override”—i.e. the selector records that this element is preserved (e.g. include with a preserve reason_code), and does not treat it as a blank slate for replacement.
- This is **not** the same as “do not generate.” Downstream may still generate for audit/review; the **injection** layer (Phase 3 / injector) is responsible for not overwriting human ALT when config says preserve. The selector’s job is to record the decision and reason so that downstream can behave correctly (e.g. “include but preserve” vs “include and allow overwrite”).

So: **preserve-existing-ALT** in the selector = record the preserve policy outcome and reason; do not conflate with “safe to overwrite” in injection.

### 3.3 Downstream Generation (Phase 2)

- **Phase 2** should generate ALT **only** for elements that are **included** by the selector (`include_atomic` or `include_group`) and **not** deferred (`escalation_strategy != defer_to_manual_review`).
- Excluded elements (`exclude_decorative`, `exclude_redundant`, `escalate_manual_review`) get **no** generated ALT from Phase 2.
- Whether an included element already has meaningful ALT is a separate concern: generation may be skipped for that key by “has_current_alt” logic, but the **gate** for “may we generate at all?” is the selector. So: **included** = eligible for generation (subject to other rules); **excluded** = not eligible.

### 3.4 Downstream Injection (Phase 3 / Injector)

- **Injection** decides whether to **apply** generated ALT or keep existing (e.g. preserve policy, meaningfulness). That is **downstream** behavior, not selector output. The selector does not output “safe to overwrite”; it outputs “in scope” and “preserve reason” where applicable. Injection uses config (e.g. `alt_text_handling.mode`) and existing ALT to decide overwrite vs preserve.

**Summary:** Selector = semantic scope and preserve-policy recording (included = eligible/in-scope only; no implication of replacement or guaranteed generation/application). Phase 2 = generate only for included, non-deferred. Phase 3 / injector = apply or preserve based on config and existing ALT. Keep selector scope, preserve behavior, Phase 2 generation, and Phase 3 injection explicitly separate; do not equate “included” with “safe to replace.”

---

## 4. Contract Gap Analysis

### 4.1 Required Per-Element Fields, parent_group_id, preserve_conflict

- Contract Section 5: all fields required; when `exclude_redundant` or child suppressed, `parent_group_id` MUST be present (schema already has if/then for exclude_redundant). For **preserve_conflict**, contract Sections 6 (3b) and 9 require a child manifest entry that “references parent_group_id”; schema and types already include `preserve_conflict`; add schema if/then: when `selector_decision == "preserve_conflict"`, require non-null `parent_group_id`.

### 4.2 Contract Internal Inconsistency: preserve_conflict

- **Section 5** (Outputs) lists only five values: `include_atomic | include_group | exclude_decorative | exclude_redundant | escalate_manual_review`. It does **not** list `preserve_conflict`.
- **Sections 6 (3b) and 9** require the selector to write a **child `preserve_conflict` manifest entry** with `parent_group_id` and `human_reason`.
- **Repo today:** [shared/selector/types.py](../shared/selector/types.py) and [schemas/selector_manifest.schema.json](../schemas/selector_manifest.schema.json) already treat `preserve_conflict` as a valid sixth value. The contract is internally inconsistent.

**Resolution (prefer updating existing contract/docs in place):**

- **Update [docs/smart-selector-contract.md](../docs/smart-selector-contract.md) in place:** In Section 5, extend the normative `selector_decision` enum to include `preserve_conflict` and add one sentence: “`preserve_conflict` is used only for a child element when the group is selected for inclusion and the child has existing meaningful ALT under preserve policy; it documents the conflict for review (see Sections 6 and 9).”
- Do **not** let schema and code carry a value that the contract omits; bring the contract in line with the already-canonical schema and types so that contract, schema, and code are consistent.

### 4.3 Other Gaps

- reason_code, human_reason, escalation_strategy, content_scope: stub uses fixed values; implementation must set them per contract (ambiguity → ambiguous_*, escalation; hard-stop → defer; overlay/unknown per Section 13).
- Group suppression: when GROUP is include_group, children get exclude_redundant + parent_group_id; preserve + child with meaningful ALT → also emit child preserve_conflict entry.
- Placeholder ALT: use config.selector.placeholder_alt_patterns and min_meaningful_alt_chars; treat as non-meaningful for preserve rule.
- Overlay/unknown: structural-only metadata; record has_overlay, overlay_ids, annotation_hint where applicable; no pixels.

---

## 5. Recommended Manifest Design

- **Normative:** Single array of records per Candidate Visual Element (plus one extra record per preserve-conflict child when applicable). Required fields per Section 5; element_id = instance_key from Phase 1. metadata: original_shape_type and overlay/unknown fields as in contract; no pixel- or model-derived data.
- **One primary inclusion path per semantic unit:** A given semantic unit must have only one primary inclusion path: either **include_group** for the parent grouping (with children exclude_redundant) or **include_atomic** for standalone content. The selector must not produce duplicate primary inclusion for the same semantic content (e.g. both include_group for a group and include_atomic for its children as primary targets).
- **Slide-level groupings:** Omit in v1; add later only if review UX requires (non-normative, additive).
- **Schema:** Add if/then for preserve_conflict requiring parent_group_id (non-null).

---

## 6. Decision Model (Deterministic, Structural Only)

- Pre-flight: candidates from Phase 1 manifest; element_id = instance_key.
- Precedence order: (1) Preserve-existing-ALT (policy + meaningful ALT → record preserve, do not override), (2) Decorative exclusion, (3) Group semantics and suppression (include_group → children exclude_redundant; preserve + child ALT → also preserve_conflict child record), (4) Atomic inclusion, (5) Redundancy. One primary inclusion per semantic unit (Section 5). Ambiguity default: include with ambiguous_* and include_with_ambiguous_reason. Overlay/unknown: structural metadata only; mode influences thresholds/weighting only.

**Concrete criteria (concise, structural-only):**

- **Decorative exclusion:** Apply when element matches configured decorative rules: e.g. shape type + name/role pattern (e.g. “divider”, “line” with no text), or structural signal (very small area below configured threshold, line-like aspect ratio). Excluded regardless of mode; reason_code and human_reason required.
- **Redundant exclusion:** Apply when element is a child of a group selected as include_group (suppress child; parent_group_id required), or when element is a structural duplicate of another already included (e.g. same content_key or explicit redundancy rule). parent_group_id or reference to canonical element as required by contract.
- **Hard-stop manual review / defer:** Use **only** when a defined trigger matches: (1) overlay type in configured hard_stop_overlay_types (e.g. error_dialog, system_modal), (2) selector cannot produce a stable element_id or manifest validation would fail for that element, (3) element strongly resembles transient system UI per contract. Set selector_decision = escalate_manual_review and escalation_strategy = defer_to_manual_review; do not use for mere ambiguity (ambiguity → include with ambiguous_*).

### 6.1 Shape-built diagram (synthetic) virtual groups

For shape-built diagrams, the selector will only create a single semantic virtual_group when there is structural evidence of semantic linkage. Structural evidence is defined as **(a)** connector relationships (arrows/connectors, i.e. LINE or CONNECTOR shape type) linking members, or **(b)** a shared, meaningful nearby label that appears to apply to the set (proximity ≤40px and alignment ≥60% of cluster members). Mere adjacency or styling alone is insufficient. Anchor selection is deterministic: smallest element_id lexicographically. Confidence is a weighted sum (connectors = high weight, nearby labels = medium, adjacency = low); if confidence &lt; 0.6 the anchor record gets escalation_strategy = render_and_assist. See config selector.synthetic_diagram (proximity_px, required_alignment_fraction, confidence_threshold).

---

## 7. Pipeline Integration

- **Inputs:** Phase 1 manifest (and visual_index/current_alt_by_key). Config: selector.*, inclusion_policy (e.g. from alt_text_handling.mode or selector.inclusion_policy).
- **Output:** artifacts.selector_manifest_path; validate against schema after write; pipeline fails if validation fails.
- **Phase 2 gating:** Only generate for element_ids that have a selector record with selector_decision in (include_atomic, include_group) and escalation_strategy != defer_to_manual_review. Excluded and deferred get no generation.
- **RunArtifacts:** Add load_selector_manifest() for Phase 2 and review builder.
- **Review-doc surfacing:** For this implementation scope, the selector **only** needs to **emit the data cleanly** (reason_code, human_reason, escalation_strategy, priority, has_overlay, preserve_conflict records) so that **downstream review tooling** can surface ambiguous, deferred, overlay, and preserve_conflict items. Building or changing the actual review DOCX is **out of scope** for the selector contract-alignment work; the selector’s obligation is that the manifest is complete and structured for downstream consumption.

---

## 8. Phase 2 Gating: Migration and Safe Behavior

### 8.1 Requirement: No Silent Behavior

- **Do not silently generate** when selector output is missing: if Phase 2 is expected to gate on the selector, then missing or invalid selector manifest must not be treated as “generate for everyone.”
- **Do not silently skip** in a way that hides errors: e.g. if the manifest exists but a key has no record, that should be detectable (log + deterministic behavior), not silently skipped as if the element were excluded.

### 8.2 Proposed Behavior (Deterministic, Explicit)

- **Selector manifest required (target state):** After Phase 1.9, selector manifest is always written and validated. Phase 2 **requires** the selector manifest to exist and to pass schema validation (already enforced in Phase 1.9). Phase 2 loads the manifest and:
  - For each key in visual_index, if there is **no** selector record for that element_id: **fail** Phase 2 with a clear error (e.g. “Selector manifest has no record for element_id …; cannot gate generation.”). This avoids silent generation and avoids silent skip-without-explanation.
  - For each key that has a record: if selector_decision is exclude_* or escalate_manual_review, or escalation_strategy is defer_to_manual_review, do **not** add that key to keys_needing_generation. Only include keys that are included and not deferred.

- **Migration / backward compatibility:** **Option A is the default implementation path** for this plan. Implement Option A unless there is a **clearly documented repo requirement** for temporary legacy compatibility.
  - **Option A (adopted as default):** No temporary compatibility path. Phase 2 gating is added in the same release as the contract-aligned selector. Phase 1.9 always runs and always produces a manifest; Phase 2 always requires the manifest and fails if it is missing or if any visual_index key has no selector record. Old runs (no selector manifest) are considered invalid for the pipeline; re-run from Phase 1. This is the **recommended implementation target**.
  - **Option B (fallback only, not recommended):** A config flag (e.g. `selector.required_for_generation: true` default) may be introduced **only** if a documented repo requirement exists (e.g. resuming very old runs without re-running Phase 1.9). When `false`, Phase 2 would log a loud warning and proceed as today. Option B is **not** the recommended implementation target; use it only when explicitly required and document the requirement and deprecation timeline in this plan and in config.

### 8.3 Legacy/Stub Selector Output

- **Legacy/stub output:** Current stub emits one record per candidate with include_atomic and stub reason_code. That output is **valid** for schema and for gating: every element is “included,” so Phase 2 would generate for all (as today). Once the selector is contract-aligned, records will include exclude_* and escalate_manual_review where appropriate, and Phase 2 will restrict generation accordingly. No special handling for “stub” reason_code is required; treat stub output as valid legacy until replaced.

### 8.4 Fixtures and Tests

- **Older fixtures/tests:** Any fixture or test that assumes “no selector manifest” or “selector not run” must be updated: run Phase 1.9 and provide a valid manifest in the test (Option A). Golden selector manifests (e.g. fixtures/selector/*/selector_manifest.json.golden) should be updated to the contract-aligned shape and validated by CI. Under Option A there is no “legacy path” test that skips the selector.

---

## 9. Migration / Backward-Compatibility Summary

| Scenario | Handling |
|---------|----------|
| **Legacy/stub selector output** | Valid schema; treat as “all included”; no special code path; replace with contract-aligned output when selector is implemented. |
| **Older fixtures/tests** | Update to supply selector manifest and exercise new path (Option A). Golden JSONs updated to contract shape. Legacy tests that relied on stub/missing selector updated or removed. |
| **Selector manifest missing in Phase 2** | Do not silently generate. **Option A (default):** Fail Phase 2 with clear error. Option B only if documented repo requirement exists: then config flag, loud warning when disabled, deprecation timeline. |
| **Temporary compatibility path** | **Not** the recommended target. Only if Option B is explicitly required: config flag, deprecation timeline, and explicit documentation; remove on timeline. |

---

## 10. Implementation Breakdown (File-by-File)

- **shared/selector/selector.py:** Consume Phase 1 manifest/visual_index; element_id = instance_key; implement decision precedence and metadata; write manifest to output_path; deterministic sort.
- **shared/selector/types.py:** Keep preserve_conflict; no confidence in normative record.
- **schemas/selector_manifest.schema.json:** Add if/then for preserve_conflict requiring parent_group_id.
- **shared/pipeline_phases.py:** Phase 1.9 passes artifacts (and config) to run_selector so selector can read manifest. Phase 2: load selector manifest; build “generate allowed” set from records; fail on missing manifest or missing record per Section 8; only add keys that are included and not deferred.
- **shared/pipeline_artifacts.py:** Add load_selector_manifest().
- **config.yaml:** Add selector.inclusion_policy or document use of alt_text_handling.mode; add selector.hard_stop_overlay_types if needed. Add selector.required_for_generation only if Option B is adopted (not recommended).
- **tools/validate_selector_manifest.py:** No change if schema is updated; ensure if/then for preserve_conflict is validated.
- **tests:** New tests for selector (determinism, preserve, group suppression, preserve_conflict, ambiguity, defer, overlay, unknown, schema). Phase 2 tests: manifest required, missing record fails (Option A); no tests rely on stub or missing selector.
- **fixtures/selector:** Add/update golden manifests to contract-aligned shape.
- **docs/smart-selector-contract.md:** Update Section 5 in place to add preserve_conflict to the normative enum and one-sentence description (Section 4.2). No new doc unless necessary.

---

## 11. Documentation: Prefer Updating Existing Docs In Place

- **Prefer updating existing documentation** rather than creating new docs. In particular:
  - **[docs/smart-selector-contract.md](../docs/smart-selector-contract.md):** Fix Section 5 enum to include `preserve_conflict` (see Section 4.2). Any other clarifications (e.g. distinction between selector scope vs injection) can be added as a short subsection or note in the same file.
  - **README.md / AGENTS.md:** Add or adjust the “Smart Selector” / “Phase 1.9” description in place (selector consumes Phase 1 manifest, emits selector_manifest.json, Phase 2 gates on it; no pixels/LLM). Do not create a separate “Smart Selector Guide” unless a clear need arises.
  - **Config comments:** Document selector.* and any new keys (inclusion_policy; required_for_generation only if Option B is used) in config.yaml in place.

Do not introduce new top-level docs (e.g. “selector_architecture.md”) unless the existing contract and pipeline docs are insufficient and the team agrees.

---

## 12. Testing Plan

- Deterministic output for fixed input. Preserve-existing-ALT and placeholder handling. Group suppression (children exclude_redundant, parent_group_id). Preserve_conflict record when preserve + child has ALT. Ambiguous include (ambiguous_*, include_with_ambiguous_reason). Hard-stop defer. Overlay/unknown metadata. Schema validation (including preserve_conflict parent_group_id). Pipeline: Phase 1 → 1.9 → 2 with manifest; Phase 2 fails when manifest missing or record missing (or assert warning when compatibility flag off).

---

## 13. Definition of Done

Implementation is **not** considered complete until **all** of the following are true:

1. **Contract and docs:** Section 5 of [docs/smart-selector-contract.md](../docs/smart-selector-contract.md) includes `preserve_conflict` in the normative selector_decision enum and is updated in place; schema and code match the contract.
2. **Selector input:** Selector uses Phase 1 manifest (and/or visual_index/current_alt) as the **primary** source of candidates and element_id; any fallback derives element_id exactly via create_instance_key(slide_idx, shape_id).
3. **Selector output:** Manifest conforms to contract: per-element records with correct selector_decision, content_scope, reason_code, human_reason, escalation_strategy, metadata; parent_group_id when exclude_redundant or preserve_conflict; no pixel- or model-derived data.
4. **Decision rules:** Precedence (preserve, decorative, group with suppression and preserve_conflict, atomic, redundancy), ambiguity default, hard-stop defer, overlay/unknown handling are implemented and deterministic.
5. **Phase 2 gating:** Phase 2 loads selector manifest; generates only for elements that are included and not deferred; **fails** when manifest is missing or when a visual_index key has no selector record (Option A; no silent generation or silent skip). If Option B is used, it is documented and not the default.
6. **RunArtifacts:** load_selector_manifest() exists and is used by Phase 2 (and review builder as needed).
7. **Tests and fixtures:** Selector unit tests and pipeline tests cover the above; golden selector manifests exist and validate; CI passes.
8. **Legacy tests/fixtures:** Any legacy tests or fixtures that relied on stub selector behavior (e.g. no manifest, or “all include_atomic” without Phase 1.9) have been **updated or explicitly removed** so that the new path (Phase 1.9 → manifest required → gating) is actually exercised; no test suite passes by virtue of skipping or stubbing the selector.
9. **Documentation:** Contract and pipeline docs updated in place; config and README/AGENTS reflect selector behavior and Phase 2 gating.

---

## 14. Open Decisions (Approval Before Implementation)

1. **Option A vs B:** **Option A is adopted** as the default implementation path: Phase 2 fails when selector manifest is missing or when a visual_index key has no selector record. **Option B** (config-driven compatibility) is **not** the recommended implementation target; implement it only if there is a clearly documented repo requirement for temporary legacy compatibility, and document that requirement and deprecation in this plan.
2. **Slide-level helper groupings:** Omit in v1 (recommended).
3. **Confidence in metadata:** Omit in v1 (contract forbids model-derived; no rule-derived score unless product need).
4. **Selector version:** Use semantic version (e.g. 1.0.0) for first contract-aligned release; record in config and manifest.
