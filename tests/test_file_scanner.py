"""Tests for the file scanner module."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_pairing.file_scanner import ScanResult, scan_directory


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def media_tree(tmp_path: Path) -> Path:
    """Create a directory tree with mixed media and non-media files."""
    # Top-level files
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8fake")
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x00fake")
    (tmp_path / "readme.txt").write_text("hello")

    # Subdirectory with more files
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep.png").write_bytes(b"\x89PNGfake")
    (sub / "deep.mov").write_bytes(b"\x00\x00fake")
    (sub / "notes.md").write_text("notes")

    return tmp_path


# ------------------------------------------------------------------
# scan_directory tests
# ------------------------------------------------------------------


class TestScanDirectory:
    def test_recursive_finds_all_media(self, media_tree: Path) -> None:
        result = scan_directory(media_tree, recursive=True)
        assert isinstance(result, ScanResult)
        assert len(result.image_paths) == 2  # photo.jpg + deep.png
        assert len(result.video_paths) == 2  # clip.mp4 + deep.mov

    def test_non_recursive_finds_top_level_only(self, media_tree: Path) -> None:
        result = scan_directory(media_tree, recursive=False)
        assert len(result.image_paths) == 1  # photo.jpg only
        assert len(result.video_paths) == 1  # clip.mp4 only

    def test_non_media_files_skipped(self, media_tree: Path) -> None:
        result = scan_directory(media_tree, recursive=True)
        assert len(result.skipped) == 2  # readme.txt + notes.md

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = scan_directory(tmp_path)
        assert result.image_paths == []
        assert result.video_paths == []
        assert result.skipped == []

    def test_nonexistent_directory_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            scan_directory("/nonexistent/path/xyz")

    def test_file_instead_of_directory_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "a_file.txt"
        f.write_text("hi")
        with pytest.raises(NotADirectoryError):
            scan_directory(f)

    def test_stats_populated(self, media_tree: Path) -> None:
        result = scan_directory(media_tree, recursive=True)
        assert result.stats["root"] == str(media_tree)
        assert result.stats["recursive"] is True
        assert result.stats["images_found"] == 2
        assert result.stats["videos_found"] == 2
        assert result.stats["skipped"] == 2
        assert "time_elapsed" in result.stats

    def test_paths_are_absolute_strings(self, media_tree: Path) -> None:
        result = scan_directory(media_tree)
        for p in result.image_paths + result.video_paths:
            assert isinstance(p, str)
            assert Path(p).is_absolute()

    def test_all_image_extensions_detected(self, tmp_path: Path) -> None:
        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"):
            (tmp_path / f"img{ext}").write_bytes(b"fake")
        result = scan_directory(tmp_path)
        assert len(result.image_paths) == 7

    def test_all_video_extensions_detected(self, tmp_path: Path) -> None:
        for ext in (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"):
            (tmp_path / f"vid{ext}").write_bytes(b"fake")
        result = scan_directory(tmp_path)
        assert len(result.video_paths) == 8

    def test_case_insensitive_extensions(self, tmp_path: Path) -> None:
        (tmp_path / "photo.JPG").write_bytes(b"fake")
        (tmp_path / "clip.MP4").write_bytes(b"fake")
        result = scan_directory(tmp_path)
        assert len(result.image_paths) == 1
        assert len(result.video_paths) == 1

    def test_results_sorted_deterministically(self, media_tree: Path) -> None:
        r1 = scan_directory(media_tree, recursive=True)
        r2 = scan_directory(media_tree, recursive=True)
        assert r1.image_paths == r2.image_paths
        assert r1.video_paths == r2.video_paths


# ------------------------------------------------------------------
# ScanResult dataclass
# ------------------------------------------------------------------


class TestScanResult:
    def test_defaults(self) -> None:
        r = ScanResult()
        assert r.image_paths == []
        assert r.video_paths == []
        assert r.skipped == []
        assert r.stats == {}
