# AGENTS Instructions for pdf-alt

This repository contains tools for recreating PDF documents with improved accessibility and alternative text handling.

## Project Layout
- `core/`: Primary modules orchestrating PDF processing and recreation.
- `shared/`: Utilities such as configuration management and alt-text generation.
- `Documents to Review/`: Sample input PDFs used in tests and examples.
- `config.yaml`: Default configuration settings.

## Coding Guidelines
- Target Python 3.12 and follow [PEP 8](https://peps.python.org/pep-0008/) style.
- Include type hints and docstrings for public functions and classes.
- Keep lines under 100 characters.
- End files with a single newline.

## Dependency Management
- Add new Python dependencies to `requirements.txt`.

## Testing
- Run `pytest` from the repository root to execute the available workflow test.
- Ensure the sample PDF in `Documents to Review/test1_demo.pdf` remains available for tests.

