# Media Pairing Tool

Automatically match images to their corresponding video clips and rename the videos to share the same name as the image they came from. Built for workflows where you generate multiple video clips from a single source image — for example, AI video generation — and need to organise the output.

This is designed as a **reusable component** that can be dropped into larger applications, but it also works perfectly well as a **standalone application** through its built-in GUI.

## What It Does

You give it a batch of images and a batch of videos. The tool looks at the visual content of each file — not the filename — and figures out which videos match which images. It does this by comparing a visual fingerprint (called a perceptual hash) of each image against the opening frame of each video.

Once it finds the matches, you can copy the videos to an output folder with clean, structured filenames based on the image they matched to.

### Example

You have:
- `beach_sunset.jpg` (your source image)
- `IMG_8821.mp4`, `IMG_8822.mp4`, `IMG_8823.mp4` (three AI-generated clips of that image)

After matching and renaming with suffix `V`, you get:
```
beach_sunset_V_001.mp4
beach_sunset_V_002.mp4
beach_sunset_V_003.mp4
```

The suffix is up to you — use `V` for video, `GRADE` for colour-graded versions, `EDIT` for edited cuts, or whatever makes sense for your workflow.

## How It Works

The matching pipeline has four stages:

1. **Frame extraction** — Each video is opened with OpenCV and the first meaningful frame is extracted. "Meaningful" means the tool skips past dark or black frames (common in fade-from-black intros) by checking mean brightness against a configurable threshold. You can also extract multiple sample frames per video if the first frame isn't representative.

2. **Perceptual hashing** — Each image and each extracted video frame is reduced to a compact fingerprint using a perceptual hash algorithm. Three algorithms are available:
   - **pHash** (default) — uses DCT-based frequency analysis. Good all-rounder for content-preserving transformations like resizing and minor colour shifts.
   - **dHash** — compares adjacent pixel gradients. Better for matching across colour grading changes since it focuses on structure rather than tone.
   - **aHash** — averages pixel values. Fastest, but less discriminating.

   Each algorithm produces a 64-bit hash that captures the visual essence of the image while ignoring minor differences.

3. **Comparison** — Video frame hashes are compared against image hashes using Hamming distance (the number of differing bits). A distance of 0 means the images are perceptually identical; higher values mean greater visual difference. A match is accepted only if the distance falls within the configured tolerance (default: 4 bits out of 64).

   For large image sets (100+), the engine uses **band-based bucketing** (a form of locality-sensitive hashing) to avoid brute-force comparison. Each 64-bit hash is split into four 16-bit bands, and only images sharing at least one band with the video frame are considered as candidates. This dramatically reduces the number of comparisons needed.

4. **Rename and copy** — Matched videos are copied to an output folder with structured names: `{image_stem}_{NNN}_{suffix}{ext}`. Videos matched to the same image are sorted by triage tier (YES > unknown > MAYBE, inferred from folder paths) and then by match distance (best first). Sequence numbers continue from where existing files in the output folder left off, so you can run the tool incrementally without overwriting previous results.

## How to Use the GUI

### Getting Started

```bash
# Install dependencies (one time)
uv pip install -r requirements.txt

# Launch the application
.venv/bin/python -m media_pairing.test_gui
```

### Step by Step

1. **Add your files** — click "+ Add Files" on the image (left) or video (right) panel to select individual files, or use "Load Folder" to scan an entire directory (with optional recursion). Drag and drop is supported if tkinterdnd2 is installed.

2. **Run Matching** — click the button and the tool will analyse each file and figure out which videos belong to which images. Results appear colour-coded: green for matches, amber for unmatched files, red for errors.

3. **Set your suffix** — type a label into the Suffix field (e.g. `V`). This becomes part of the renamed filename. You must provide a suffix before copying.

4. **Rename & Copy** — click the button, choose an output folder, and the matched videos are copied there with their new names. Your original files are never touched.

### Settings

The GUI exposes four settings you can adjust before running:

- **Algorithm** — which visual fingerprinting method to use. `phash` works well for most cases. Try `dhash` if you're comparing colour-graded material against ungraded source images, as it focuses on structure rather than tone.

- **Tolerance** — how visually similar a video frame needs to be to an image to count as a match. Lower values are stricter. The default of 4 works well for AI-generated clips that closely resemble their source. Increase to 8-12 if matches are being missed; decrease to 1-2 if you're getting false matches.

