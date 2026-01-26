# Smart Selector Contract

**Status:** v1.0-rc2
**Applies to:** PPTX Accessibility Pipeline
**Introduced:** v1.3.x planning

**Change Control:** Behavior changes require contract version bump + fixture update.

---

## 1. Purpose & Scope

The **Smart Selector** is responsible for determining **which visual elements should receive ALT text** and **at what semantic level** (atomic image vs grouped composite).

### The Smart Selector:

* Operates **before any LLM / ALT generation**
* Is **deterministic and explainable**
* Produces **selection decisions**, not descriptions
* Acts as the **single source of truth** for inclusion/exclusion logic

### The Smart Selector does **not**:

* Generate ALT text
* Perform image understanding beyond metadata and structure
* Modify PowerPoint files
* Render slides visually
* Call LLMs or vision models

---

## 2. Core Problem Statement

PowerPoint slides—especially in scientific and medical contexts—often contain:

* Grouped visuals (images + shapes + arrows + labels)
* Image-like shapes combined with real images
* Decorative noise mixed with semantic content

Treating every embedded image atomically produces:

* Redundant ALT text
* Loss of semantic meaning
* Poor accessibility outcomes

The Smart Selector exists to **identify meaningful visual units** and **exclude non-informative elements** while preserving interpretability.

---

## 3. Definitions (Normative)

### Visual Element

Any PowerPoint shape that contributes to visual presentation, including but not limited to:

* `PICTURE` — raster or vector images, including screenshots, stock images, and inserted icons
* `AUTO_SHAPE` — geometric shapes, freeforms, arrows, connectors, callouts, and shapes with image fills
* `GROUP` — explicit PowerPoint groupings of multiple shapes
* `CHART` — data-backed charts (bar, line, scatter, pie, etc.)
* `SMARTART` — SmartArt graphics (processes, cycles, hierarchies, org charts)
* `MEDIA` — video or audio objects and their visual placeholders
* `TEXT_BOX` / `WORDART` — text-only shapes when they participate in composite visuals
* `UNKNOWN` — shapes classified but not fully understood

The Smart Selector MUST treat shape type as a **structural signal**, not a semantic guarantee.

### Candidate Visual Element

A Visual Element that survives initial placeholder, hidden-element, and pre-flight filtering and is therefore eligible for selector evaluation. This excludes placeholders, hidden shapes, and elements explicitly filtered by pre-flight rules.

**Placeholder ALT detection:** The selector MUST treat ALT strings matching configured placeholder patterns (for example, values in `config.selector.placeholder_alt_patterns`) or ALT strings shorter than `min_meaningful_alt_chars` as non-meaningful. Such ALT values are treated as if no meaningful ALT exists for the purposes of the `Preserve Existing ALT` precedence rule.

### Atomic Image

A standalone image-rendering Visual Element that represents a complete visual concept on its own.

### Group (Composite Visual)

A PowerPoint `GROUP` shape, `SMARTART`, or other composite construct containing multiple child or internal elements that together form a single semantic unit (e.g., diagram, labeled image, process flow, chart with annotations).

### Image-Rendering Shape

Any Visual Element whose fill or content renders raster or vector imagery (e.g., `PICTURE`, image-filled `AUTO_SHAPE`, converted WMF/EMF shapes).

### Decorative Element

A visual element that does **not** convey meaning necessary for understanding slide content (e.g., borders, dividers, purely stylistic lines).

### Selector Decision

The explicit outcome produced by the Smart Selector for each Candidate Visual Element.

---

## 4. Inputs to the Smart Selector

The Smart Selector **MAY** inspect the following inputs.

### Structural Inputs

* Shape type (`PICTURE`, `GROUP`, `AUTO_SHAPE`, `UNKNOWN`)
* Shape hierarchy (group membership)
* Bounding box (area, aspect ratio)
* Child shapes (for `GROUP` elements)

### Content Signals

* Presence of embedded images
* Existing ALT text
* Text within shapes
* Nearby slide text (titles, labels, captions)

### Contextual Inputs

