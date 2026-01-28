# Rename Checklist — VisualText Pro

## Purpose of rename

Repo and project are "VisualText Pro"; align all docs and references, remove every mention of pdf-alt from tracked files, and avoid any assumption about repo folder name or absolute paths. Claude artifact folders are removed and ignored.

## Search terms used

- `pdf-alt`
- `pdf alt`
- `pdf_alt`
- `/pdf-alt/`
- `ProgrammingEnvs/pdf-alt`

## Files updated

- `.gitignore` — added `.claude_docs/` and `.claudedocs/`; removed `.claude_docs/pdf-alt.code-workspace`
- `README.md` — repository structure root → `./` with heading "From the repository root:"
- `docs/repo-inventory.md` — Repository Root and Root Folder Name made repo-agnostic; tree root → `./`; removed/rewrote internal-docs-folder discrepancy
- `docs/batch-operational-resilience.md` — replaced `.claude_docs/` reference with pointer to core/shared implementation
- `docs/repo-cleanup-snapshots/pre-cleanup-summary.txt` — rewrote reference to removed internal docs folder
- `docs/rename-checklist.md` — created (this file)
- `.claude_docs/` — deleted (all files and folder removed)

## Validation commands run

- `python3 altgen.py --help` — **OK** (exit 0; help text displayed).
- `python3 altgen.py --dry-run process "documents_to_review"` — **Fail** with `Error: No module named 'yaml'` (environment: install deps with `pip install -r requirements.txt`; not caused by this rename).
- Final verification: grep for `pdf-alt`, `pdf alt`, `.claude_docs`, `.claudedocs` in tracked files. Only remaining mentions: (1) this checklist’s “Search terms used” and “Final verification” and “Claude folder removal” sections, and (2) `.gitignore` entries `.claude_docs/` and `.claudedocs/` (ignore rules, not references). No other references in README, AGENTS, or docs.

## Notes / TODOs

- Re-run dry-run after `pip install -r requirements.txt` to confirm path_validator and runtime accept `documents_to_review`. Link/badge search found no `github.com/.../pdf-alt` or `shields.io` references.

## Claude folder removal

- **Which folder existed:** `.claude_docs/` only (`.claudedocs/` did not exist).
- **Removed:** Yes.
- **Confirmation:** No runtime or CI references were found; references existed only in `.gitignore`, docs (repo-inventory, pre-cleanup-summary, batch-operational-resilience), and files inside the folder. Those doc references were updated or removed before deletion.