- **Dark threshold** — how bright a video frame needs to be before the tool considers it "real" content rather than a black screen. This lets it skip past fade-from-black intros and dark leader frames to find the actual first frame of content. The default of 5.0 works for most videos.

- **Sample frames** — how many frames to extract from each video for comparison. The default of 1 (just the first meaningful frame) is usually enough. Increase this if your videos have misleading opening frames that don't represent the actual content.

### Other Features

- **Debug Log** — the bottom panel shows every step the tool takes: files loaded, hashes generated, comparisons made, errors encountered. Useful for understanding why a match did or didn't happen.
- **Export Results (JSON)** — save the full matching results to a JSON file for use in other tools or scripts.
- **Export Results (Excel)** — save the rename results to an `.xlsx` workbook with columns for description, scene number, source filename, output filename, and creation date. Useful for downstream VFX or editing workflows.
- **Copy Log** — copy the debug log to your clipboard.
- **Right-click** any file in the lists to remove it.

## Using as a Component

The GUI is just a thin wrapper around the core engine. If you want to integrate this into your own application or script, you can use the modules directly:

### Scan a directory for media files

```python
from media_pairing import scan_directory

scan = scan_directory("/path/to/media", recursive=True)
print(f"Found {len(scan.image_paths)} images, {len(scan.video_paths)} videos")
```

### Match images to videos

```python
from media_pairing import MediaPairingEngine

engine = MediaPairingEngine(hash_tolerance=4)
result = engine.find_pairs(
    image_paths=["beach_sunset.jpg", "mountain.png"],
    video_paths=["clip1.mp4", "clip2.mp4", "clip3.mp4"],
)

for pair in result.pairs:
    print(f"{pair['image']} matched {pair['video']} (distance: {pair['distance']})")

print(f"Unmatched images: {result.unmatched_images}")
print(f"Unmatched videos: {result.unmatched_videos}")
```

### Copy matched videos with structured names

```python
from media_pairing import MediaFileRenamer

renamer = MediaFileRenamer(output_dir="/path/to/output", suffix="V")
rename_result = renamer.execute(result)

print(f"Copied {rename_result.stats['total_copied']} files")
```

### Export rename results to Excel

```python
from media_pairing import export_rename_to_excel

export_rename_to_excel(rename_result, "/path/to/report.xlsx")
```

### Full public API

| Export | Module | Description |
|--------|--------|-------------|
| `MediaPairingEngine` | `pairing_engine` | Core matching engine |
| `PairingResult` | `pairing_engine` | Dataclass for match results |
| `MediaFileRenamer` | `file_renamer` | Rename and copy matched videos |
| `RenameResult` | `file_renamer` | Dataclass for rename results |
| `scan_directory` | `file_scanner` | Recursively scan a folder for media files |
| `ScanResult` | `file_scanner` | Dataclass for scan results |
| `export_rename_to_excel` | `excel_export` | Write rename results to an `.xlsx` workbook |

All exports are available from the top-level package:

```python
from media_pairing import MediaPairingEngine, MediaFileRenamer, scan_directory, export_rename_to_excel
```

## Supported File Formats

**Images:** JPG, JPEG, PNG, BMP, WEBP, TIFF, TIF

**Videos:** MP4, MKV, AVI, MOV, WMV, FLV, WEBM, M4V

## Project Structure

```
project/
├── media_pairing/
│   ├── __init__.py           # Public API exports
│   ├── pairing_engine.py     # Core matching engine (hashing, comparison, pairing)
│   ├── file_scanner.py       # Directory scanning and file classification
│   ├── file_renamer.py       # Rename planning, triage sorting, and file copying
│   ├── excel_export.py       # Excel workbook generation for rename reports
│   └── test_gui.py           # Tkinter test harness / standalone GUI
├── tests/
│   ├── test_pairing_engine.py
│   ├── test_file_scanner.py
│   ├── test_file_renamer.py
│   └── test_excel_export.py
├── requirements.txt
└── README.md
```

## Requirements

- Python 3.12+
- OpenCV, Pillow, ImageHash, NumPy, openpyxl (installed via `requirements.txt`)
- tkinterdnd2 (optional — enables drag-and-drop in the GUI; falls back to file dialogs without it)

## Development

See `CLAUDE.md` for development conventions, project structure, and how to run the test suite.
