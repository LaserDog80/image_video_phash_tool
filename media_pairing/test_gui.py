"""Lightweight tkinter test harness for the media pairing engine.

Provides drag-and-drop (via tkinterdnd2, optional) or file-dialog-based file
loading, configurable engine parameters, colour-coded results, and a scrollable
debug log that captures every engine operation.
"""

from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

from media_pairing.excel_export import export_rename_to_excel
from media_pairing.file_renamer import MediaFileRenamer, RenameResult, build_triage_map
from media_pairing.file_scanner import scan_directory
from media_pairing.pairing_engine import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaPairingEngine,
    PairingResult,
)

# Try to import drag-and-drop support; fall back gracefully.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except ImportError:
    HAS_DND = False

logger = logging.getLogger("media_pairing")


# ------------------------------------------------------------------
# Custom logging handler → tkinter Text widget
# ------------------------------------------------------------------


class _TextWidgetHandler(logging.Handler):
    """Routes log records to a tkinter Text widget, thread-safely."""

    def __init__(self, text_widget: tk.Text, root: tk.Tk) -> None:
        super().__init__()
        self.text_widget = text_widget
        self.root = root

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.root.after(0, self._append, msg, record.levelno)

    def _append(self, msg: str, level: int) -> None:
        self.text_widget.configure(state="normal")
        if level >= logging.ERROR:
            tag = "error"
        elif level >= logging.WARNING:
            tag = "warning"
        else:
            tag = "info"
        self.text_widget.insert("end", msg + "\n", tag)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")


# ------------------------------------------------------------------
# Main GUI class
# ------------------------------------------------------------------