* Slide index
* Slide title text
* Processing mode (`presentation`, `scientific`, `context`, `auto`)
* Inclusion policy (`preserve`, `overwrite`, `smart`)

### Explicitly Prohibited Inputs (Audit Armor)

The Smart Selector **MUST NOT** use the following as inputs or decision triggers:

* Pixel-level visual features (color, contrast, texture, salience computed from rendered pixels)
* Model-derived confidence scores produced by LLMs or vision models
* Any heuristics derived from prior LLM/vision outputs unless they are explicitly stored and versioned in the manifest
* External telemetry that could leak user data or slide pixels

> ⚠️ The selector **MUST NOT** rely on rendered slide images or pixel-level analysis as a decision input. Rendering is permitted only in downstream, gated AI-assisted phases (Phase 4) when explicitly configured and audited.

---

## 5. Outputs (Required Contract) — v1.0 normative shape

For each Candidate Visual Element, the Smart Selector **MUST** produce a single JSON decision record. This is the minimal, normative shape that pipeline stages and downstream validators must accept.

```json
{
  "selector_version": "string",                // semantic version or commit/tag of selector
  "element_id": "string",                      // stable identifier for this element (required)
  "parent_group_id": "string|null",            // id of parent GROUP when applicable (required if suppressed as child)
  "selector_decision": "include_atomic | include_group | exclude_decorative | exclude_redundant | escalate_manual_review",
  "content_scope": "image | group | slide_context",
  "reason_code": "machine_readable_string",
  "human_reason": "Short explanation for logs and review docs",
  "escalation_strategy": "none | include_with_ambiguous_reason | defer_to_manual_review | render_and_assist | convert_and_reinspect",
  "metadata": { "original_shape_type": "string", "has_overlay": true, "...": "..." }
}
```

Normative rules for the shape above:

* `element_id` is required for every record.
* If `selector_decision == exclude_redundant` or a child is suppressed by a parent group selection then `parent_group_id` MUST be present and reference the `element_id` of the selected parent group.
* `selector_decision` must include the value `escalate_manual_review` to represent deterministic deferral cases.
* `escalation_strategy` must be set for every record. Mappings:
  * `escalate_manual_review` → `escalation_strategy = defer_to_manual_review` (required).
  * Ambiguous-but-safe includes → `selector_decision` remains `include_atomic` or `include_group` and `escalation_strategy = include_with_ambiguous_reason`.
* The `metadata` object is for additive structural signals (e.g., `original_shape_type`, `overlay_ids`, `detected_subtype`) and MUST NOT contain pixel-derived or model-derived scores per the Audit Armor rules.

These outputs are:

* Persisted in the manifest
* Used to gate ALT generation
* Displayed in review documents

---

**Manifest validation requirement:** Every manifest record MUST include `selector_version`. Pipelines MUST validate manifest records against the selector schema corresponding to `selector_version` before proceeding with generation or injection. If a manifest lacks `selector_version` or fails schema validation, the pipeline MUST fail safe (skip injection, generate review doc, and log an error).

## 6. Decision Rule Precedence (Normative)

The following precedence rules are **normative** and MUST be implemented in this order unless an explicit policy override is provided and recorded in the manifest.

1. **Preserve Existing ALT**
   If policy is `preserve` and meaningful ALT exists (non-placeholder) → selector must not override.

2. **Decorative Exclusion**
   Elements explicitly identified as decorative (by rule, name match, or configuration) are excluded regardless of mode.

3. **Group Semantics (if applicable)**
   A meaningful `GROUP` supersedes atomic children (see Group Suppression Rule below).

3a. **Group Suppression Rule**
If a `GROUP` is selected for inclusion, all child elements MUST be marked as `exclude_redundant` with an explicit reference to the parent group's identifier.

3b. **Child ALT vs Group Selection Rule (Normative)**
When a `GROUP` is selected for `include_group`, the selector MUST mark child elements as `exclude_redundant` regardless of child existing ALT, unless the `inclusion_policy` is `preserve` and the child ALT is explicitly marked as `reviewed` or `human_created`. In the `preserve` case, the selector MUST still write both a group decision and a child `preserve_conflict` manifest entry with `human_reason` describing the conflict; surface this in review docs so reviewers can choose the canonical ALT.

