"""Core media pairing engine — matches images to videos via perceptual hashing."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import cv2
import imagehash
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

HASH_ALGORITHMS: dict[str, callable] = {
    "phash": imagehash.phash,
    "dhash": imagehash.dhash,
    "ahash": imagehash.average_hash,
}

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif",
})

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
})


@dataclass
class PairingResult:
    """Structured result from a pairing run."""

    pairs: list[dict] = field(default_factory=list)
    unmatched_images: list[str] = field(default_factory=list)
    unmatched_videos: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class MediaPairingEngine:
    """Match image files to video files using perceptual hashing.

    Args:
        hash_algo: Hash algorithm to use ('phash', 'dhash', or 'ahash').
        hash_tolerance: Maximum Hamming distance for a match.
        skip_black_frames: Whether to skip dark/black frames during extraction.
        dark_threshold: Mean brightness below which a frame is considered dark.
        sample_frames: Number of meaningful frames to extract per video.
        max_probe_frames: Maximum frames to check before giving up on a video.
    """

    def __init__(
        self,
        hash_algo: str = "phash",
        hash_tolerance: int = 4,
        skip_black_frames: bool = True,
        dark_threshold: float = 5.0,
        sample_frames: int = 1,
        max_probe_frames: int = 30,
    ) -> None:
        if hash_algo not in HASH_ALGORITHMS:
            raise ValueError(
                f"Unknown hash algorithm '{hash_algo}'. "
                f"Choose from: {list(HASH_ALGORITHMS.keys())}"
            )

        self.hash_algo = hash_algo
        self.hash_func = HASH_ALGORITHMS[hash_algo]
        self.hash_tolerance = hash_tolerance
        self.skip_black_frames = skip_black_frames
        self.dark_threshold = dark_threshold
        self.sample_frames = sample_frames
        self.max_probe_frames = max_probe_frames

    # ------------------------------------------------------------------
    # Frame extraction
    # ------------------------------------------------------------------

    def extract_frames(self, video_path: str) -> list[Image.Image]:
        """Extract up to *sample_frames* meaningful (non-dark) frames from a video.

        Raises:
            FileNotFoundError: If the video file doesn't exist.
            RuntimeError: If OpenCV can't open the video.
        """
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")

        frames: list[Image.Image] = []
        frames_checked = 0

        try:
            while (
                len(frames) < self.sample_frames
                and frames_checked < self.max_probe_frames
            ):
                ret, frame = cap.read()
                if not ret:
                    break

                frames_checked += 1

                if self.skip_black_frames:
                    mean_brightness = float(np.mean(frame))
                    if mean_brightness < self.dark_threshold:
                        logger.debug(
                            "Skipped frame %d of %s (dark: mean=%.1f)",
                            frames_checked - 1,
                            path.name,
                            mean_brightness,
                        )
                        continue

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(rgb_frame)
                frames.append(pil_image)
                logger.debug(
                    "Extracted frame %d from %s",
                    frames_checked - 1,
                    path.name,
                )
        finally:
            cap.release()

        if not frames:
            logger.warning(
                "No meaningful frames found in %s after checking %d frames",
                path.name,
                frames_checked,
            )

        return frames

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    def hash_image(
        self, image_input: Union[str, Path, Image.Image]
    ) -> imagehash.ImageHash | None:
        """Hash a PIL Image or image file path using the configured algorithm."""
        try:
            if isinstance(image_input, (str, Path)):
                image = Image.open(image_input)
            else:
                image = image_input
            return self.hash_func(image)
        except Exception:
            logger.exception("Failed to hash image %s", image_input)
            return None

    def build_index(
        self, image_paths: list[str]
    ) -> tuple[dict[str, imagehash.ImageHash], list[dict]]:
        """Pre-compute hashes for all images.

        Returns:
            Tuple of (hash_dict, errors) where hash_dict maps paths to hashes.
        """
        hashes: dict[str, imagehash.ImageHash] = {}
        errors: list[dict] = []

        for path in image_paths:
            name = Path(path).name
            logger.info("Hashing image: %s", name)
            h = self.hash_image(path)
            if h is not None:
                hashes[path] = h
                logger.info("Hash (%s): %s for %s", self.hash_algo, h, name)
            else:
                errors.append({
                    "file": path,
                    "error_message": f"Failed to generate hash for {name}",
                })
        return hashes, errors

    # ------------------------------------------------------------------
    # Band-based hash bucketing (LSH)
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_to_int(h: imagehash.ImageHash) -> int:
        """Convert an ImageHash to a plain integer."""
        return int(str(h), 16)

    @staticmethod
    def _build_band_index(
        image_hashes: dict[str, imagehash.ImageHash],
    ) -> dict[tuple[int, int], list[str]]:
        """Build a band index for efficient approximate lookup.

        Splits each 64-bit hash into 4 x 16-bit bands.  Two hashes sharing
        *any* band are treated as candidates worth a full Hamming check.
        """
        bands: dict[tuple[int, int], list[str]] = defaultdict(list)
        for path, h in image_hashes.items():
            h_int = int(str(h), 16)
            for i in range(4):
                band_val = (h_int >> (i * 16)) & 0xFFFF
                bands[(i, band_val)].append(path)
        return bands

    @staticmethod
    def _find_candidates(
        video_hash: imagehash.ImageHash,
        band_index: dict[tuple[int, int], list[str]],
    ) -> set[str]:
        """Return candidate image paths that share at least one band."""
        candidates: set[str] = set()
        h_int = int(str(video_hash), 16)
        for i in range(4):
            band_val = (h_int >> (i * 16)) & 0xFFFF
            candidates.update(band_index.get((i, band_val), []))
        return candidates

    # ------------------------------------------------------------------
    # Main matching
    # ------------------------------------------------------------------

    def find_pairs(
        self, image_paths: list[str], video_paths: list[str]
    ) -> PairingResult:
        """Match images to videos by perceptual hash.

        For each video, extracts meaningful frames, hashes them, and finds the
        closest image within *hash_tolerance*.  Uses band-based bucketing when
        there are >= 100 images; brute-force otherwise.

        Returns a :class:`PairingResult` with pairs, unmatched files, errors,
        and timing stats.
        """
        start_time = time.time()
        result = PairingResult()
        total_comparisons = 0

        # Early exit for empty inputs
        if not image_paths or not video_paths:
            logger.info(
                "Nothing to compare: %d images, %d videos",
                len(image_paths),
                len(video_paths),
            )
            result.unmatched_images = list(image_paths)
            result.unmatched_videos = list(video_paths)
            result.stats = self._make_stats(
                total_comparisons, start_time, image_paths, video_paths, result,
            )
            return result

        # Build image hash index
        image_hashes, hash_errors = self.build_index(image_paths)
        result.errors.extend(hash_errors)

        # Choose lookup strategy
        use_bands = len(image_hashes) >= 100
        band_index = self._build_band_index(image_hashes) if use_bands else None

        matched_images: set[str] = set()
        matched_videos: set[str] = set()

        for video_path in video_paths:
            logger.info("Processing video: %s", Path(video_path).name)

            # Extract frames
            try:
                frames = self.extract_frames(video_path)
            except Exception as exc:
                result.errors.append({
                    "file": video_path,
                    "error_message": str(exc),
                })
                logger.error(
                    "Error extracting frames from %s: %s", video_path, exc,
                )
                continue

            if not frames:
                result.errors.append({
                    "file": video_path,
                    "error_message": f"No meaningful frames found in {Path(video_path).name}",
                })
                continue

            # Hash extracted frames
            video_hashes: list[imagehash.ImageHash] = []
            for i, frame in enumerate(frames):
                h = self.hash_image(frame)
                if h is not None:
                    video_hashes.append(h)
                    logger.info(
                        "Video %s frame %d hash (%s): %s",
                        Path(video_path).name,
                        i,
                        self.hash_algo,
                        h,
                    )

            if not video_hashes:
                result.errors.append({
                    "file": video_path,
                    "error_message": "Failed to hash any extracted frames",
                })
                continue

            # Find the best image match across all extracted frames
            best_match: str | None = None
            best_distance = float("inf")

            for vh in video_hashes:
                candidates = (
                    self._find_candidates(vh, band_index)
                    if use_bands
                    else image_hashes.keys()
                )

                for img_path in candidates:
                    ih = image_hashes[img_path]
                    distance = vh - ih
                    total_comparisons += 1

                    logger.debug(
                        "Comparing %s vs %s: distance=%d %s",
                        Path(video_path).name,
                        Path(img_path).name,
                        distance,
                        "MATCH" if distance <= self.hash_tolerance else "NO MATCH",
                    )

                    if distance < best_distance:
                        best_distance = distance
                        best_match = img_path

            if best_match is not None and best_distance <= self.hash_tolerance:
                result.pairs.append({
                    "video": video_path,
                    "image": best_match,
                    "distance": int(best_distance),
                    "algorithm": self.hash_algo,
                })
                matched_videos.add(video_path)
                matched_images.add(best_match)
                logger.info(
                    "Matched: %s <-> %s (distance: %d)",
                    Path(video_path).name,
                    Path(best_match).name,
                    best_distance,
                )
            else:
                logger.info(
                    "No match for video: %s (best distance: %s)",
                    Path(video_path).name,
                    best_distance if best_distance != float("inf") else "N/A",
                )

        # Determine unmatched files
        result.unmatched_images = [
            p for p in image_paths
            if p not in matched_images and p in image_hashes
        ]
        result.unmatched_videos = [
            p for p in video_paths if p not in matched_videos
        ]
        result.stats = self._make_stats(
            total_comparisons, start_time, image_paths, video_paths, result,
        )

        logger.info(
            "Matching complete: %d pairs found, %d comparisons in %.2fs",
            len(result.pairs),
            total_comparisons,
            result.stats["time_elapsed"],
        )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_stats(
        self,
        total_comparisons: int,
        start_time: float,
        image_paths: list[str],
        video_paths: list[str],
        result: PairingResult,
    ) -> dict:
        return {
            "total_comparisons": total_comparisons,
            "time_elapsed": round(time.time() - start_time, 3),
            "algorithm": self.hash_algo,
            "tolerance": self.hash_tolerance,
            "images_processed": len(image_paths),
            "videos_processed": len(video_paths),
            "pairs_found": len(result.pairs),
        }
