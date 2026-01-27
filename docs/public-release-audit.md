# Public Release Audit

## Search terms used

- **Secrets-like**: `key`, `token`, `secret`, `password`, `api`, `bearer`, `Authorization` — scoped to `*.py`, `*.yaml`, `*.yml`, `*.json`, `*.md`, `*.env`, `*.txt`
- **Absolute paths**: `/Users/`
- **Campus/internal identifiers**: `campus`, `internal`, `UTSW`, `utsw`, `university`, `institution`, `department` — starting from `docs/` and config files

## Findings

- **Secrets-like terms**: Benign uses only (e.g. "Key Features", `image_key`, `max_tokens`, `api/generate`, config `base_url: http://127.0.0.1:11434`). No credentials or API keys in code or config.
- **Absolute paths**: No `/Users/` matches in the repository.
- **Campus/internal**: UTSW-specific decorative filenames in `config.yaml` (previously lines 50–57, now replaced); `archive/old_project/config.yaml` still contains UTSW entries (legacy, not active); `shared/decorative_filter.py` test/example block referenced `utsw_logo.png` (replaced with neutral example).
- **Git-tracked runtime content**: `git ls-files` for `logs/`, `reviewed_reports/`, `slide_thumbnails/`, `temp/`, `documents_to_review/`, and `*.pptx` — only `reviewed_reports/README.md` and `slide_thumbnails/README.md` are tracked. No logs, outputs, thumbnails, or real PPTX files are committed. No tracked files under `documents_to_review/` or `temp/` in the index.
- **Config hostnames**: Active `config.yaml` uses `http://127.0.0.1:11434` only (public default). No real hostnames or private IPs.

## What was removed or redacted

- Institution-specific decorative filename examples were replaced with neutral placeholders in config.yaml. A comment was added to guide user customization.
- UTSW-specific decorative entries in `config.yaml` were replaced with `your_org_logo.png` and `organization_logo.jpg`; a short comment was added above the `exact` list.
- In `shared/decorative_filter.py`, the `__main__` test/example block was updated to use `your_org_logo.png` instead of `utsw_logo.png` so no institution-specific identifiers remain in active code. Archive config was not modified.

## What is confirmed safe

- No secrets, API keys, or credentials in the repository.
- No `/Users/` absolute paths in tracked files.
- Active configuration uses only `127.0.0.1` for the LLaVA endpoint.
- Logs, output folders (`reviewed_reports/`, `slide_thumbnails/`, `temp/`), and `documents_to_review/` contents are not tracked; only README stubs in `reviewed_reports/` and `slide_thumbnails/` are in the index. No `.pptx` files are tracked.