4. **Atomic Inclusion**
   Standalone meaningful images are included if not excluded by the prior rules.

5. **Redundancy Handling**
   Repeated or visually duplicated visuals may be excluded or grouped with explicit reason codes.

> ⚠️ Exact numeric thresholds and fuzzy heuristics (e.g., area cutoffs) remain TBD and must be captured in configuration profiles and selector_versioned releases.

---

## 7. GROUP Shape Contract (Critical, Normative)

### Known Intent

`GROUP` shapes are **first-class semantic candidates**, not containers to be flattened.

The Smart Selector **MUST**:

* Treat a `GROUP` as a single visual unit when its children collectively express meaning, unless explicitly excluded by policy.
* Prefer group-level ALT when labels, arrows, and images work together to convey a single concept.
* Avoid generating ALT for individual children if the group is selected; children must be marked `exclude_redundant` with the parent reference.

### Canonical Examples

**Example 1: Labeled Cell Diagram**

* Image of cell + text labels + arrows
* Decision: `include_group`
* Scope: `group`

**Example 2: Process Flow (Cells → Organ → Heart)**

* Multiple shapes + directional arrows
* Decision: `include_group`
* ALT describes the process, not each image

> ⚠️ Formal detection heuristics (e.g., label-arrow co-occurrence rules, relative bounding heuristics) are implementation details and must be recorded in selector_versioned releases.

---

## 8. Mode-Specific Behavior (Constrained)

Modes may influence thresholds and weighting, but MUST NOT change the set of possible decision outcomes.

### `presentation`

* Favor atomic images
* Conservative grouping behavior

### `scientific`

* Favor group-level semantics
* Prefer labeled composites

### `context`

* Consider slide title and surrounding text more heavily in tie-breakers

### `auto`

* Heuristic-based selection that chooses a mode; decisions must still be deterministic and versioned (selector_version)

*Determinism requirement:* `auto` selection MUST be algorithmically deterministic. The exact tie-breaker heuristics and scoring must be recorded in the `selector_version` release notes, and the selector implementation MUST log the sub-scores and rationale used for choosing the mode for each slide/manifest.

---

## 9. Failure & Ambiguity Handling

When the selector cannot confidently decide:

* Default to **inclusion**, not exclusion
* Provide explicit `reason_code` indicating ambiguity
* Use a naming convention for ambiguity: `reason_code` MUST be prefixed with `ambiguous_` (e.g., `ambiguous_structure`, `ambiguous_grouping`)
* Defer semantic resolution to the ALT generation phase only when the manifest record clearly documents the ambiguity and inclusion decision

Silent exclusion is **not permitted**.

---

## Normative Default Ambiguity Policy (resolves Sections 9 & 13)

When the selector cannot deterministically resolve semantic inclusion at the configured policy thresholds, the selector MUST follow the policy below (normative):

1. **Default behavior** — Ambiguity defaults to *inclusion with a flag*:
   * `selector_decision` = `include_atomic` | `include_group` (as appropriate)
   * `reason_code` MUST be prefixed with `ambiguous_` (examples: `ambiguous_structure`, `ambiguous_grouping`)
   * `escalation_strategy` = `include_with_ambiguous_reason` (so the item surfaces early in review docs)

2. **Hard-stop (defer) triggers** — Use `escalate_manual_review` **only** when a concrete trigger is matched. For v1.0 define this minimal set of triggers:
   * Element strongly resembles transient system UI or pasted error/modal (contract field example: `annotation_hint == error_dialog` or `annotation_hint == unknown` combined with configured overlap thresholds).
   * Selector cannot produce a stable `element_id` or the manifest validation fails for that element (structural integrity issue).
   * Overlays that explicitly match configured `hard_stop_overlay_types` (for example: `error_dialog`, `system_modal`).
   When any hard-stop trigger matches:
   * `selector_decision` = `escalate_manual_review`
   * `escalation_strategy` = `defer_to_manual_review`
   * `reason_code` should be specific (e.g., `escalate_system_ui_like`, `escalate_invalid_element_id`)

