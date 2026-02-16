"""Scan a directory tree and classify files as images or videos.

Given a root folder, recursively (or flat) discovers all media files and
separates them into image and video lists based on file extension.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from media_pairing.pairing_engine import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

logger = logging.getLogger("media_pairing")


@dataclass
class ScanResult:
    """Structured result from a directory scan."""

    image_paths: list[str] = field(default_factory=list)
    video_paths: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def scan_directory(root: str | Path, recursive: bool = True) -> ScanResult:
    """Walk a directory tree and classify files as images or videos.

    Args:
        root: Root directory to scan.
        recursive: If ``True``, descend into subdirectories.

    Returns:
        A :class:`ScanResult` with classified file paths and scan stats.

    Raises:
        FileNotFoundError: If *root* does not exist.
        NotADirectoryError: If *root* is not a directory.
    """
    start_time = time.time()
    root_path = Path(root)

    if not root_path.exists():
        raise FileNotFoundError(f"Directory not found: {root}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    result = ScanResult()
    glob_pattern = "**/*" if recursive else "*"

    for entry in sorted(root_path.glob(glob_pattern)):
        if not entry.is_file():
            continue

        ext = entry.suffix.lower()

        if ext in IMAGE_EXTENSIONS:
            result.image_paths.append(str(entry))
        elif ext in VIDEO_EXTENSIONS:
            result.video_paths.append(str(entry))
        else:
            result.skipped.append(str(entry))

    result.stats = {
        "root": str(root_path),
        "recursive": recursive,
        "images_found": len(result.image_paths),
        "videos_found": len(result.video_paths),
        "skipped": len(result.skipped),
        "time_elapsed": round(time.time() - start_time, 3),
    }

    logger.info(
        "Scanned %s: %d images, %d videos, %d skipped (%.3fs)",
        root_path,
        len(result.image_paths),
        len(result.video_paths),
        len(result.skipped),
        result.stats["time_elapsed"],
    )
    return result
