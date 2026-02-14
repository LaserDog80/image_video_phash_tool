# CLAUDE.md

> **Purpose:** Persistent instructions for Claude when working in this project.  
> **Rule:** Edit specific sections. Never rewrite this file entirely.

---

## Project Overview

Media Pairing Tool — matches image files to video files using perceptual hashing, with a tkinter test GUI for debugging.

---

## Tech Stack

- **Language:** Python 3.12+
- **Web framework:** None (tkinter for test GUI)
- **Testing:** pytest
- **Package manager:** uv (use `uv pip install -r requirements.txt`)
- **Key libraries:** opencv-python, Pillow, ImageHash, numpy, tkinterdnd2 (optional)

---

## Development Workflow

```bash
# 1. Install dependencies
uv pip install -r requirements.txt

# 2. Run tests
.venv/bin/python -m pytest tests/ -v

# 3. Launch the test GUI
.venv/bin/python -m media_pairing.test_gui

# 4. Before committing
.venv/bin/python -m pytest tests/ && git add -A && git commit -m "message"
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
├── media_pairing/            # Main package
│   ├── __init__.py
│   ├── pairing_engine.py     # Core matching engine (reusable component)
│   └── test_gui.py           # Tkinter test harness (developer tool)
├── tests/                    # pytest tests
│   └── test_pairing_engine.py
├── requirements.txt          # Dependencies
└── README.md
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
