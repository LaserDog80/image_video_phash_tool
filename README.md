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

After matching and renaming you get:
```
beach_sunset_001.mp4
beach_sunset_002.mp4
beach_sunset_003.mp4
```

You can optionally add a suffix label (e.g. `V`) to get `beach_sunset_001_V.mp4` instead — useful for distinguishing video versions, colour grades, edits, etc.

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

4. **Rename and copy** — Matched videos are copied to an output folder with structured names: `{image_stem}_{NNN}{ext}` by default, or `{image_stem}_{NNN}_{suffix}{ext}` when an optional suffix is provided. Videos matched to the same image are sorted by triage tier (YES > unknown > MAYBE, inferred from folder paths) and then by match distance (best first). Sequence numbers continue from where existing files in the output folder left off, so you can run the tool incrementally without overwriting previous results.

## Setup

### Prerequisites

- **Python 3.12+** — download from [python.org](https://www.python.org/downloads/) or install via your package manager
- **uv** (recommended) — fast Python package manager. Install from [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/)

### macOS / Linux

```bash
# Clone the repository
git clone https://github.com/LaserDog80/image_video_phash_tool.git
cd image_video_phash_tool

# Create a virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# Launch the application
.venv/bin/python -m media_pairing.test_gui
```

> **Linux note:** tkinter may not be bundled with your Python install. If you get a `ModuleNotFoundError: No module named 'tkinter'`, install it with your package manager:
> ```bash
> # Debian / Ubuntu
> sudo apt install python3-tk
>
> # Fedora
> sudo dnf install python3-tkinter
>
> # Arch
> sudo pacman -S tk
> ```

### Windows

```powershell
# Clone the repository
git clone https://github.com/LaserDog80/image_video_phash_tool.git
cd image_video_phash_tool

# Create a virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# Launch the application
.venv\Scripts\python -m media_pairing.test_gui
```

> **Without uv:** You can use plain pip instead:
> ```bash
> python -m venv .venv
>
> # macOS / Linux
> source .venv/bin/activate
>
> # Windows
> .venv\Scripts\activate
>
> pip install -r requirements.txt
> python -m media_pairing.test_gui
> ```

## How to Use the GUI

### Step by Step

The tool has two matching modes, shown as tabs at the top of the window:

#### Image → Video (default tab)

Use this when you have a folder of source images and a separate folder of video clips to match against them.

1. **Load Image Folder** — select the folder containing your source images (left panel).
2. **Load Video Folder** — select the folder containing your video clips (right panel).
3. You can also use **+ Add Files** to pick individual files, or drag and drop if supported.
4. **Run Matching** — the tool analyses each file and figures out which videos belong to which images. Results appear colour-coded: green for matches, amber for unmatched files, red for errors.

#### Video → Video

Use this when you want to match two sets of video files against each other — for example, matching low-res proxy clips to their high-res originals, or finding duplicates across two folders.

1. **Load Source Folder** — select the folder containing your reference videos (left panel). These provide the filenames for renaming.
2. **Load Target Folder** — select the folder containing the videos you want to match (right panel).
3. **Run Matching** — the tool samples multiple frames from each video, builds a fingerprint for each one, and compares them. This is slower than image matching because it processes several frames per video instead of just one.

> **Note:** If you load the same folder as both source and target, the tool will skip self-comparisons (a video won't match against itself) and only fingerprint each file once.

#### Rename & Copy

After running either matching mode, click **Rename & Copy**, choose an output folder, and the matched videos are copied there with clean, structured names. Your original files are never touched. By default, videos are named `{image}_{001}.mp4`. If you want an extra label, type it into the optional Suffix field (e.g. `V`) to get `{image}_{001}_V.mp4`.

### Settings

All settings are shared between both tabs. You can adjust them before running a match.

| Setting | What it does | Default | Range | When to change it |
|---------|-------------|---------|-------|-------------------|
| **Algorithm** | Which visual fingerprinting method to use. Think of it as a way of summarising what an image "looks like" as a short code. | `phash` | `phash`, `dhash`, `ahash` | `phash` works for most cases. Try `dhash` if comparing colour-graded footage against ungraded source images — it focuses on shapes and edges rather than colour. `ahash` is fastest but least accurate. |
| **Tolerance** | How different two fingerprints can be and still count as a match. Lower = stricter (fewer but more accurate matches). Higher = looser (more matches but risk of false positives). | `4` | `0`–`32` | The default of 4 works well for AI-generated clips that closely resemble their source. Increase to 8–12 if genuine matches are being missed. Decrease to 1–2 if you're getting false matches (wrong videos paired to wrong images). A value of 0 means the images must be virtually identical. |
| **Dark threshold** | How bright a frame needs to be before the tool considers it real content rather than a black screen. Measured as average pixel brightness (0 = pure black, 255 = pure white). | `5.0` | `0.0`–`128.0` | This lets the tool skip past fade-from-black intros and dark leader frames. The default of 5.0 works for most videos. Increase if your videos have very dark (but not black) opening scenes that are being skipped. Set to 0 to disable black frame skipping entirely. |
| **Sample frames** | How many frames to extract from each video when doing **Image → Video** matching. | `1` | `1`–`10` | The default of 1 (just the first meaningful frame) is usually enough for AI-generated clips. Increase if your videos have misleading opening frames — the tool will check multiple frames and use the best match. |
| **Video match frames** | How many frames to sample across the full length of each video when doing **Video → Video** matching. Frames are spread evenly from start to end. | `8` | `2`–`30` | More frames = more accurate matching but slower processing. 8 is a good balance. Increase to 15–20 for long videos where the content changes significantly throughout. Decrease to 3–4 if you need faster results and the videos are short or visually consistent. |

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

# Simple mode: beach_sunset_001.mp4
renamer = MediaFileRenamer(output_dir="/path/to/output")
rename_result = renamer.execute(result)

# With suffix: beach_sunset_001_V.mp4
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

## Running Tests

```bash
# macOS / Linux
.venv/bin/python -m pytest tests/ -v

# Windows
.venv\Scripts\python -m pytest tests/ -v
```

## Development

See `CLAUDE.md` for development conventions, project structure, and how to run the test suite.
