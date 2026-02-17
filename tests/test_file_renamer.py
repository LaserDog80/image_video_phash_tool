"""Tests for the file renamer module."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_pairing.file_renamer import (
    MediaFileRenamer,
    RenameResult,
    build_triage_map,
)
from media_pairing.pairing_engine import PairingResult


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _touch(path: Path, content: bytes = b"fake") -> str:
    """Create a small file and return its string path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def _result_with_pairs(pairs: list[dict]) -> PairingResult:
    """Build a PairingResult with only pairs populated."""
    return PairingResult(pairs=pairs)


# ------------------------------------------------------------------
# Initialisation tests
# ------------------------------------------------------------------


class TestInit:
    def test_empty_suffix_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="suffix is required"):
            MediaFileRenamer(output_dir=tmp_path, suffix="")

    def test_whitespace_suffix_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="suffix is required"):
            MediaFileRenamer(output_dir=tmp_path, suffix="   ")

    def test_valid_suffix_accepted(self, tmp_path: Path) -> None:
        renamer = MediaFileRenamer(output_dir=tmp_path, suffix="V")
        assert renamer.suffix == "V"

    def test_suffix_stripped(self, tmp_path: Path) -> None:
        renamer = MediaFileRenamer(output_dir=tmp_path, suffix="  GRADE  ")
        assert renamer.suffix == "GRADE"

    def test_strip_image_suffix_stored(self, tmp_path: Path) -> None:
        renamer = MediaFileRenamer(
            output_dir=tmp_path, suffix="V", strip_image_suffix="_S"
        )
        assert renamer.strip_image_suffix == "_S"

    def test_seq_padding_stored(self, tmp_path: Path) -> None:
        renamer = MediaFileRenamer(
            output_dir=tmp_path, suffix="V", seq_padding=6
        )
        assert renamer.seq_padding == 6


# ------------------------------------------------------------------
# plan_renames tests — filename format
# ------------------------------------------------------------------


