# VisualText Pro: System Overview

A single-page, plain-English explanation of how the pipeline works. For setup and commands, see the [root README](../README.md). For technical detail, see the [docs index](README.md).

---

## What It Does

VisualText Pro takes PowerPoint presentations, finds the images and visual elements that need alternative text for accessibility, generates descriptions using a local AI vision model (LLaVA), and writes those descriptions back into the slides. It also adds a standard "Disclosures" slide when needed to indicate that AI was used.

---

## The Pipeline (High Level)

1. **Load the presentation** — Open the PPTX and scan all slides for visual content.

2. **Extract visual elements** — Identify images, shapes with image fills, charts, grouped graphics, and shapes that should be rendered to images. Filter out placeholders, decorative elements, and hidden content.

3. **Smart selector** — Decide which elements get ALT text and at what level (single image vs. grouped composite). This step is deterministic and runs before any AI call. See [smart-selector-contract.md](smart-selector-contract.md).

4. **Generate derivative images** — The system produces two kinds of image outputs:
   - **Thumbnails** — Small previews used only in review documents (Word DOCX) for human oversight.
   - **Normalized images** — Full-size or upscaled images used only as input to the LLaVA model. Thumbnails are never sent to LLaVA; if a thumbnail path reaches the model, it is converted to a normalized image first. See [artifacts_thumbs_vs_normalized.md](artifacts_thumbs_vs_normalized.md).

5. **Generate ALT text** — Send normalized images to LLaVA (via Ollama) and get descriptive text. Apply policies (preserve existing, replace weak text, or overwrite all).

6. **Inject ALT text** — Write the descriptions into the PowerPoint XML. Before saving, ensure a "Disclosures" slide exists at position 2 (second slide) when not already present.

7. **Save** — Write the modified PPTX to disk.

---

## Batch Workflow

When you process a folder (or glob), the system uses a **staged batch workflow**:

- A **run folder** is created under the input directory: `<input_root>/staged_runs/<run_id>/`
- The run folder contains:
  - `manifest.json` — Tracks which files are done, pending, or failed; supports resume.
  - `outputs/<relative_path>/` — Per-file artifacts (coverage reports, etc.).
- Resume with `--run-id <id>` or `--resume-manifest <path>`.
- Use `--force` to reprocess everything without using the manifest.

See [batch_completion_criteria.md](batch_completion_criteria.md) and [batch_manifest_skip_explained.md](batch_manifest_skip_explained.md) for details.

---

## Key Behaviors

| Behavior | Summary |
|----------|----------|
| **Disclosure slide** | Processed PPTX files include a standard "Disclosures" slide at position 2 when needed to indicate AI-generated ALT text. |
| **Staged batch** | Batch runs create `<input_root>/staged_runs/<run_id>/` with `manifest.json` and `outputs/<relative_path>/`. |
| **Image derivatives** | Thumbnails = review docs only. Normalized images = LLaVA/model input only. |

---

## Where to Go Next

- **New user / operator:** [root README](../README.md) → Quick Start, Common Commands → [batch_manifest_skip_explained.md](batch_manifest_skip_explained.md) for resume/force.
- **Developer / contributor:** [docs index](README.md) → [entry-points-and-call-flow.md](entry-points-and-call-flow.md) → [alt-text-generation-workflow.md](alt-text-generation-workflow.md).