class MediaPairingGUI:
    """Developer test harness for :class:`MediaPairingEngine`."""

    def __init__(self) -> None:
        # Root window — use TkinterDnD root if available.
        if HAS_DND:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("Media Pairing Test Tool")
        self.root.geometry("920x850")
        self.root.minsize(700, 600)

        self.image_paths: list[str] = []
        self.video_paths: list[str] = []
        self._matching = False
        self._last_result: Optional[PairingResult] = None
        self._last_rename_result: Optional[RenameResult] = None

        self._build_ui()
        self._setup_logging()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Top frame: file lists (images + videos side by side)
        file_frame = ttk.LabelFrame(self.root, text="Files", padding=6)
        file_frame.pack(fill="x", padx=8, pady=(8, 4))

        # Load Folder button — scans a directory for images and videos
        folder_frame = ttk.Frame(file_frame)
        folder_frame.pack(fill="x", pady=(0, 4))
        ttk.Button(
            folder_frame, text="Load Folder", command=self._load_folder
        ).pack(side="left")
        self.recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            folder_frame, text="Recursive", variable=self.recursive_var
        ).pack(side="left", padx=(8, 0))

        # Image list
        img_frame = ttk.Frame(file_frame)
        img_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        ttk.Label(img_frame, text="Images").pack(anchor="w")
        self.image_listbox = tk.Listbox(img_frame, height=6, selectmode="extended")
        self.image_listbox.pack(fill="both", expand=True)
        self._register_drop(self.image_listbox, "image")
        self._bind_context_menu(self.image_listbox, "image")

        btn_frame_img = ttk.Frame(img_frame)
        btn_frame_img.pack(fill="x", pady=(2, 0))
        ttk.Button(btn_frame_img, text="+ Add Files", command=self._add_images).pack(
            side="left"
        )
        ttk.Button(
            btn_frame_img, text="Remove Selected", command=self._remove_selected_images
        ).pack(side="left", padx=4)

        # Video list
        vid_frame = ttk.Frame(file_frame)
        vid_frame.pack(side="left", fill="both", expand=True, padx=(4, 0))

        ttk.Label(vid_frame, text="Videos").pack(anchor="w")
        self.video_listbox = tk.Listbox(vid_frame, height=6, selectmode="extended")
        self.video_listbox.pack(fill="both", expand=True)
        self._register_drop(self.video_listbox, "video")
        self._bind_context_menu(self.video_listbox, "video")

        btn_frame_vid = ttk.Frame(vid_frame)
        btn_frame_vid.pack(fill="x", pady=(2, 0))
        ttk.Button(btn_frame_vid, text="+ Add Files", command=self._add_videos).pack(
            side="left"
        )
        ttk.Button(
            btn_frame_vid,
            text="Remove Selected",
            command=self._remove_selected_videos,
        ).pack(side="left", padx=4)

        # Settings frame
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=6)
        settings_frame.pack(fill="x", padx=8, pady=4)

        row = ttk.Frame(settings_frame)
        row.pack(fill="x")

        ttk.Label(row, text="Algorithm:").pack(side="left")
        self.algo_var = tk.StringVar(value="phash")
        algo_combo = ttk.Combobox(
            row,
            textvariable=self.algo_var,
            values=["phash", "dhash", "ahash"],
            state="readonly",
            width=8,
        )
        algo_combo.pack(side="left", padx=(4, 16))

        ttk.Label(row, text="Tolerance:").pack(side="left")
        self.tolerance_var = tk.IntVar(value=4)
        ttk.Spinbox(
            row, textvariable=self.tolerance_var, from_=0, to=32, width=4
        ).pack(side="left", padx=(4, 16))

        ttk.Label(row, text="Dark threshold:").pack(side="left")
        self.dark_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(
            row, textvariable=self.dark_var, from_=0.0, to=128.0, increment=0.5, width=5
        ).pack(side="left", padx=(4, 16))

        ttk.Label(row, text="Sample frames:").pack(side="left")
        self.sample_var = tk.IntVar(value=1)
        ttk.Spinbox(
            row, textvariable=self.sample_var, from_=1, to=10, width=4
        ).pack(side="left", padx=(4, 0))

        # Action buttons
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=8, pady=4)

        self.run_btn = ttk.Button(
            action_frame, text="Run Matching", command=self._run_matching
        )
        self.run_btn.pack(side="left")

        ttk.Button(action_frame, text="Clear All", command=self._clear_all).pack(
            side="left", padx=8
        )

        ttk.Label(action_frame, text="Output suffix (e.g. V):").pack(
            side="left", padx=(16, 0)
        )
        self.suffix_var = tk.StringVar(value="V")
        self.suffix_entry = ttk.Entry(
            action_frame, textvariable=self.suffix_var, width=10
        )
        self.suffix_entry.pack(side="left", padx=(4, 4))

        ttk.Label(action_frame, text="Strip from image name:").pack(
            side="left", padx=(8, 0)
        )
        self.strip_suffix_var = tk.StringVar(value="_S")
        ttk.Entry(
            action_frame, textvariable=self.strip_suffix_var, width=8
        ).pack(side="left", padx=(4, 4))

        self.rename_btn = ttk.Button(
            action_frame,
            text="Rename & Copy",
            command=self._rename_and_copy,
            state="disabled",
        )
        self.rename_btn.pack(side="left", padx=4)

        ttk.Button(
            action_frame, text="Export Results (JSON)", command=self._export_results
        ).pack(side="right")

        ttk.Button(
            action_frame, text="Export to Excel", command=self._export_to_excel
        ).pack(side="right", padx=(0, 8))

        ttk.Button(action_frame, text="Copy Log", command=self._copy_log).pack(
            side="right", padx=8
        )

        # Results text
        results_frame = ttk.LabelFrame(self.root, text="Results", padding=4)
        results_frame.pack(fill="both", expand=True, padx=8, pady=4)

        self.results_text = tk.Text(
            results_frame, height=8, wrap="word", state="disabled"
        )
        results_scroll = ttk.Scrollbar(
            results_frame, orient="vertical", command=self.results_text.yview
        )
        self.results_text.configure(yscrollcommand=results_scroll.set)
        self.results_text.pack(side="left", fill="both", expand=True)
        results_scroll.pack(side="right", fill="y")

        self.results_text.tag_configure("match", foreground="#2e7d32")
        self.results_text.tag_configure("unmatched_video", foreground="#e65100")
        self.results_text.tag_configure("unmatched_image", foreground="#bf360c")
        self.results_text.tag_configure("error_result", foreground="#b71c1c")
        self.results_text.tag_configure("stats", foreground="#1565c0")

        # Debug log
        log_frame = ttk.LabelFrame(self.root, text="Debug Log", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        self.log_text = tk.Text(
            log_frame, height=10, wrap="word", state="disabled", font=("Courier", 10)
        )
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("error", foreground="#b71c1c")
        self.log_text.tag_configure("warning", foreground="#e65100")
        self.log_text.tag_configure("info", foreground="#212121")

    # ------------------------------------------------------------------
    # Drag-and-drop registration
    # ------------------------------------------------------------------

    def _register_drop(self, widget: tk.Listbox, target: str) -> None:
        """Register a widget as a drag-and-drop target (if tkinterdnd2 is available)."""
        if not HAS_DND:
            return

        widget.drop_target_register(DND_FILES)

        def _on_drop(event: tk.Event) -> None:
            raw = event.data
            paths = self._parse_drop_data(raw)
            for p in paths:
                self._add_file(p, target)

        widget.dnd_bind("<<Drop>>", _on_drop)

    @staticmethod
    def _parse_drop_data(data: str) -> list[str]:
        """Parse the raw string from a DnD drop event into file paths.

        tkinterdnd2 wraps paths containing spaces in braces: {/path/with spaces}.
        """
        paths: list[str] = []
        i = 0
        while i < len(data):
            if data[i] == "{":
                end = data.index("}", i)
                paths.append(data[i + 1 : end])
                i = end + 2  # skip closing brace + space
            elif data[i] == " ":
                i += 1
            else:
                end = data.find(" ", i)
                if end == -1:
                    end = len(data)
                paths.append(data[i:end])
                i = end + 1
        return paths

    # ------------------------------------------------------------------
    # Context menus
    # ------------------------------------------------------------------

    def _bind_context_menu(self, listbox: tk.Listbox, target: str) -> None:
        menu = tk.Menu(listbox, tearoff=0)
        menu.add_command(
            label="Remove Selected",
            command=lambda: self._remove_from_listbox(listbox, target),
        )

        def _show(event: tk.Event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        # Right-click: Button-2 on macOS, Button-3 elsewhere.
        listbox.bind("<Button-2>", _show)
        listbox.bind("<Button-3>", _show)

    def _remove_from_listbox(self, listbox: tk.Listbox, target: str) -> None:
        selected = list(listbox.curselection())
        if not selected:
            return
        store = self.image_paths if target == "image" else self.video_paths
        for idx in reversed(selected):
            listbox.delete(idx)
            del store[idx]

    # ------------------------------------------------------------------
    # File adding helpers
    # ------------------------------------------------------------------

    def _add_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[
                ("Image files", " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))),
                ("All files", "*.*"),
            ],
        )
        for p in paths:
            self._add_file(p, "image")

    def _add_videos(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Videos",
            filetypes=[
                ("Video files", " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))),
                ("All files", "*.*"),
            ],
        )
        for p in paths:
            self._add_file(p, "video")

    def _add_file(self, path: str, target: str) -> None:
        """Add a single file to the appropriate list, auto-sorting by extension."""
        ext = Path(path).suffix.lower()

        if target == "image" and ext in IMAGE_EXTENSIONS:
            if path not in self.image_paths:
                self.image_paths.append(path)
                self.image_listbox.insert("end", Path(path).name)
        elif target == "video" and ext in VIDEO_EXTENSIONS:
            if path not in self.video_paths:
                self.video_paths.append(path)
                self.video_listbox.insert("end", Path(path).name)
        elif ext in IMAGE_EXTENSIONS:
            # Dropped on wrong panel — redirect.
            if path not in self.image_paths:
                self.image_paths.append(path)
                self.image_listbox.insert("end", Path(path).name)
        elif ext in VIDEO_EXTENSIONS:
            if path not in self.video_paths:
                self.video_paths.append(path)
                self.video_listbox.insert("end", Path(path).name)
        else:
            logger.warning("Skipped unrecognised file type: %s", Path(path).name)

    def _load_folder(self) -> None:
        """Open a directory chooser and stage all images and videos found."""
        folder = filedialog.askdirectory(title="Select Root Folder")
        if not folder:
            return

        result = scan_directory(folder, recursive=self.recursive_var.get())

        for p in result.image_paths:
            if p not in self.image_paths:
                self.image_paths.append(p)
                self.image_listbox.insert("end", Path(p).name)

        for p in result.video_paths:
            if p not in self.video_paths:
                self.video_paths.append(p)
                self.video_listbox.insert("end", Path(p).name)

    def _remove_selected_images(self) -> None:
        self._remove_from_listbox(self.image_listbox, "image")

    def _remove_selected_videos(self) -> None:
        self._remove_from_listbox(self.video_listbox, "video")

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _run_matching(self) -> None:
        if self._matching:
            return

        if not self.image_paths and not self.video_paths:
            self._write_result("Nothing to compare — add some files first.\n", "stats")
            return

        self._matching = True
        self.run_btn.configure(state="disabled", text="Matching...")

        # Clear previous results
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.configure(state="disabled")

        engine = MediaPairingEngine(
            hash_algo=self.algo_var.get(),
            hash_tolerance=self.tolerance_var.get(),
            dark_threshold=self.dark_var.get(),
            sample_frames=self.sample_var.get(),
        )

        images = list(self.image_paths)
        videos = list(self.video_paths)

        def _worker() -> None:
            try:
                result = engine.find_pairs(images, videos)
                self.root.after(0, self._display_result, result)
            except Exception as exc:
                logger.exception("Matching failed")
                self.root.after(
                    0,
                    self._write_result,
                    f"ERROR: {exc}\n",
                    "error_result",
                )
            finally:
                self.root.after(0, self._matching_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _matching_done(self) -> None:
        self._matching = False
        self.run_btn.configure(state="normal", text="Run Matching")

    def _display_result(self, result: PairingResult) -> None:
        self._last_result = result

        # Pairs
        for pair in result.pairs:
            self._write_result(
                f"  MATCH  {Path(pair['video']).name}  <->  "
                f"{Path(pair['image']).name}  (distance: {pair['distance']})\n",
                "match",
            )

        # Unmatched videos
        for v in result.unmatched_videos:
            self._write_result(
                f"  NO MATCH  {Path(v).name} — no image match found\n",
                "unmatched_video",
            )

        # Unmatched images
        for img in result.unmatched_images:
            self._write_result(
                f"  NO MATCH  {Path(img).name} — no video match found\n",
                "unmatched_image",
            )

        # Errors
        for err in result.errors:
            self._write_result(
                f"  ERROR  {Path(err['file']).name}: {err['error_message']}\n",
                "error_result",
            )

        # Stats
        s = result.stats
        self._write_result(
            f"\n--- Stats: {s.get('pairs_found', 0)} pairs, "
            f"{s.get('total_comparisons', 0)} comparisons, "
            f"{s.get('time_elapsed', 0):.2f}s "
            f"({s.get('algorithm', '?')}, tolerance {s.get('tolerance', '?')}) ---\n",
            "stats",
        )

        # Enable Rename & Copy if there are matched pairs
        if result.pairs:
            self.rename_btn.configure(state="normal")
        else:
            self.rename_btn.configure(state="disabled")

    def _write_result(self, text: str, tag: str) -> None:
        self.results_text.configure(state="normal")
        self.results_text.insert("end", text, tag)
        self.results_text.see("end")
        self.results_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Utility buttons
    # ------------------------------------------------------------------

    def _clear_all(self) -> None:
        self.image_paths.clear()
        self.video_paths.clear()
        self.image_listbox.delete(0, "end")
        self.video_listbox.delete(0, "end")
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._last_result = None
        self.rename_btn.configure(state="disabled")

    def _copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end"))

    def _export_results(self) -> None:
        if self._last_result is None:
            logger.info("No results to export — run matching first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Results",
        )
        if not path:
            return
        data = {
            "pairs": self._last_result.pairs,
            "unmatched_images": self._last_result.unmatched_images,
            "unmatched_videos": self._last_result.unmatched_videos,
            "errors": self._last_result.errors,
            "stats": self._last_result.stats,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Results exported to %s", path)

    def _export_to_excel(self) -> None:
        """Export rename results to an Excel workbook."""
        if self._last_rename_result is None:
            logger.info("No rename results to export — run Rename & Copy first.")
            return
        if not self._last_rename_result.copied_files:
            logger.info("No copied files to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            title="Export Clip Report to Excel",
        )
        if not path:
            return
        try:
            export_rename_to_excel(self._last_rename_result, path)
            logger.info("Excel report exported to %s", path)
        except Exception:
            logger.exception("Failed to export Excel report")

    # ------------------------------------------------------------------
    # Rename & Copy
    # ------------------------------------------------------------------

    def _rename_and_copy(self) -> None:
        if self._last_result is None or not self._last_result.pairs:
            return

        suffix = self.suffix_var.get().strip().lstrip("_")
        if not suffix:
            self._write_result(
                "  ERROR  A suffix is required before copying "
                "(e.g. V, GRADE, EDIT).\n",
                "error_result",
            )
            self.suffix_entry.focus_set()
            return

        output_dir = filedialog.askdirectory(
            title="Select Output Folder for Renamed Files",
            initialdir=getattr(self, "_last_output_dir", None),
        )
        if not output_dir:
            return

        self._last_output_dir = output_dir
        self.rename_btn.configure(state="disabled", text="Copying...")

        result = self._last_result
        strip_suffix = self.strip_suffix_var.get().strip() or None

        def _worker() -> None:
            try:
                renamer = MediaFileRenamer(
                    output_dir=output_dir,
                    suffix=suffix,
                    strip_image_suffix=strip_suffix,
                )

                # Auto-detect triage from video folder paths
                triage_map = build_triage_map(
                    [p["video"] for p in result.pairs]
                )
                yes_count = sum(1 for v in triage_map.values() if v == "yes")
                maybe_count = sum(
                    1 for v in triage_map.values() if v == "maybe"
                )
                unknown_count = sum(
                    1 for v in triage_map.values() if v == "unknown"
                )
                logger.info(
                    "Triage detected: %d YES, %d MAYBE, %d unknown",
                    yes_count,
                    maybe_count,
                    unknown_count,
                )

                # Log existing file offsets
                existing = renamer.scan_existing_sequences()
                if existing:
                    for stem, max_seq in sorted(existing.items()):
                        logger.info(
                            "Output folder has existing files: "
                            "%s → %d existing, starting from %03d",
                            stem,
                            max_seq,
                            max_seq + 1,
                        )
                else:
                    logger.info("Output folder: no existing sequences found")

                rename_result = renamer.execute(result, triage_map=triage_map)
                self.root.after(0, self._display_rename_result, rename_result)
            except Exception as exc:
                logger.exception("Rename/copy failed")
                self.root.after(
                    0, self._write_result, f"RENAME ERROR: {exc}\n", "error_result"
                )
            finally:
                self.root.after(0, self._rename_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _rename_done(self) -> None:
        self.rename_btn.configure(state="normal", text="Rename & Copy")

    def _display_rename_result(self, rename_result: RenameResult) -> None:
        self._last_rename_result = rename_result
        self._write_result("\n--- Rename & Copy Results ---\n", "stats")

        for entry in rename_result.copied_files:
            self._write_result(
                f"  COPIED  {Path(entry['source']).name}  ->  "
                f"{Path(entry['destination']).name}\n",
                "match",
            )

        for entry in rename_result.skipped_files:
            self._write_result(
                f"  SKIPPED  {Path(entry['source']).name}: {entry['reason']}\n",
                "unmatched_video",
            )

        for entry in rename_result.errors:
            self._write_result(
                f"  ERROR  {Path(entry['source']).name}: {entry['error_message']}\n",
                "error_result",
            )

        s = rename_result.stats
        self._write_result(
            f"\n--- Copy Stats: {s['total_copied']} copied, "
            f"{s['total_skipped']} skipped, "
            f"{s['total_errors']} errors, "
            f"{s['time_elapsed']:.2f}s ---\n",
            "stats",
        )

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------

    def _setup_logging(self) -> None:
        handler = _TextWidgetHandler(self.log_text, self.root)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
        )
        root_logger = logging.getLogger("media_pairing")
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the tkinter main loop."""
        dnd_status = "enabled" if HAS_DND else "unavailable — use Add Files buttons"
        logger.info("Media Pairing Test Tool started (drag-and-drop: %s)", dnd_status)
        self.root.mainloop()


def main() -> None:
    app = MediaPairingGUI()
    app.run()


if __name__ == "__main__":
    main()
