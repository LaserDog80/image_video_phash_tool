"""Copy matched videos to an output folder with structured names.

Given a :class:`PairingResult` from the pairing engine, this module copies
each matched video renamed to ``{image_stem}_{suffix}_{NNN}{video_ext}`` —
where *suffix* is a user-provided label and *NNN* is a zero-padded sequence
number ordered by match quality (best match = 001).
"""

from __future__ import annotations

import logging
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from media_pairing.pairing_engine import PairingResult

logger = logging.getLogger("media_pairing")


@dataclass
class RenameResult:
    """Structured result from a rename/copy operation."""

    copied_files: list[dict] = field(default_factory=list)
    skipped_files: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


class MediaFileRenamer:
    """Copy matched videos to *output_dir* with structured names.

    Args:
        output_dir: Target directory for copied files.
        suffix: Required label appended after the sequence number
            (e.g. ``"V"`` produces ``image_001_V.mp4``).
        overwrite: If ``True``, overwrite existing files in the output dir.
        dry_run: If ``True``, compute the rename plan but don't copy anything.

    Raises:
        ValueError: If *suffix* is empty or whitespace-only.
    """

    def __init__(
        self,
        output_dir: str | Path,
        suffix: str,
        overwrite: bool = False,
        dry_run: bool = False,
    ) -> None:
        if not suffix or not suffix.strip():
            raise ValueError("A suffix is required (e.g. 'V', 'GRADE', 'EDIT').")
        self.output_dir = Path(output_dir)
        self.suffix = suffix.strip()
        self.overwrite = overwrite
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # Planning (pure logic, no I/O)
    # ------------------------------------------------------------------

    def plan_renames(self, pairing_result: PairingResult) -> list[dict]:
        """Build a rename plan from a :class:`PairingResult`.

        Only videos are copied — images are used solely to derive the base
        name.  Returns a list of planned copy operations::

            [{"source": str, "destination": str, "type": "video"}, ...]

        Videos matched to the same image are sorted by distance (best first),
        with source filename as a tiebreaker for deterministic ordering.
        """
        if not pairing_result.pairs:
            return []

        # Group pairs by image path
        image_to_pairs: dict[str, list[dict]] = defaultdict(list)
        for pair in pairing_result.pairs:
            image_to_pairs[pair["image"]].append(pair)

        planned: list[dict] = []
        seen_stems: dict[str, int] = {}  # lowercase stem → count (collision tracking)

        for image_path, pairs in image_to_pairs.items():
            stem = Path(image_path).stem
            stem_lower = stem.lower()

            # Handle same-name images from different directories
            if stem_lower in seen_stems:
                seen_stems[stem_lower] += 1
                dest_stem = f"{stem}_({seen_stems[stem_lower]})"
            else:
                seen_stems[stem_lower] = 1
                dest_stem = stem

            # Sort videos: best match first, filename tiebreaker
            sorted_pairs = sorted(
                pairs, key=lambda p: (p["distance"], Path(p["video"]).name)
            )

            # Plan: copy each video with suffix then sequential number
            for idx, pair in enumerate(sorted_pairs, start=1):
                video_ext = Path(pair["video"]).suffix
                dest_name = f"{dest_stem}_{self.suffix}_{idx:03d}{video_ext}"
                dest_video = self.output_dir / dest_name
                planned.append({
                    "source": pair["video"],
                    "destination": str(dest_video),
                    "type": "video",
                })

        return planned

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, pairing_result: PairingResult) -> RenameResult:
        """Plan and execute the rename/copy operation.

        Returns a :class:`RenameResult` with copied, skipped, and errored files.
        """
        start_time = time.time()
        result = RenameResult()

        plan = self.plan_renames(pairing_result)
        if not plan:
            logger.info("Nothing to copy — no matched pairs.")
            result.stats = self._make_stats(result, start_time)
            return result

        # Ensure output directory exists
        if not self.dry_run:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Output directory: %s", self.output_dir)

        for entry in plan:
            src = entry["source"]
            dst = entry["destination"]
            src_name = Path(src).name
            dst_name = Path(dst).name

            # Check source exists
            if not Path(src).exists():
                result.errors.append({
                    "source": src,
                    "error_message": f"Source file not found: {src_name}",
                })
                logger.error("Source not found: %s", src_name)
                continue

            # Check destination collision
            if Path(dst).exists() and not self.overwrite:
                result.skipped_files.append({
                    "source": src,
                    "reason": f"Destination already exists: {dst_name}",
                })
                logger.warning("Skipped (exists): %s -> %s", src_name, dst_name)
                continue

            if self.dry_run:
                result.copied_files.append(entry)
                logger.info("[DRY RUN] Would copy: %s -> %s", src_name, dst_name)
                continue

            # Copy
            try:
                shutil.copy2(src, dst)
                result.copied_files.append(entry)
                logger.info("Copied: %s -> %s", src_name, dst_name)
            except Exception:
                logger.exception("Failed to copy %s", src_name)
                result.errors.append({
                    "source": src,
                    "error_message": f"Copy failed for {src_name}",
                })

        result.stats = self._make_stats(result, start_time)
        logger.info(
            "Rename/copy complete: %d copied, %d skipped, %d errors in %.2fs",
            result.stats["total_copied"],
            result.stats["total_skipped"],
            result.stats["total_errors"],
            result.stats["time_elapsed"],
        )
        return result

    @staticmethod
    def _make_stats(result: RenameResult, start_time: float) -> dict:
        return {
            "total_copied": len(result.copied_files),
            "total_skipped": len(result.skipped_files),
            "total_errors": len(result.errors),
            "time_elapsed": round(time.time() - start_time, 3),
        }