3. **Preserve vs conflict** — If `inclusion_policy == preserve` and a child element has an existing non-placeholder ALT with deterministic provenance (see Appendix B if defined), the selector must write both:
   * A group-level decision (`include_group`) and
   * A child `preserve_conflict` manifest entry that references `parent_group_id` and explains the conflict in `human_reason`.
   This makes the conflict explicit in review docs rather than silently overriding human ALT.

4. **Operational rule** — Any record with `escalation_strategy == defer_to_manual_review` MUST be surfaced as a high-priority review item in generated review docs; it SHOULD block automated ALT injection for that element until resolved.

---

## 10. Non-Goals (Explicit)

The Smart Selector will **NOT**:

* Call LLaVA or any LLM
* Generate or edit ALT text
* Perform visual rendering
* Attempt medical interpretation
* Make irreversible decisions without explanation
* Perform slide-level semantic synthesis

---

## 11. Acceptance Criteria (Testable)

The Smart Selector is considered correct when all of the following hold:

* The same input (Candidate Visual Elements + config + selector_version) yields the same output (deterministic behavior)
* Every exclusion has a logged `reason_code` and `human_reason`
* `GROUP` decisions are explicit and reviewable in generated review documents
* No ALT generation occurs without a selector decision present in the manifest
* Selector decisions can be regenerated from manifest artifacts without reprocessing the PPTX (enables resume/review workflows)

---

## 12. Open Questions (Intentional Gaps)

The following items are deliberately undefined in this contract and must be resolved in selector_versioned implementation artifacts or in configuration profiles:

* Exact decorative heuristics
* Area thresholds (if any)
* Redundancy detection strategy
* Group confidence scoring (how to compute and persist)
* Text-to-visual weighting and tie-breakers
* Auto-mode fallback rules

These must be recorded as part of the `selector_version` release notes and unit-tested against representative slide fixtures.

---

## Appendix A — Decision Matrix (Suggested, Implementation Appendix)

(Recommended as an implementation aid; not normative unless committed to a selector_version.)

A concise table mapping common cases to default decisions—for example:

| Shape Type                          | Grouped? | Mode         | Default Decision   | Example Reason Code             |
| ----------------------------------- | -------: | ------------ | ------------------ | ------------------------------- |
| `PICTURE`                           |       No | presentation | include_atomic     | `include_atomic_picture`        |
| `AUTO_SHAPE` (image-rendering fill) |       No | scientific   | include_atomic     | `include_atomic_image_fill`     |
| `GROUP` (image + labels + arrows)   |      Yes | scientific   | include_group      | `include_group_labeled_diagram` |
| Small decorative line               |       No | any          | exclude_decorative | `exclude_decorative_small`      |

---

**End of Contract (v1.0-rc)**

## 13. Handling UNKNOWNs, Extensibility, and Edge Cases

Faculty slide content is unpredictable. The selector must be designed to *gracefully identify, record, and escalate* truly unknown or edge-case visuals rather than silently failing or making unstable guesses. The following patterns should be implemented in the selector design and are required to be documented in the selector_version release notes.

### 13.1 Detection & Enhanced Classification

For each Candidate Visual Element, the selector implementation MUST attempt layered detection and record discovered signals in the manifest, for example:

* `original_shape_type` — raw type reported by the parser (e.g., `PICTURE`, `AUTO_SHAPE`, `GROUP`, `CHART`, `SMARTART`, `MEDIA`, `TEXT_BOX`, `OLE_OBJECT`, `MODEL_3D`, `UNKNOWN`)
* `detected_subtype` — more specific subtype if available (e.g., `wmf_emf`, `svg_icon`, `image_fill`, `chart_pie`, `smartart_process`)
* `file_extension` — when the element references an embedded file (png, emf, svg, wmf, etc.)
* `has_image_fill` — boolean indicating image fill on non-picture shapes
* `has_chart` — boolean
* `has_smartart` — boolean
* `is_vector` — boolean hint (vector vs raster) when detectable
* `is_3d_model` — boolean
* `is_ole_object` — boolean
* `raw_ooxml_type` — raw XML node name if available (useful for forensic debugging)