class TestPlanRenames:
    def test_single_pair(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "beach.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        plan = renamer.plan_renames(_result_with_pairs([
            {"image": img, "video": vid, "distance": 2, "algorithm": "phash"},
        ]))

        assert len(plan) == 1
        assert plan[0]["type"] == "video"
        assert Path(plan[0]["destination"]).name == "beach_001_V.mp4"

    def test_no_image_in_plan(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "beach.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 2, "algorithm": "phash"},
            ])
        )

        types = [e["type"] for e in plan]
        assert "image" not in types

    def test_custom_suffix(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "beach.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(output_dir=out, suffix="GRADE").plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 2, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "beach_001_GRADE.mp4"

    def test_multiple_videos_same_image(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "sunset.png")
        v1 = _touch(tmp_path / "src" / "a.mp4")
        v2 = _touch(tmp_path / "src" / "b.mkv")
        v3 = _touch(tmp_path / "src" / "c.avi")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v1, "distance": 1, "algorithm": "phash"},
            {"image": img, "video": v2, "distance": 3, "algorithm": "phash"},
            {"image": img, "video": v3, "distance": 2, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        video_names = [Path(e["destination"]).name for e in plan]
        assert video_names == [
            "sunset_001_V.mp4",
            "sunset_002_V.avi",
            "sunset_003_V.mkv",
        ]

    def test_videos_sorted_by_distance(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_far = _touch(tmp_path / "src" / "far.mp4")
        v_close = _touch(tmp_path / "src" / "close.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_far, "distance": 4, "algorithm": "phash"},
            {"image": img, "video": v_close, "distance": 1, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        assert Path(plan[0]["source"]).name == "close.mp4"
        assert Path(plan[0]["destination"]).name == "photo_001_V.mp4"
        assert Path(plan[1]["source"]).name == "far.mp4"
        assert Path(plan[1]["destination"]).name == "photo_002_V.mp4"

    def test_distance_tiebreaker_is_filename(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_b = _touch(tmp_path / "src" / "beta.mp4")
        v_a = _touch(tmp_path / "src" / "alpha.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_b, "distance": 2, "algorithm": "phash"},
            {"image": img, "video": v_a, "distance": 2, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        assert Path(plan[0]["source"]).name == "alpha.mp4"
        assert Path(plan[1]["source"]).name == "beta.mp4"

    def test_multiple_image_groups(self, tmp_path: Path) -> None:
        img1 = _touch(tmp_path / "src" / "cat.jpg")
        img2 = _touch(tmp_path / "src" / "dog.png")
        v1 = _touch(tmp_path / "src" / "clip1.mp4")
        v2 = _touch(tmp_path / "src" / "clip2.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img1, "video": v1, "distance": 1, "algorithm": "phash"},
            {"image": img2, "video": v2, "distance": 0, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        dest_names = [Path(e["destination"]).name for e in plan]
        assert "cat_001_V.mp4" in dest_names
        assert "dog_001_V.mp4" in dest_names

    def test_video_extension_preserved(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_mkv = _touch(tmp_path / "src" / "clip.mkv")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_mkv, "distance": 1, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        assert Path(plan[0]["destination"]).suffix == ".mkv"

    def test_empty_pairs_produces_empty_plan(self, tmp_path: Path) -> None:
        plan = MediaFileRenamer(output_dir=tmp_path, suffix="V").plan_renames(
            PairingResult()
        )
        assert plan == []

    def test_same_image_name_collision(self, tmp_path: Path) -> None:
        img_a = _touch(tmp_path / "folder_a" / "beach.jpg")
        img_b = _touch(tmp_path / "folder_b" / "beach.jpg")
        v1 = _touch(tmp_path / "src" / "clip1.mp4")
        v2 = _touch(tmp_path / "src" / "clip2.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img_a, "video": v1, "distance": 1, "algorithm": "phash"},
            {"image": img_b, "video": v2, "distance": 2, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        dest_names = [Path(e["destination"]).name for e in plan]
        assert "beach_001_V.mp4" in dest_names
        assert "beach_(2)_001_V.mp4" in dest_names

    def test_image_stem_with_dots(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "my.photo.beach.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        assert Path(plan[0]["destination"]).name == "my.photo.beach_001_V.mp4"


# ------------------------------------------------------------------
# strip_image_suffix tests
# ------------------------------------------------------------------


class TestStripImageSuffix:
    def test_strip_suffix(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "SPT25_SC38_002_S.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(
            output_dir=out, suffix="V", strip_image_suffix="_S"
        ).plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "SPT25_SC38_002_001_V.mp4"

    def test_no_strip(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "SPT25_SC38_002_S.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "SPT25_SC38_002_S_001_V.mp4"

    def test_strip_suffix_not_at_end(self, tmp_path: Path) -> None:
        """If the stem doesn't end with the strip suffix, it's kept as-is."""
        img = _touch(tmp_path / "src" / "SPT25_SC38_002.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(
            output_dir=out, suffix="V", strip_image_suffix="_S"
        ).plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "SPT25_SC38_002_001_V.mp4"


# ------------------------------------------------------------------
# seq_padding tests
# ------------------------------------------------------------------


class TestSeqPadding:
    def test_custom_padding(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "SPT25_SC38_002.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(
            output_dir=out, suffix="V", seq_padding=6
        ).plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "SPT25_SC38_002_000001_V.mp4"

    def test_default_padding_is_3(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "photo_001_V.mp4"


# ------------------------------------------------------------------
# Triage ordering tests
# ------------------------------------------------------------------


class TestTriageOrdering:
    def test_yes_before_maybe(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_yes1 = _touch(tmp_path / "src" / "y1.mp4")
        v_yes2 = _touch(tmp_path / "src" / "y2.mp4")
        v_yes3 = _touch(tmp_path / "src" / "y3.mp4")
        v_maybe1 = _touch(tmp_path / "src" / "m1.mp4")
        v_maybe2 = _touch(tmp_path / "src" / "m2.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_maybe1, "distance": 1, "algorithm": "phash"},
            {"image": img, "video": v_yes1, "distance": 3, "algorithm": "phash"},
            {"image": img, "video": v_yes2, "distance": 2, "algorithm": "phash"},
            {"image": img, "video": v_maybe2, "distance": 0, "algorithm": "phash"},
            {"image": img, "video": v_yes3, "distance": 1, "algorithm": "phash"},
        ]
        triage = {
            v_yes1: "yes", v_yes2: "yes", v_yes3: "yes",
            v_maybe1: "maybe", v_maybe2: "maybe",
        }
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs), triage_map=triage
        )

        names = [Path(e["destination"]).name for e in plan]
        # YES clips get 001-003, MAYBE get 004-005
        assert names == [
            "photo_001_V.mp4",  # y3 (yes, dist 1)
            "photo_002_V.mp4",  # y2 (yes, dist 2)
            "photo_003_V.mp4",  # y1 (yes, dist 3)
            "photo_004_V.mp4",  # m2 (maybe, dist 0)
            "photo_005_V.mp4",  # m1 (maybe, dist 1)
        ]
        # Verify sources are in the right order
        sources = [Path(e["source"]).name for e in plan]
        assert sources == ["y3.mp4", "y2.mp4", "y1.mp4", "m2.mp4", "m1.mp4"]

    def test_all_yes(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v1 = _touch(tmp_path / "src" / "a.mp4")
        v2 = _touch(tmp_path / "src" / "b.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v1, "distance": 2, "algorithm": "phash"},
            {"image": img, "video": v2, "distance": 1, "algorithm": "phash"},
        ]
        triage = {v1: "yes", v2: "yes"}
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs), triage_map=triage
        )

        names = [Path(e["destination"]).name for e in plan]
        assert names == ["photo_001_V.mp4", "photo_002_V.mp4"]

    def test_all_maybe(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v1 = _touch(tmp_path / "src" / "a.mp4")
        v2 = _touch(tmp_path / "src" / "b.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v1, "distance": 2, "algorithm": "phash"},
            {"image": img, "video": v2, "distance": 1, "algorithm": "phash"},
        ]
        triage = {v1: "maybe", v2: "maybe"}
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs), triage_map=triage
        )

        names = [Path(e["destination"]).name for e in plan]
        assert names == ["photo_001_V.mp4", "photo_002_V.mp4"]

    def test_no_triage_map_falls_back_to_distance(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v1 = _touch(tmp_path / "src" / "a.mp4")
        v2 = _touch(tmp_path / "src" / "b.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v1, "distance": 3, "algorithm": "phash"},
            {"image": img, "video": v2, "distance": 1, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        sources = [Path(e["source"]).name for e in plan]
        assert sources == ["b.mp4", "a.mp4"]  # best distance first

    def test_yes_with_worse_distance_before_maybe_with_better(
        self, tmp_path: Path
    ) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_yes = _touch(tmp_path / "src" / "yes_clip.mp4")
        v_maybe = _touch(tmp_path / "src" / "maybe_clip.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_yes, "distance": 10, "algorithm": "phash"},
            {"image": img, "video": v_maybe, "distance": 1, "algorithm": "phash"},
        ]
        triage = {v_yes: "yes", v_maybe: "maybe"}
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs), triage_map=triage
        )

        sources = [Path(e["source"]).name for e in plan]
        assert sources[0] == "yes_clip.mp4"
        assert sources[1] == "maybe_clip.mp4"


# ------------------------------------------------------------------
# build_triage_map tests
# ------------------------------------------------------------------


class TestBuildTriageMap:
    def test_detects_yes_folder(self) -> None:
        paths = ["/root/YES/clip1.mp4", "/root/yes/clip2.mp4"]
        result = build_triage_map(paths)
        assert result[paths[0]] == "yes"
        assert result[paths[1]] == "yes"

    def test_detects_maybe_folder(self) -> None:
        paths = ["/root/MAYBE/clip1.mp4", "/root/Maybe/clip2.mp4"]
        result = build_triage_map(paths)
        assert result[paths[0]] == "maybe"
        assert result[paths[1]] == "maybe"

    def test_unknown_for_other_paths(self) -> None:
        paths = ["/root/other/clip.mp4"]
        result = build_triage_map(paths)
        assert result[paths[0]] == "unknown"

    def test_backslash_paths(self) -> None:
        paths = ["C:\\Users\\data\\YES\\clip.mp4", "C:\\Users\\data\\MAYBE\\clip.mp4"]
        result = build_triage_map(paths)
        assert result[paths[0]] == "yes"
        assert result[paths[1]] == "maybe"


# ------------------------------------------------------------------
# scan_existing_sequences tests
# ------------------------------------------------------------------


class TestScanExistingSequences:
    def test_empty_output_folder(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        assert renamer.scan_existing_sequences() == {}

    def test_nonexistent_folder(self, tmp_path: Path) -> None:
        out = tmp_path / "nonexistent"
        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        assert renamer.scan_existing_sequences() == {}

    def test_finds_highest_sequence(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "SPT25_SC38_002_001_V.mp4")
        _touch(out / "SPT25_SC38_002_002_V.mp4")
        _touch(out / "SPT25_SC38_002_003_V.mp4")

        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        existing = renamer.scan_existing_sequences()
        assert existing == {"SPT25_SC38_002": 3}

    def test_independent_stems(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "cat_001_V.mp4")
        _touch(out / "cat_002_V.mp4")
        _touch(out / "dog_001_V.mp4")

        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        existing = renamer.scan_existing_sequences()
        assert existing == {"cat": 2, "dog": 1}

    def test_different_suffix_ignored(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "photo_001_GRADE.mp4")
        _touch(out / "photo_002_GRADE.mp4")

        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        existing = renamer.scan_existing_sequences()
        assert existing == {}

    def test_varied_padding_parsed(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "photo_01_V.mp4")
        _touch(out / "photo_002_V.mp4")

        renamer = MediaFileRenamer(output_dir=out, suffix="V")
        existing = renamer.scan_existing_sequences()
        assert existing == {"photo": 2}


# ------------------------------------------------------------------
# Output folder scan integration
# ------------------------------------------------------------------


class TestOutputFolderContinuation:
    def test_continues_numbering(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "photo_001_V.mp4")
        _touch(out / "photo_002_V.mp4")
        _touch(out / "photo_003_V.mp4")

        img = _touch(tmp_path / "src" / "photo.jpg")
        vid1 = _touch(tmp_path / "src" / "new1.mp4")
        vid2 = _touch(tmp_path / "src" / "new2.mp4")

        pairs = [
            {"image": img, "video": vid1, "distance": 1, "algorithm": "phash"},
            {"image": img, "video": vid2, "distance": 2, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        names = [Path(e["destination"]).name for e in plan]
        assert names == ["photo_004_V.mp4", "photo_005_V.mp4"]

    def test_independent_stem_offsets(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _touch(out / "cat_001_V.mp4")
        _touch(out / "cat_002_V.mp4")
        _touch(out / "dog_001_V.mp4")

        img_cat = _touch(tmp_path / "src" / "cat.jpg")
        img_dog = _touch(tmp_path / "src" / "dog.jpg")
        v1 = _touch(tmp_path / "src" / "clip1.mp4")
        v2 = _touch(tmp_path / "src" / "clip2.mp4")

        pairs = [
            {"image": img_cat, "video": v1, "distance": 1, "algorithm": "phash"},
            {"image": img_dog, "video": v2, "distance": 1, "algorithm": "phash"},
        ]
        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs(pairs)
        )

        dest_names = {Path(e["destination"]).name for e in plan}
        assert "cat_003_V.mp4" in dest_names
        assert "dog_002_V.mp4" in dest_names

    def test_no_existing_starts_at_001(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")

        plan = MediaFileRenamer(output_dir=out, suffix="V").plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "photo_001_V.mp4"

    def test_strip_suffix_with_continuation(self, tmp_path: Path) -> None:
        """Strip suffix + output scan work together."""
        out = tmp_path / "out"
        _touch(out / "SPT25_SC38_002_001_V.mp4")
        _touch(out / "SPT25_SC38_002_002_V.mp4")

        img = _touch(tmp_path / "src" / "SPT25_SC38_002_S.jpg")
        vid = _touch(tmp_path / "src" / "new_clip.mp4")

        plan = MediaFileRenamer(
            output_dir=out, suffix="V", strip_image_suffix="_S"
        ).plan_renames(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert Path(plan[0]["destination"]).name == "SPT25_SC38_002_003_V.mp4"


# ------------------------------------------------------------------
# execute tests
# ------------------------------------------------------------------


class TestExecute:
    def test_video_copied_to_output(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg", b"image data")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"video data")
        out = tmp_path / "out"

        result = MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 2, "algorithm": "phash"},
            ])
        )

        assert len(result.copied_files) == 1
        assert not (out / "photo.jpg").exists()  # image NOT copied
        assert (out / "photo_001_V.mp4").exists()
        assert (out / "photo_001_V.mp4").read_bytes() == b"video data"

    def test_originals_untouched(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg", b"original")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"original video")
        out = tmp_path / "out"

        MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 0, "algorithm": "phash"},
            ])
        )

        assert Path(img).exists()
        assert Path(vid).exists()
        assert Path(img).read_bytes() == b"original"
        assert Path(vid).read_bytes() == b"original video"

    def test_output_dir_created(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "deep" / "nested" / "output"

        MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert out.exists()
        assert (out / "photo_001_V.mp4").exists()

    def test_skip_existing_when_overwrite_false(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"new video")
        out = tmp_path / "out"
        _touch(out / "photo_001_V.mp4", b"old video")

        result = MediaFileRenamer(output_dir=out, suffix="V", overwrite=False).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        # With scan_existing_sequences, the renamer sees _001 exists and
        # numbers the new file as _002 instead — so no skip happens.
        assert len(result.copied_files) == 1
        assert (out / "photo_002_V.mp4").exists()
        assert (out / "photo_001_V.mp4").read_bytes() == b"old video"

    def test_overwrite_existing_when_overwrite_true(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"new video")
        out = tmp_path / "out"
        _touch(out / "photo_001_V.mp4", b"old video")

        result = MediaFileRenamer(output_dir=out, suffix="V", overwrite=True).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        # With scan, new file goes to _002 (not overwriting _001)
        assert len(result.copied_files) == 1
        assert (out / "photo_002_V.mp4").exists()

    def test_missing_source_produces_error(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        result = MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs([
                {
                    "image": "/nonexistent/photo.jpg",
                    "video": "/nonexistent/clip.mp4",
                    "distance": 1,
                    "algorithm": "phash",
                },
            ])
        )

        assert len(result.errors) == 1  # only video, no image copy
        assert len(result.copied_files) == 0

    def test_stats_populated(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        result = MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert result.stats["total_copied"] == 1
        assert result.stats["total_skipped"] == 0
        assert result.stats["total_errors"] == 0
        assert "time_elapsed" in result.stats

    def test_empty_pairs_no_crash(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        result = MediaFileRenamer(output_dir=out, suffix="V").execute(PairingResult())
        assert result.copied_files == []
        assert result.stats["total_copied"] == 0

    def test_execute_with_triage_map(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        v_yes = _touch(tmp_path / "src" / "yes.mp4", b"yes data")
        v_maybe = _touch(tmp_path / "src" / "maybe.mp4", b"maybe data")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v_maybe, "distance": 1, "algorithm": "phash"},
            {"image": img, "video": v_yes, "distance": 2, "algorithm": "phash"},
        ]
        triage = {v_yes: "yes", v_maybe: "maybe"}
        result = MediaFileRenamer(output_dir=out, suffix="V").execute(
            _result_with_pairs(pairs), triage_map=triage
        )

        assert len(result.copied_files) == 2
        # YES clip gets _001, MAYBE clip gets _002
        assert (out / "photo_001_V.mp4").read_bytes() == b"yes data"
        assert (out / "photo_002_V.mp4").read_bytes() == b"maybe data"


# ------------------------------------------------------------------
# dry_run tests
# ------------------------------------------------------------------


class TestDryRun:
    def test_no_files_created(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        MediaFileRenamer(output_dir=out, suffix="V", dry_run=True).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert not out.exists()

    def test_returns_planned_operations(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4")
        out = tmp_path / "out"

        result = MediaFileRenamer(output_dir=out, suffix="V", dry_run=True).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert len(result.copied_files) == 1
        assert result.stats["total_copied"] == 1

    def test_dry_run_respects_triage_and_strip(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "SPT25_S.jpg")
        v1 = _touch(tmp_path / "src" / "yes.mp4")
        v2 = _touch(tmp_path / "src" / "maybe.mp4")
        out = tmp_path / "out"

        pairs = [
            {"image": img, "video": v2, "distance": 1, "algorithm": "phash"},
            {"image": img, "video": v1, "distance": 2, "algorithm": "phash"},
        ]
        triage = {v1: "yes", v2: "maybe"}
        result = MediaFileRenamer(
            output_dir=out, suffix="V", dry_run=True, strip_image_suffix="_S"
        ).execute(_result_with_pairs(pairs), triage_map=triage)

        names = [Path(e["destination"]).name for e in result.copied_files]
        assert names == ["SPT25_001_V.mp4", "SPT25_002_V.mp4"]


# ------------------------------------------------------------------
# RenameResult dataclass
# ------------------------------------------------------------------


class TestRenameResult:
    def test_defaults(self) -> None:
        r = RenameResult()
        assert r.copied_files == []
        assert r.skipped_files == []
        assert r.errors == []
        assert r.stats == {}
