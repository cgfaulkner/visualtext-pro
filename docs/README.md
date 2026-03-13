# VisualText Pro — Documentation index

**How to use the docs:** The [root README](../README.md) is the first stop for setup and usage. Workflow docs below help operators with batch resume and artifacts. Architecture docs help developers understand the pipeline. This index stays concise; use it to find the right doc.

---

## Start here

| Doc | Description |
|-----|-------------|
| [system-overview.md](system-overview.md) | Single-page plain-English pipeline explanation. |
| [root README](../README.md) | Setup, commands, configuration. |

---

## User-facing and workflow

| Doc | Description |
|-----|-------------|
| [batch_manifest_skip_explained.md](batch_manifest_skip_explained.md) | Why batch runs skip files (resume, fingerprint, status); manifest location; force reprocess. |
| [batch_resume_smoke_test.md](batch_resume_smoke_test.md) | Manual E2E checklist for batch resume and checkpointing. |

---

## Contracts and specs

| Doc | Description |
|-----|-------------|
| [batch_completion_criteria.md](batch_completion_criteria.md) | Canonical batch statuses, DONE vs retryable, file fingerprint, manifest location, atomic write. |
| [smart-selector-contract.md](smart-selector-contract.md) | Smart Selector contract: selection logic, versioning, change control. |
| [artifacts_thumbs_vs_normalized.md](artifacts_thumbs_vs_normalized.md) | Thumbnails (review only) vs normalized images (LLaVA only); config keys; conversion lifecycle. |

---

## Architecture and technical reference

| Doc | Description |
|-----|-------------|
| [entry-points-and-call-flow.md](entry-points-and-call-flow.md) | Entry points and call flow (altgen, processors, batch). |
| [execution-path-trace.md](execution-path-trace.md) | Execution path trace for single-file and batch. |
| [slide-processing.md](slide-processing.md) | Per-slide extraction and processing sequence. |
| [image-processing-flow.md](image-processing-flow.md) | Image detection, extraction, and flow (thumbs vs normalized). |
| [alt-text-generation-decisions.md](alt-text-generation-decisions.md) | Decision points in ALT text generation. |
| [external-dependencies.md](external-dependencies.md) | External dependencies (Ollama, PIL, config). |
| [workflow-assumptions-and-limitations.md](workflow-assumptions-and-limitations.md) | Workflow assumptions and limitations from code. |
| [alt-text-generation-workflow.md](alt-text-generation-workflow.md) | End-to-end ALT text generation workflow. |

---

## Other

| Doc | Description |
|-----|-------------|
| [repo-inventory.md](repo-inventory.md) | Repository structure and module inventory. |
| [archive/](archive/) | Historical implementation plans (staged runs, LLaVA gate, disclosure slide); current behavior is in the docs above. |