These fields are additive metadata and MUST be written to the manifest so downstream stages (generation, review, injection) can make deterministic, versioned choices.

### 13.2 Overlay & Annotation Handling (Normative)

Groups and composite visuals may contain **annotative overlays** that materially change meaning, such as arrows, callouts, highlights, or error indicators layered on top of charts, images, or diagrams.

The Smart Selector MUST apply the following rules:

* If an annotative overlay (arrow, callout, highlighted stroke, short emphatic text) overlaps or points to another visual element, the selector MUST treat the composite as a single semantic unit and assign `include_group`.
* Annotative overlays MUST supersede decorative exclusion rules when they materially alter meaning.
* If an overlay points to or highlights a `CHART` or data-backed visual, the selector MUST prefer group-level inclusion and surface the annotation explicitly in the `human_reason`.
* If an overlay strongly resembles transient system UI (e.g., pasted error dialogs, application warnings, modal boxes), the selector MUST escalate to `defer_to_manual_review`.

For all overlay cases, the selector MUST record:

* `has_overlay` — boolean
* `overlay_ids` — list of overlay element identifiers
* `overlay_relation` — object describing relationship (e.g., `{overlay_id, target_id, overlap_area_pct, zindex_delta}`)
* `annotation_hint` — enum (`arrow`, `callout`, `circle`, `text_box`, `error_dialog`, `highlight`, `unknown`)
* `priority` — (`high`, `medium`, `low`) for review ordering

### 13.3 Fallback Strategies (Escalation)

When an element is `UNKNOWN` or matches configured edge-case rules, the selector MUST choose one of the following controlled escalations and persist the choice as `escalation_strategy` in the manifest:

* `include_with_ambiguous_reason` — include this element for ALT generation but mark as `ambiguous_*` so it surfaces high in review docs
* `defer_to_manual_review` — exclude from automated generation and mark prominently in review docs for human authoring
* `render_and_assist` — render slide (or crop) and run LLaVA / vision assist in a gated manner (costly, must be configured and audited)
* `convert_and_reinspect` — run a converter (e.g., WMF/EMF -> PNG via configured tool like Inkscape) and re-run detection

Policy: default escalation is `include_with_ambiguous_reason` unless configuration or selector rules say otherwise.

### 13.4 Incremental Handler Registration

The codebase should expose a small registry of handler functions keyed by `detected_subtype` or `original_shape_type` so new converters/handlers can be added without touching core selector logic. Handlers should be pure and return deterministic manifest updates.

### 13.5 Prioritization & Review UX

Unknown, ambiguous, and overlay-driven items should be surfaced earlier in generated review docs. The review DOCX should include a priority flag based on `priority`:

* High — `defer_to_manual_review`, chart annotations, error overlays
* Medium — `include_with_ambiguous_reason`, unclear annotations
* Low — standard includes

### 13.6 Observability & Iteration

Track metrics for unknowns and escalation outcomes in your logging and cost-tracking telemetry:

* `unknown_rate` per batch
* `overlay_rate`
* `escalation_distribution`
* `human_override_rate` for ambiguous and overlay items

These metrics feed an iteration plan: add handlers for the most frequent unknowns and overlays first.

---

## Appendix B — Suggested Manifest Fields (Implementation Appendix)

Include these fields for each manifest entry (in addition to the fields in Section 5):

* `element_id` — stable identifier for shape (unique per slide/run)
* `original_shape_type` — (see 13.1)
* `detected_subtype` — (see 13.1)
* `file_extension` — if available
* `has_image_fill` — boolean
* `has_text` — boolean
* `text_content_sample` — short snippet of nearby text (configurable length), for context
* `escalation_strategy` — as described in 13.2
* `parent_group_id` — id if child of selected group
* `raw_ooxml_type` — (if available)
* `analysis_timestamp` — ISO timestamp of selector decision

These fields are intended to be machine-readable and human-friendly for debugging and audit.

---

**End of Contract (v1.0-rc, extended)**