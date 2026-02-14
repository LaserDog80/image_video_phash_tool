"""Tests for the file renamer module."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_pairing.file_renamer import MediaFileRenamer, RenameResult
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


# ------------------------------------------------------------------
# plan_renames tests
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
        assert Path(plan[0]["destination"]).name == "beach_V_001.mp4"

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

        assert Path(plan[0]["destination"]).name == "beach_GRADE_001.mp4"

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
            "sunset_V_001.mp4",
            "sunset_V_002.avi",
            "sunset_V_003.mkv",
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
        assert Path(plan[0]["destination"]).name == "photo_V_001.mp4"
        assert Path(plan[1]["source"]).name == "far.mp4"
        assert Path(plan[1]["destination"]).name == "photo_V_002.mp4"

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
        assert "cat_V_001.mp4" in dest_names
        assert "dog_V_001.mp4" in dest_names

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
        assert "beach_V_001.mp4" in dest_names
        assert "beach_(2)_V_001.mp4" in dest_names

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

        assert Path(plan[0]["destination"]).name == "my.photo.beach_V_001.mp4"


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
        assert (out / "photo_V_001.mp4").exists()
        assert (out / "photo_V_001.mp4").read_bytes() == b"video data"

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
        assert (out / "photo_V_001.mp4").exists()

    def test_skip_existing_when_overwrite_false(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"new video")
        out = tmp_path / "out"
        _touch(out / "photo_V_001.mp4", b"old video")

        result = MediaFileRenamer(output_dir=out, suffix="V", overwrite=False).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert len(result.skipped_files) == 1
        assert len(result.copied_files) == 0
        assert (out / "photo_V_001.mp4").read_bytes() == b"old video"

    def test_overwrite_existing_when_overwrite_true(self, tmp_path: Path) -> None:
        img = _touch(tmp_path / "src" / "photo.jpg")
        vid = _touch(tmp_path / "src" / "clip.mp4", b"new video")
        out = tmp_path / "out"
        _touch(out / "photo_V_001.mp4", b"old video")

        result = MediaFileRenamer(output_dir=out, suffix="V", overwrite=True).execute(
            _result_with_pairs([
                {"image": img, "video": vid, "distance": 1, "algorithm": "phash"},
            ])
        )

        assert len(result.copied_files) == 1
        assert (out / "photo_V_001.mp4").read_bytes() == b"new video"

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
