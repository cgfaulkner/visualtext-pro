Updated README - pdf-alt

Overview
pdf-alt is an accessibility toolkit for extracting images from PowerPoint decks, generating high-quality alternative text, injecting the text back into the slides, and optionally exporting accessible PDFs or review artifacts.

The repository also includes a clean three-phase pipeline and a manifest-driven workflow that act as alternative implementations for producing consistent, reviewable accessibility data.


Repository layout
* core/ – orchestration logic for PPTX and PDF processing pipelines.
* shared/ – shared utilities for configuration, generation, and manifest handling.
* Slides to Review/ – sample decks and the default staging folder for new presentations.
* config.yaml – default runtime configuration (paths, fallback policy, prompts, providers).
* Command-line entry points: pptx_alt_processor.py, pptx_clean_processor.py, and pptx_manifest_processor.py for progressively more structured workflows.
Installation
1. Use Python 3.12 in a fresh virtual environment to match the project’s target runtime.
2. Install dependencies with pip install -r requirements.txt to pull in PPTX/PDF tooling, document generators, and the Ollama client used for LLaVA calls.
Configuration
The project reads settings from config.yaml, including the default ALT-text mode (preserve), fallback policy, worker pool size, and cache reuse rules.

Paths for inputs, outputs, thumbnails, and temporary files default to folders inside the repository, so the bundled “Slides to Review” samples work out of the box.

Prompt templates and decorative-image overrides drive how suggested text is generated and when shapes should be treated as decorative.

The ai_providers section points to a local LLaVA endpoint (http://127.0.0.1:11434

) with retry and timeout controls; update these values if you run the model elsewhere.

Quick start
1. Place a PPTX deck in Slides to Review/ (or adjust the paths.input_folder entry).
2. Generate alternative text and update the deck in place:
3. python pptx_alt_processor.py process "Slides to Review/your_deck.pptx"
4. Add --export-pdf to produce an accessible PDF after injection, or use the other commands described below for batch work, review docs, or manifest workflows.
Command-line tools
pptx_alt_processor.py
This integration script wires together the existing configuration manager, the PPTX accessibility processor, and the injector to deliver a single “generate and inject” command with optional PDF export and logging enhancements.

Usage: python pptx_alt_processor.py <command> [options]
Subcommands and notable flags
* process <pptx> – end-to-end generation and injection. Optional flags include --export-pdf, --generate-approval-documents, --approval-doc-only, and --approval-out for creating Word review packages in addition to updating the PPTX.Shape-handling controls (--llava-include-shapes, --max-shapes-per-slide, --min-shape-area) tune which vector shapes are described.Use --skip-injection to generate without writing to the deck, or --dry-run to exercise the manifest pipeline without modifying files.
* batch-process <folder> – process every PPTX matching --pattern (default *.pptx), optionally writing results to --output-dir and exporting PDFs.
* extract <pptx> – pull image metadata into JSON, optionally saved with --output for manual authoring workflows.
* inject <pptx> – apply ALT text from a JSON mapping supplied via --alt-text-file, with optional --output to write to a new deck.
* test-survival <pptx> – verify ALT text survives PDF export paths.
Global options
Pass --config to point at a non-default configuration file, --verbose or --debug for richer logging, --fallback-policy to override decorative handling (none, doc-only, ppt-gated), and --mode (preserve or replace) to control how existing ALT text is treated during injection.

pptx_clean_processor.py
The clean pipeline implements explicit scan, generate, and resolve phases that emit JSON artifacts alongside the updated deck, making it easier to audit or re-run individual stages.
Usage: python pptx_clean_processor.py <command> [options]
* process <pptx> – runs all three phases, injects ALT text (unless --review-doc-only), and optionally builds a Word review document with --review-doc and --review-out. Use --mode to choose between preserving or replacing existing text and --force-regenerate to ignore caches.
* inject <pptx> – inject from a previously generated final_alt_map.json supplied via --alt-map, with optional --output and --mode controls.
* review – build a DOCX review document from existing visual_index, current_alt, and final_alt JSON files, with optional --title customization.
Global flags mirror the main pipeline (--config, --verbose, --force-regenerate, --mode).

pptx_manifest_processor.py
The manifest workflow stores every ALT-text decision in a single JSONL file so future injection or review runs can reuse cached results without re-calling LLaVA.
Usage: python pptx_manifest_processor.py <command> [options]
* process <pptx> – extracts assets, generates ALT text into a manifest, injects into the deck (unless --review-only), and/or builds a review document (--review-doc, --review-out). Specify --manifest to control where the manifest is written and --mode to set preservation behavior.
* inject <pptx> – validate and inject from an existing manifest (--manifest), optionally writing to a new file with --output and adjusting --mode as needed.
* review – create a DOCX review document straight from a manifest, with optional --title.
* validate <manifest> – check manifest health, list statistics, and confirm injectability before running other commands.
Global options include --config, --verbose, --force-regenerate, and --no-thumbnails to skip thumbnail generation for faster runs.

Samples and review assets
The repository keeps a regression-friendly sample deck at Slides to Review/test1_llava_latest_backup test names.pptx; keep it available when running tests or demos.

Testing
Run pytest from the repository root to execute the automated suite when you change pipeline behavior or configuration rules.

