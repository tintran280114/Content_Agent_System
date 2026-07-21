# Content Agent System

Content Agent System is a Python foundation for developing content automation
capabilities. PLT-01 establishes only the repository and package bootstrap.

## Requirements

- Python 3.12

## Development setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux, activate it with `source .venv/bin/activate` instead.

Install the project in editable mode with its development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Run the project checks:

```powershell
python -m pytest
python -m ruff check .
python -m build
```

## Repository structure

```text
.
|-- src/
|   `-- content_agent/
|       `-- __init__.py
|-- tests/
|   `-- test_package.py
|-- .gitignore
|-- .python-version
|-- pyproject.toml
`-- README.md
```

The `src/content_agent/ai/` subtree is owned by the AI team member. PLT-01 does
not create or modify that subtree.
