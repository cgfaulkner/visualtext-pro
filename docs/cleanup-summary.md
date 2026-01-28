# Repo Cleanup Summary — 2026-01-27

## What was moved/copied and where

- **core/backup/** → **archive/core-backup/** (legacy PDF/PPTX processors and injectors).
- **old_project/** → **archive/old_project/** (legacy batch processor, LLaVA alt generator, pptx_alt, etc.).
- **PPTX into documents_to_review/:** Copied from Slides to Review (1 file) and Temp (test2.pptx, smoke_test.pptx). See consolidation-preview.csv and consolidation-report.txt for full list and owner sign-off notes.
- **Complete/** left at repo root; output-side content (timestamped dirs) can be moved to archive/complete/ after owner sign-off.

## Which files were consolidated and which left in place

- **Consolidated into documents_to_review/:** test1_llava_latest_backup test names.pptx (from Slides to Review), test2.pptx and smoke_test.pptx (from Temp).
- **Left in place:** Complete/ReviewThis_* (output archive); Temp/*_NEW_ALT.pptx and other outputs; remaining Temp base PPTX listed in consolidation-preview.csv as candidates for owner approval. Documents to Review/ was missing. Originals were not deleted; deletion/move of originals requires explicit owner sign-off.

## config.yaml change

**Before:** `input_folder: Slides to Review`, `output_folder: Reviewed Reports`, `temp_folder: Temp`, `thumbnail_folder: Slide Thumbnails`  
**After:** `input_folder: documents_to_review`, `output_folder: reviewed_reports`, `temp_folder: temp`, `thumbnail_folder: slide_thumbnails`

See docs/repo-cleanup-snapshots/config-change.txt for the exact snippet.

## Runtime path validation

path_validator was updated to include canonical folder names (documents_to_review, reviewed_reports, temp, slide_thumbnails, archive) in `get_allowed_base_dirs()`. project_root already allows any path under the repo; canonical dirs were added explicitly. Dry-run was not executed in this run (environment missing PyYAML). **TODO:** Re-run `python altgen.py --dry-run process "documents_to_review"` after `pip install -r requirements.txt`; if path_validator or any runtime rejects the new names, record a TODO here and do not guess.

**path_validator refactor:** Prefer making shared/path_validator.py read allowed base directories from config.yaml rather than hardcoding. If that is out of scope, the current hardcoded canonical names are sufficient; a TODO is in path_validator and in import-fixes.txt.

## Runtime folders and README stubs

The four runtime folders (**documents_to_review**, **reviewed_reports**, **slide_thumbnails**, **temp**) are **intentionally tracked** so they appear on GitHub for new users and other universities or first-time contributors. A **README stub** in each folder explains its purpose (input PPTX, output reports, thumbnails, temp files). **Contents are ignored** so that real data is not committed: PPTX inputs, processed outputs, thumbnails, and temporary artifacts stay local.

## Git tracking policy for runtime folders

**documents_to_review**, **reviewed_reports**, **slide_thumbnails**, and **temp** must exist in git; their contents must be ignored. Implemented via a **README.md** in each folder (tracked) and a “Runtime folders” block in **.gitignore** that ignores each folder’s contents but allows that folder’s **README.md**. See `.gitignore` and README.

## One E2E non-dry run

**Deferred** — environment missing PyYAML in this run. After dependencies are installed, run:
`python altgen.py process "documents_to_review/smoke_test.pptx"` (or another copied PPTX) and record command, outcome, and any issues here or in consolidation-report.txt.

## Dry-run and test outputs

- **Dry-run:** Not run successfully (Error: No module named 'yaml'). Re-run after `pip install -r requirements.txt`.
- **Tests:** No tests/ directory in repo; pytest not run. CI references tests/fixtures/selector/... which are missing.

## Remaining open items

- tests/ missing; CI workflow validate-selector-schema references tests/fixtures/selector/... — restore tests or update CI.
- Deletion of originals (Slides to Review, Temp, etc.) after 48h — only after owner sign-off.
- Any uncertain Complete/ or Temp/ files — see consolidation-preview.csv and consolidation-report.txt for candidate inputs; owner to decide.
- E2E non-dry run and dry-run to be re-run in an environment with PyYAML.

## Symlinks (if created)

None created. If external tooling or colleagues need old folder names, add temporary symlinks (e.g. "Documents to Review" → documents_to_review), document in this file, and schedule removal after 48–72h or owner sign-off.

## Links to snapshots and branch/PR

- **docs/repo-cleanup-snapshots/:** pre-cleanup-summary.txt, config-change.txt, consolidation-preview.csv, consolidation-report.txt, import-fixes.txt, task-e-change-note.txt, README.md.
- **Screenshots:** Capture per list in pre-cleanup-summary.txt and save in docs/repo-cleanup-snapshots/.
- **Branch:** chrore/cleanup-structure-2026-01-27 (commit b830ab9 at run time). Add PR link here when pushed.
