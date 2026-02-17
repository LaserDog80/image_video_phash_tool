# Phash Tool — Renamer Upgrade Plan

> **Branch name:** `feature/smart-renaming`
> **Create from:** `main`
> **Files affected:** `media_pairing/file_renamer.py`, `media_pairing/test_gui.py`

---

## Context

The phash tool's `MediaFileRenamer` is the right place for the two key naming rules because it already does the renaming and it knows which image each clip belongs to. Currently it produces:

```
SPT25_SC38_002_S_V_001.mp4
```

The user needs:

```
SPT25_SC38_002_001_V.mp4
```

Three changes are required:

1. **Reorder and clean the filename template** — strip the source image suffix (`_S`), put the sequence number before the suffix, and make the format configurable.
2. **YES-first / MAYBE-second ordering** — accept a triage tier per video and number YES clips before MAYBE clips.
3. **Output folder scan** — check what already exists in the output folder and continue numbering from the highest existing sequence number, per image stem.

---

## Change 1: Flexible Filename Format

### Problem

The current `plan_renames()` hardcodes the output format as:

```python
dest_name = f"{dest_stem}_{self.suffix}_{idx:03d}{video_ext}"
# Produces: SPT25_SC38_002_S_V_001.mp4
```

Two issues:
- The `_S` from the source image name leaks into the output.
- The suffix comes before the sequence number, but the user wants it after.

### Solution

Add two new parameters to `MediaFileRenamer`:

```python
def __init__(
    self,
    output_dir: str | Path,
    suffix: str,
    overwrite: bool = False,
    dry_run: bool = False,
    strip_image_suffix: str | None = None,   # NEW
    seq_padding: int = 3,                      # NEW
) -> None:
```

**`strip_image_suffix`**: If provided, this string is stripped from the end of the image stem before building the output name. For example, `strip_image_suffix="_S"` turns `SPT25_SC38_002_S` into `SPT25_SC38_002`.

**`seq_padding`**: Zero-pad width for the sequence number. Default 3 gives `001`, `002`, etc. Set to 6 for `000001`, etc.

Update `plan_renames()` to build the filename as:

```python
# Strip image suffix if configured
if self.strip_image_suffix and dest_stem.endswith(self.strip_image_suffix):
    dest_stem = dest_stem[:-len(self.strip_image_suffix)]

# Build: {stem}_{NNN}_{suffix}{ext}
dest_name = f"{dest_stem}_{idx:0{self.seq_padding}d}_{self.suffix}{video_ext}"
```

This produces: `SPT25_SC38_002_001_V.mp4` ✓

### Backward Compatibility

The default behaviour (no `strip_image_suffix`, suffix before number) changes. This is acceptable because:
- The tool is internal, not a published library.
- The old format was never correct for the user's workflow.

If backward compat is needed, add a `legacy_format: bool = False` flag that preserves the old `{stem}_{suffix}_{NNN}` order.

---

## Change 2: YES-first / MAYBE-second Ordering

### Problem

When multiple videos match the same image, they're currently sorted by match distance (best first). There's no concept of triage priority — YES and MAYBE clips are interleaved by match quality.

### Solution

Add an optional `triage_map` parameter to `plan_renames()` and `execute()`:

```python
def plan_renames(
    self,
    pairing_result: PairingResult,
    triage_map: dict[str, str] | None = None,  # NEW: video_path -> "yes"|"maybe"|"unknown"
) -> list[dict]:
```

Within each image group, sort by triage tier first, then by distance:

```python
TRIAGE_PRIORITY = {"yes": 0, "unknown": 1, "maybe": 2}

sorted_pairs = sorted(
    pairs,
    key=lambda p: (
        TRIAGE_PRIORITY.get(triage_map.get(p["video"], "unknown"), 1),
        p["distance"],
        Path(p["video"]).name,
    ),
)
```

This means YES clips get `001, 002, 003` and MAYBE clips get `004, 005` — exactly as required.

### How the triage map gets populated

The caller (GUI or script) is responsible for building the `triage_map`. Two approaches:

**A. From folder structure** (for the GUI — most common case):

```python
def build_triage_map(video_paths: list[str]) -> dict[str, str]:
    """Infer triage status from folder path."""
    triage = {}
    for vp in video_paths:
        lower = vp.lower().replace("\\", "/")
        if "/yes/" in lower:
            triage[vp] = "yes"
        elif "/maybe/" in lower:
            triage[vp] = "maybe"
        else:
            triage[vp] = "unknown"
    return triage
```

Add this as a utility function in `file_renamer.py`.

**B. Explicit dict** (for script/component usage):

