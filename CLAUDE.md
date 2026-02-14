# CLAUDE.md

> **Purpose:** Persistent instructions for Claude when working in this project.  
> **Rule:** Edit specific sections. Never rewrite this file entirely.

---

## Project Overview

<!-- Update this section when the project scope changes -->

[Project name and one-line description]

---

## Tech Stack

- **Language:** Python 3.x
- **Web framework:** [Flask/FastAPI/None—update as needed]
- **Testing:** pytest
- **Package manager:** pip (use requirements.txt)

---

## Development Workflow

```bash
# 1. Create virtual environment (first time only)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run tests
pytest

# 4. Run local server (if web-based)
python app.py  # or: flask run / uvicorn main:app

# 5. Before committing
pytest && git add -A && git commit -m "message"
```

---

## Code Standards

- Use type hints for function signatures
- Docstrings for public functions
- Keep functions under 30 lines where possible
- Prefer explicit over clever

---

## File Structure Conventions

```
project/
├── src/              # Main source code
├── tests/            # Test files (mirror src/ structure)
├── requirements.txt  # Dependencies
├── app.py            # Entry point (if web-based)
└── README.md         # User-facing documentation
```

---

## Known Issues & Workarounds

<!-- Append new issues here as they're discovered -->

- None yet

---

## Do NOT Do

<!-- Append items here when Claude makes mistakes -->

- Do not rewrite CLAUDE.md or LEARNINGS.md entirely—edit sections only
- Do not delete test files without explicit approval
- Do not change the directory structure without discussing first
