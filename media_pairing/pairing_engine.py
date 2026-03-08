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


@dataclass
class VideoFingerprint:
    """A sequence of perceptual hashes sampled across a video's duration.

    Attributes:
        path: Path to the video file.
        hashes: Perceptual hashes at each sampled position.
        positions: Normalised positions (0.0–1.0) where each frame was taken.
    """

    path: str
    hashes: list[imagehash.ImageHash]
    positions: list[float]


class MediaPairingEngine:
    """Match image files to video files using perceptual hashing.

    Args:
        hash_algo: Hash algorithm to use ('phash', 'dhash', or 'ahash').
        hash_tolerance: Maximum Hamming distance for a match.
        skip_black_frames: Whether to skip dark/black frames during extraction.
        dark_threshold: Mean brightness below which a frame is considered dark.
        sample_frames: Number of meaningful frames to extract per video.
        max_probe_frames: Maximum frames to check before giving up on a video.
        video_match_frames: Number of evenly-spaced frames to sample for
            video-to-video matching (used by :meth:`find_video_pairs`).
    """

    def __init__(
        self,
        hash_algo: str = "phash",
        hash_tolerance: int = 4,
        skip_black_frames: bool = True,
        dark_threshold: float = 5.0,
        sample_frames: int = 1,
        max_probe_frames: int = 30,
        video_match_frames: int = 8,
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
        self.video_match_frames = video_match_frames

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

    def extract_frames_distributed(
        self,
        video_path: str,
        num_frames: int | None = None,
    ) -> tuple[list[Image.Image], list[float]]:
        """Extract frames spread evenly across a video's duration.

        Unlike :meth:`extract_frames` (which reads sequentially from the
        start), this method seeks to evenly-spaced positions so the
        resulting frames represent the full timeline of the video.

        Args:
            video_path: Path to the video file.
            num_frames: How many frames to sample.  Defaults to
                ``self.video_match_frames``.

        Returns:
            Tuple of (frames, positions) where *positions* are normalised
            floats in [0.0, 1.0].

        Raises:
            FileNotFoundError: If the video file doesn't exist.
            RuntimeError: If OpenCV can't open the video.
        """
        if num_frames is None:
            num_frames = self.video_match_frames

        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {video_path}")

        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Fallback: if container doesn't report frame count, use
            # the sequential extract_frames method instead.
            if total_frames <= 0:
                logger.warning(
                    "Cannot determine frame count for %s, falling back "
                    "to sequential extraction",
                    path.name,
                )
                cap.release()
                frames = self.extract_frames(video_path)
                positions = [0.0] * len(frames)
                return frames, positions

            actual_samples = min(num_frames, total_frames)
            if actual_samples <= 0:
                return [], []

            # Compute evenly-spaced frame indices
            if actual_samples == 1:
                target_indices = [0]
            else:
                target_indices = [
                    int(i * (total_frames - 1) / (actual_samples - 1))
                    for i in range(actual_samples)
                ]

            frames: list[Image.Image] = []
            positions: list[float] = []

            for target_idx in target_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
                ret, frame = cap.read()
                if not ret:
                    continue

                # Dark-frame handling: try a few nearby frames
                if self.skip_black_frames:
                    mean_brightness = float(np.mean(frame))
                    if mean_brightness < self.dark_threshold:
                        found_bright = False
                        for offset in range(1, 6):
                            alt_idx = min(target_idx + offset, total_frames - 1)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, alt_idx)
                            ret2, frame2 = cap.read()
                            if ret2 and float(np.mean(frame2)) >= self.dark_threshold:
                                frame = frame2
                                target_idx = alt_idx
                                found_bright = True
                                break
                        if not found_bright:
                            logger.debug(
                                "Skipped dark region near frame %d in %s",
                                target_idx,
                                path.name,
                            )
                            continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(Image.fromarray(rgb))
                norm_pos = target_idx / max(total_frames - 1, 1)
                positions.append(round(norm_pos, 4))
                logger.debug(
                    "Distributed frame at index %d (%.1f%%) from %s",
                    target_idx,
                    norm_pos * 100,
                    path.name,
                )
        finally:
            cap.release()

        if not frames:
            logger.warning(
                "No meaningful distributed frames found in %s", path.name
            )

        return frames, positions

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
    # Video fingerprinting
    # ------------------------------------------------------------------

    def build_video_index(
        self, video_paths: list[str]
    ) -> tuple[dict[str, VideoFingerprint], list[dict]]:
        """Build a fingerprint index for a list of videos.

        Each video is sampled at evenly-spaced positions and hashed to
        produce a :class:`VideoFingerprint`.

        Returns:
            Tuple of (fingerprint_dict, errors).
        """
        fingerprints: dict[str, VideoFingerprint] = {}
        errors: list[dict] = []

        for vp in video_paths:
            name = Path(vp).name
            logger.info("Fingerprinting video: %s", name)
            try:
                frames, positions = self.extract_frames_distributed(vp)
            except Exception as exc:
                errors.append({"file": vp, "error_message": str(exc)})
                logger.error("Error fingerprinting %s: %s", name, exc)
                continue

            if not frames:
                errors.append({
                    "file": vp,
                    "error_message": f"No meaningful frames in {name}",
                })
                continue

            hashes: list[imagehash.ImageHash] = []
            for frame in frames:
                h = self.hash_image(frame)
                if h is not None:
                    hashes.append(h)

            if not hashes:
                errors.append({
                    "file": vp,
                    "error_message": f"Failed to hash frames from {name}",
                })
                continue

            # Trim positions to match successful hashes (if some failed)
            fingerprints[vp] = VideoFingerprint(
                path=vp,
                hashes=hashes,
                positions=positions[: len(hashes)],
            )
            logger.info(
                "Fingerprinted %s: %d hashes across %d positions",
                name,
                len(hashes),
                len(positions),
            )

        return fingerprints, errors

    @staticmethod
    def _compare_fingerprints(
        fp_a: VideoFingerprint,
        fp_b: VideoFingerprint,
    ) -> float:
        """Compute the average Hamming distance between two video fingerprints.

        When fingerprints have different lengths, pairs are formed by
        matching each hash in the shorter fingerprint to the nearest
        normalised position in the longer one.

        Returns:
            Average Hamming distance as a float, or ``float('inf')`` if
            no valid comparisons could be made.
        """
        if not fp_a.hashes or not fp_b.hashes:
            return float("inf")

        # If same length, compare positionally
        if len(fp_a.hashes) == len(fp_b.hashes):
            distances = [
                ha - hb for ha, hb in zip(fp_a.hashes, fp_b.hashes)
            ]
            return sum(distances) / len(distances)

        # Different lengths: pair by nearest normalised position
        shorter, longer = (
            (fp_a, fp_b) if len(fp_a.hashes) <= len(fp_b.hashes)
            else (fp_b, fp_a)
        )
        total_dist = 0
        for i, s_hash in enumerate(shorter.hashes):
            s_pos = shorter.positions[i] if i < len(shorter.positions) else 0.0
            # Find nearest position in longer fingerprint
            best_idx = 0
            best_gap = float("inf")
            for j, l_pos in enumerate(longer.positions):
                gap = abs(s_pos - l_pos)
                if gap < best_gap:
                    best_gap = gap
                    best_idx = j
            total_dist += s_hash - longer.hashes[best_idx]

        return total_dist / len(shorter.hashes)

    def find_video_pairs(
        self,
        source_videos: list[str],
        target_videos: list[str],
    ) -> PairingResult:
        """Match target videos to source videos by comparing fingerprints.

        *Source* videos provide the base name for renaming.  *Target*
        videos are the files being matched (and potentially renamed).

        The matching logic mirrors :meth:`find_pairs`: for each target,
        find the source with the lowest average Hamming distance within
        ``hash_tolerance``.

        Returns:
            A :class:`PairingResult`.  Each pair dict contains:

            - ``"image"`` / ``"source"``: the source video path
            - ``"video"`` / ``"target"``: the target video path
            - ``"distance"``: average Hamming distance (float)
            - ``"algorithm"``: hash algorithm used
            - ``"match_type"``: ``"video_to_video"``
        """
        start_time = time.time()
        result = PairingResult()
        total_comparisons = 0

        if not source_videos or not target_videos:
            logger.info(
                "Nothing to compare: %d source videos, %d target videos",
                len(source_videos),
                len(target_videos),
            )
            result.unmatched_images = list(source_videos)
            result.unmatched_videos = list(target_videos)
            result.stats = self._make_stats(
                total_comparisons, start_time,
                source_videos, target_videos, result,
            )
            return result

        # Build fingerprints for both sets
        source_fps, src_errors = self.build_video_index(source_videos)
        target_fps, tgt_errors = self.build_video_index(target_videos)
        result.errors.extend(src_errors)
        result.errors.extend(tgt_errors)

        matched_sources: set[str] = set()
        matched_targets: set[str] = set()

        for tgt_path, tgt_fp in target_fps.items():
            best_match: str | None = None
            best_distance = float("inf")

            for src_path, src_fp in source_fps.items():
                avg_dist = self._compare_fingerprints(src_fp, tgt_fp)
                total_comparisons += 1

                logger.debug(
                    "Video compare %s vs %s: avg_distance=%.2f %s",
                    Path(tgt_path).name,
                    Path(src_path).name,
                    avg_dist,
                    "MATCH" if avg_dist <= self.hash_tolerance else "NO MATCH",
                )

                if avg_dist < best_distance:
                    best_distance = avg_dist
                    best_match = src_path

            if best_match is not None and best_distance <= self.hash_tolerance:
                result.pairs.append({
                    "image": best_match,    # backward compat for renamer
                    "video": tgt_path,      # backward compat for renamer
                    "source": best_match,
                    "target": tgt_path,
                    "distance": round(best_distance, 2),
                    "algorithm": self.hash_algo,
                    "match_type": "video_to_video",
                })
                matched_sources.add(best_match)
                matched_targets.add(tgt_path)
                logger.info(
                    "Video matched: %s <-> %s (avg distance: %.2f)",
                    Path(tgt_path).name,
                    Path(best_match).name,
                    best_distance,
                )
            else:
                logger.info(
                    "No video match for: %s (best avg distance: %s)",
                    Path(tgt_path).name,
                    f"{best_distance:.2f}"
                    if best_distance != float("inf")
                    else "N/A",
                )

        result.unmatched_images = [
            p for p in source_videos
            if p not in matched_sources and p in source_fps
        ]
        result.unmatched_videos = [
            p for p in target_videos if p not in matched_targets
        ]
        result.stats = self._make_stats(
            total_comparisons, start_time,
            source_videos, target_videos, result,
        )
        result.stats["match_type"] = "video_to_video"

        logger.info(
            "Video matching complete: %d pairs, %d comparisons in %.2fs",
            len(result.pairs),
            total_comparisons,
            result.stats["time_elapsed"],
        )
        return result

    # ------------------------------------------------------------------
    # Main matching (image-to-video)
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
