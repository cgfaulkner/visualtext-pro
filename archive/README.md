# Archive

This directory holds legacy code and output archives that are not used for active development.

## Contents

- **archive/core-backup/** — Former `core/backup/`. Legacy PDF/PPTX processors and injectors (pdf_accessibility_recreator, pdf_alt_injector, pdf_context_extractor, pdf_processor, pptx_alt_injector, pptx_processor). Moved 2026-01-27 during repo cleanup.

- **archive/old_project/** — Former `old_project/`. Legacy batch processor, LLaVA alt generator, pptx_alt, unified_alt_generator, and related config. Moved 2026-01-27 during repo cleanup.

- **Complete/** — Left at repo root. Contains timestamped output folders (e.g. ReviewThis_YYYYMMDD_HHMMSS). Per cleanup decision rule, files with _ALT / _NEW_ALT / review suffixes are outputs; if you want to archive Complete/ here later, move it to `archive/complete/` after owner sign-off.

## Do not import from archive in active code

Nothing in `core/`, `shared/`, or top-level scripts should import from `archive/` unless a shim is explicitly maintained.
