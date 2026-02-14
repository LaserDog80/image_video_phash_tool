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

## How to Use the GUI

### Getting Started

```bash
# Install dependencies (one time)
uv pip install -r requirements.txt

# Launch the application
.venv/bin/python -m media_pairing.test_gui
```

### Step by Step

1. **Add your images** — click "+ Add Files" on the left panel and select your source images (JPG, PNG, WEBP, TIFF, BMP). You can also drag and drop files onto the panel.

2. **Add your videos** — click "+ Add Files" on the right panel and select your video clips (MP4, MKV, AVI, MOV, and others). Again, drag and drop works too.

3. **Run Matching** — click the button and the tool will analyse each file and figure out which videos belong to which images. Results appear colour-coded: green for matches, amber for unmatched files, red for errors.

4. **Set your suffix** — type a label into the Suffix field (e.g. `V`). This becomes part of the renamed filename. You must provide a suffix before copying.

5. **Rename & Copy** — click the button, choose an output folder, and the matched videos are copied there with their new names. Your original files are never touched.

### Settings

The GUI exposes four settings you can adjust before running:

- **Algorithm** — which visual fingerprinting method to use. `phash` works well for most cases. Try `dhash` if you're comparing colour-graded material against ungraded source images, as it focuses on structure rather than tone.

- **Tolerance** — how visually similar a video frame needs to be to an image to count as a match. Lower values are stricter. The default of 4 works well for AI-generated clips that closely resemble their source. Increase to 8-12 if matches are being missed; decrease to 1-2 if you're getting false matches.

- **Dark threshold** — how bright a video frame needs to be before the tool considers it "real" content rather than a black screen. This lets it skip past fade-from-black intros and dark leader frames to find the actual first frame of content. The default of 5.0 works for most videos.

- **Sample frames** — how many frames to extract from each video for comparison. The default of 1 (just the first meaningful frame) is usually enough. Increase this if your videos have misleading opening frames that don't represent the actual content.

### Other Features

- **Debug Log** — the bottom panel shows every step the tool takes: files loaded, hashes generated, comparisons made, errors encountered. Useful for understanding why a match did or didn't happen.
- **Export Results (JSON)** — save the full matching results to a file for use in other tools or scripts.
- **Copy Log** — copy the debug log to your clipboard.
- **Right-click** any file in the lists to remove it.

## Using as a Component

The GUI is just a thin wrapper around the core engine. If you want to integrate this into your own application or script, you can use it directly:

```python
from media_pairing import MediaPairingEngine, MediaFileRenamer

# Match images to videos
engine = MediaPairingEngine(hash_tolerance=4)
result = engine.find_pairs(
    image_paths=["beach_sunset.jpg", "mountain.png"],
    video_paths=["clip1.mp4", "clip2.mp4", "clip3.mp4"],
)

# See what matched
for pair in result.pairs:
    print(f"{pair['image']} matched {pair['video']}")

# Copy renamed videos to an output folder
renamer = MediaFileRenamer(output_dir="/path/to/output", suffix="V")
renamer.execute(result)
```

The engine handles all the complexity — frame extraction, black frame skipping, hash comparison, error collection — and returns clean, structured results that are easy to work with.

## Supported File Formats

**Images:** JPG, JPEG, PNG, BMP, WEBP, TIFF, TIF

**Videos:** MP4, MKV, AVI, MOV, WMV, FLV, WEBM, M4V

## Requirements

- Python 3.12+
- OpenCV, Pillow, ImageHash, NumPy (installed via `requirements.txt`)
- tkinterdnd2 (optional — enables drag-and-drop in the GUI; falls back to file dialogs without it)

## Development

See `CLAUDE.md` for development conventions, project structure, and how to run the test suite.
