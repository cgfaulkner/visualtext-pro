# Contributing to VisualText Pro

## Development setup

1. **Python**: Use Python 3.12 in a fresh virtual environment (on macOS you can use `brew install python@3.12` or install from [python.org](https://www.python.org/downloads/)).

2. **Virtual environment and dependencies**:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Validation commands

Before submitting changes, run:

```bash
python altgen.py --help
python altgen.py --dry-run process "documents_to_review"
```

These confirm the CLI and path handling work as expected.

## Tests

There is no formal test suite yet. When tests are added, run `pytest` from the repository root. CI (`.github/workflows/python-app.yml`) runs flake8 and pytest when present.

## Pull request guidelines

- Prefer small, focused PRs. Separate documentation changes from code changes when practical.
- Run formatting and lint checks: `flake8` is configured via `.flake8`; run it before pushing. CI runs these checks as well.