The caller simply passes `{"path/to/clip1.mp4": "yes", "path/to/clip2.mp4": "maybe"}`.

### GUI Integration

In `test_gui.py`, when the user clicks "Rename & Copy":

```python
triage_map = build_triage_map([p["video"] for p in result.pairs])
rename_result = renamer.execute(result, triage_map=triage_map)
```

The GUI doesn't need a new UI element — triage status is inferred from the folder the videos were loaded from. The debug log should show the detected triage status:

```
[12:34:56] Triage detected: 8 YES, 4 MAYBE, 0 unknown
```

---

## Change 3: Output Folder Scan (No Overwriting)

### Problem

If the user runs the tool in session 1 and produces `_001, _002, _003`, then runs again in session 2, the tool starts from `001` again. The current `overwrite=False` behaviour skips the file silently — but the user wants the new files to continue the sequence from `004`.

### Solution

Add a method `scan_existing_sequences()` to `MediaFileRenamer` and call it at the start of `plan_renames()`:

```python
def scan_existing_sequences(self) -> dict[str, int]:
    """Scan output_dir for existing files and return the highest
    sequence number per stem prefix.

    Returns:
        Dict mapping stem prefix to highest existing sequence number.
        e.g. {"SPT25_SC38_002": 3}
    """
    max_seq: dict[str, int] = {}

    if not self.output_dir.exists():
        return max_seq

    # Pattern: {prefix}_{NNN}_{suffix}{ext}
    # We need to match files that look like our output format
    import re
    pattern = re.compile(
        rf"^(.+?)_(\d{{{self.seq_padding},}})_{re.escape(self.suffix)}\.",
        re.IGNORECASE,
    )

    for file_path in self.output_dir.iterdir():
        if not file_path.is_file():
            continue
        match = pattern.match(file_path.name)
        if match:
            prefix = match.group(1)
            seq = int(match.group(2))
            if seq > max_seq.get(prefix, 0):
                max_seq[prefix] = seq

    return max_seq
```

Then in `plan_renames()`, after computing `dest_stem` (with suffix stripped), look up the starting offset:

```python
existing = self.scan_existing_sequences()

# For each image group:
start_idx = existing.get(dest_stem, 0) + 1

for idx, pair in enumerate(sorted_pairs, start=start_idx):
    dest_name = f"{dest_stem}_{idx:0{self.seq_padding}d}_{self.suffix}{video_ext}"
```

### Edge Cases

- **Output folder doesn't exist yet** → no existing files, start from 001. The folder gets created during `execute()`.
- **Files from a different suffix** (e.g. `_GRADE_001`) → regex won't match because it includes the current suffix. Correct — different suffixes are different sequences.
- **Mixed padding widths** (e.g. existing `_01` but current padding is 3) → the regex uses `{self.seq_padding,}` (minimum match), so `_01` would match if padding is 2+. For safety, use `\d+` and always parse the integer.

### Revised regex (more robust)

```python
pattern = re.compile(
    rf"^(.+?)_(\d+)_{re.escape(self.suffix)}\.",
    re.IGNORECASE,
)
```

This matches any digit width and is safer against mixed sessions.

---

## Updated `plan_renames()` — Full Logic

Putting all three changes together, the core of `plan_renames()` becomes:

```python
def plan_renames(
    self,
    pairing_result: PairingResult,
    triage_map: dict[str, str] | None = None,
) -> list[dict]:
    if not pairing_result.pairs:
        return []

    TRIAGE_PRIORITY = {"yes": 0, "unknown": 1, "maybe": 2}
    triage_map = triage_map or {}

    # Scan output folder for existing sequences
    existing_seqs = self.scan_existing_sequences()

    # Group pairs by image path
    image_to_pairs: dict[str, list[dict]] = defaultdict(list)
    for pair in pairing_result.pairs:
        image_to_pairs[pair["image"]].append(pair)

    planned: list[dict] = []
    seen_stems: dict[str, int] = {}

    for image_path, pairs in image_to_pairs.items():
        stem = Path(image_path).stem

        # Strip image suffix (e.g. "_S")
        if self.strip_image_suffix and stem.endswith(self.strip_image_suffix):
            stem = stem[:-len(self.strip_image_suffix)]

        stem_lower = stem.lower()

        # Handle same-name images from different directories
        if stem_lower in seen_stems:
            seen_stems[stem_lower] += 1
            dest_stem = f"{stem}_({seen_stems[stem_lower]})"
        else:
            seen_stems[stem_lower] = 1
            dest_stem = stem

        # Sort: triage tier first, then distance, then filename
        sorted_pairs = sorted(
            pairs,
            key=lambda p: (
                TRIAGE_PRIORITY.get(triage_map.get(p["video"], "unknown"), 1),
                p["distance"],
                Path(p["video"]).name,
            ),
        )

        # Start numbering after existing files
        start_idx = existing_seqs.get(dest_stem, 0) + 1

        for idx, pair in enumerate(sorted_pairs, start=start_idx):
            video_ext = Path(pair["video"]).suffix
            dest_name = f"{dest_stem}_{idx:0{self.seq_padding}d}_{self.suffix}{video_ext}"
            dest_video = self.output_dir / dest_name
            planned.append({
                "source": pair["video"],
                "destination": str(dest_video),
                "type": "video",
            })

    return planned
```

