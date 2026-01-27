# AGENTS Instructions for VisualText Pro

This project provides tools to extract, clean, and rebuild presentations and PDFs with improved
alternative text for accessibility.

## Project Layout
- `core/`: modules orchestrating PDF and PPTX processing.
- `shared/`: utilities for configuration management and alt-text generation.
- `documents_to_review/`: canonical input folder for presentations (sample/tests).
- `config.yaml`: default configuration settings.
- Command-line utilities: `pptx_alt_processor.py`, `pptx_clean_processor.py`,
  `pptx_manifest_processor.py`.

## Coding Guidelines
- Target Python 3.12 and follow [PEP 8](https://peps.python.org/pep-0008/) style.
- Include type hints and docstrings for public functions and classes.
- Keep lines under 100 characters.
- End files with a single newline.

## Dependency Management
- Add new Python dependencies to `requirements.txt` with explicit versions when possible.

## Testing
- Run `pytest` from the repository root to execute the available tests.
- Ensure the sample presentation in `documents_to_review/test1_llava_latest_backup test names.pptx`
  remains available for tests.