---

## Updated `execute()` Signature

```python
def execute(
    self,
    pairing_result: PairingResult,
    triage_map: dict[str, str] | None = None,  # NEW
) -> RenameResult:
    """Plan and execute the rename/copy operation."""
    start_time = time.time()
    result = RenameResult()

    plan = self.plan_renames(pairing_result, triage_map=triage_map)
    # ... rest unchanged ...
```

---

## GUI Changes (`test_gui.py`)

1. **Add a "Strip Suffix" input** next to the existing Suffix field. Label: `Strip from image name`. Default value: `_S`. This populates `strip_image_suffix`.

2. **Auto-detect triage** from video paths when "Rename & Copy" is clicked. Show a line in the debug log: `Triage detected: X YES, Y MAYBE, Z unknown`.

3. **Show offset info** in the debug log before copying: `Output folder has existing files: SPT25_SC38_002 → 3 existing, starting from 004`.

---

## Build Order

| Step | What | File |
|------|------|------|
| 1 | Create branch `feature/smart-renaming` from `main` | git |
| 2 | Add `strip_image_suffix` and `seq_padding` params to `__init__` | `file_renamer.py` |
| 3 | Update `plan_renames()` to strip suffix and reorder filename | `file_renamer.py` |
| 4 | Add `scan_existing_sequences()` method | `file_renamer.py` |
| 5 | Integrate scan into `plan_renames()` start index | `file_renamer.py` |
| 6 | Add `build_triage_map()` utility function | `file_renamer.py` |
| 7 | Add `triage_map` param to `plan_renames()` and `execute()` | `file_renamer.py` |
| 8 | Implement triage-aware sort in `plan_renames()` | `file_renamer.py` |
| 9 | Update GUI: strip suffix input, triage detection, offset logging | `test_gui.py` |
| 10 | Update tests for all new behaviour | `tests/` |

---

## Test Cases

### Filename Format
- [ ] Default: `SPT25_SC38_002_S` + suffix `V` + `strip_image_suffix="_S"` → `SPT25_SC38_002_001_V.mp4`
- [ ] No strip: `SPT25_SC38_002_S` + suffix `V` + no strip → `SPT25_SC38_002_S_001_V.mp4`
- [ ] Custom padding: `seq_padding=6` → `SPT25_SC38_002_000001_V.mp4`
- [ ] Different suffix: suffix `GRADE` → `SPT25_SC38_002_001_GRADE.mp4`
- [ ] Image stem collision (same name, different folders) → `_({n})` appended

### Triage Ordering
- [ ] 3 YES + 2 MAYBE for same image → YES get 001-003, MAYBE get 004-005
- [ ] All YES → numbered 001, 002, 003 normally
- [ ] All MAYBE → numbered 001, 002, 003 normally (no YES to come first)
- [ ] No triage map provided → falls back to distance-based ordering (backward compat)
- [ ] Mixed: YES with worse distance still comes before MAYBE with better distance
- [ ] `build_triage_map()` detects `/YES/` and `/MAYBE/` in paths (case-insensitive)
- [ ] `build_triage_map()` handles backslash paths on Windows

### Output Folder Scan
- [ ] Empty output folder → starts at 001
- [ ] Existing `_001_V`, `_002_V`, `_003_V` → new files start at `_004_V`
- [ ] Existing files for different stems → each stem gets independent offset
- [ ] Existing files with different suffix (e.g. `_GRADE`) → ignored, independent sequence
- [ ] Output folder doesn't exist yet → no scan, starts at 001, folder created on execute
- [ ] Existing files with varied padding (e.g. `_01` and `_001`) → both parsed correctly
- [ ] `overwrite=False` + collision (shouldn't happen with scan) → skip with warning logged

### Integration
- [ ] GUI: strip suffix field populated and passed to renamer
- [ ] GUI: triage auto-detected from folder paths, logged
- [ ] GUI: existing file offsets logged before copy begins
- [ ] Component usage: `execute(result, triage_map={...})` works as documented
- [ ] Dry run respects all new parameters
