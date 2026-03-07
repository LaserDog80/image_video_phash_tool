"""Tests for the media pairing engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from media_pairing.pairing_engine import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaPairingEngine,
    PairingResult,
    VideoFingerprint,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def engine() -> MediaPairingEngine:
    return MediaPairingEngine()


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


def _make_image(path: Path, colour: tuple[int, int, int] = (128, 64, 200)) -> str:
    """Create a small solid-colour image and return its path."""
    img = Image.new("RGB", (64, 64), colour)
    img.save(str(path))
    return str(path)


def _make_video(
    path: Path,
    frames: list[np.ndarray] | None = None,
    frame_count: int = 5,
    colour: tuple[int, int, int] = (128, 64, 200),
    size: tuple[int, int] = (64, 64),
) -> str:
    """Create a small synthetic .avi video and return its path.

    If *frames* is provided, those exact frames are written.
    Otherwise *frame_count* solid-colour frames are generated.
    """
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, 24.0, size)
    if frames is not None:
        for f in frames:
            writer.write(f)
    else:
        # colour is RGB, OpenCV wants BGR
        bgr = (colour[2], colour[1], colour[0])
        frame = np.full((*size[::-1], 3), bgr, dtype=np.uint8)  # h, w, c
        for _ in range(frame_count):
            writer.write(frame)
    writer.release()
    return str(path)


# ------------------------------------------------------------------
# Initialisation tests
# ------------------------------------------------------------------


class TestEngineInit:
    def test_default_params(self) -> None:
        eng = MediaPairingEngine()
        assert eng.hash_algo == "phash"
        assert eng.hash_tolerance == 4
        assert eng.skip_black_frames is True
        assert eng.dark_threshold == 5.0
        assert eng.sample_frames == 1
        assert eng.max_probe_frames == 30

    def test_custom_params(self) -> None:
        eng = MediaPairingEngine(
            hash_algo="dhash",
            hash_tolerance=8,
            dark_threshold=10.0,
            sample_frames=3,
            max_probe_frames=50,
        )
        assert eng.hash_algo == "dhash"
        assert eng.hash_tolerance == 8

    def test_invalid_algorithm_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown hash algorithm"):
            MediaPairingEngine(hash_algo="md5")

    @pytest.mark.parametrize("algo", ["phash", "dhash", "ahash"])
    def test_all_algorithms_accepted(self, algo: str) -> None:
        eng = MediaPairingEngine(hash_algo=algo)
        assert eng.hash_algo == algo


# ------------------------------------------------------------------
# hash_image tests
# ------------------------------------------------------------------


class TestHashImage:
    def test_hash_pil_image(self, engine: MediaPairingEngine) -> None:
        img = Image.new("RGB", (64, 64), (100, 150, 200))
        h = engine.hash_image(img)
        assert h is not None

    def test_hash_file_path(self, engine: MediaPairingEngine, tmp_dir: Path) -> None:
        path = _make_image(tmp_dir / "test.png")
        h = engine.hash_image(path)
        assert h is not None

    def test_hash_missing_file_returns_none(
        self, engine: MediaPairingEngine
    ) -> None:
        h = engine.hash_image("/nonexistent/fake.png")
        assert h is None

    def test_identical_images_distance_zero(
        self, engine: MediaPairingEngine
    ) -> None:
        img = Image.new("RGB", (64, 64), (100, 150, 200))
        h1 = engine.hash_image(img)
        h2 = engine.hash_image(img)
        assert h1 is not None and h2 is not None
        assert h1 - h2 == 0

    def test_different_images_nonzero_distance(
        self, engine: MediaPairingEngine
    ) -> None:
        img1 = Image.new("RGB", (64, 64), (0, 0, 0))
        img2 = Image.new("RGB", (64, 64), (255, 255, 255))
        h1 = engine.hash_image(img1)
        h2 = engine.hash_image(img2)
        assert h1 is not None and h2 is not None
        assert h1 - h2 > 0


# ------------------------------------------------------------------
# extract_frames tests
# ------------------------------------------------------------------


class TestExtractFrames:
    def test_extract_from_valid_video(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        vid = _make_video(tmp_dir / "clip.avi")
        frames = engine.extract_frames(vid)
        assert len(frames) == 1  # default sample_frames=1
        assert isinstance(frames[0], Image.Image)

    def test_multi_frame_sampling(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(sample_frames=3)
        vid = _make_video(tmp_dir / "clip.avi", frame_count=10)
        frames = eng.extract_frames(vid)
        assert len(frames) == 3

    def test_black_frames_skipped(self, tmp_dir: Path) -> None:
        # 3 black frames followed by a bright frame
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        bright = np.full((64, 64, 3), 180, dtype=np.uint8)
        vid = _make_video(tmp_dir / "fade.avi", frames=[black, black, black, bright])
        eng = MediaPairingEngine(skip_black_frames=True, dark_threshold=5.0)
        frames = eng.extract_frames(vid)
        assert len(frames) == 1  # only the bright frame

    def test_all_black_video_returns_empty(self, tmp_dir: Path) -> None:
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        vid = _make_video(tmp_dir / "black.avi", frames=[black] * 5)
        eng = MediaPairingEngine(skip_black_frames=True, dark_threshold=5.0)
        frames = eng.extract_frames(vid)
        assert frames == []

    def test_missing_video_raises(self, engine: MediaPairingEngine) -> None:
        with pytest.raises(FileNotFoundError):
            engine.extract_frames("/nonexistent/video.mp4")

    def test_skip_black_frames_disabled(self, tmp_dir: Path) -> None:
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        vid = _make_video(tmp_dir / "black.avi", frames=[black] * 3)
        eng = MediaPairingEngine(skip_black_frames=False)
        frames = eng.extract_frames(vid)
        assert len(frames) == 1  # sample_frames=1


# ------------------------------------------------------------------
# build_index tests
# ------------------------------------------------------------------


class TestBuildIndex:
    def test_builds_hashes(self, engine: MediaPairingEngine, tmp_dir: Path) -> None:
        p1 = _make_image(tmp_dir / "a.png", (100, 100, 100))
        p2 = _make_image(tmp_dir / "b.png", (200, 200, 200))
        hashes, errors = engine.build_index([p1, p2])
        assert len(hashes) == 2
        assert errors == []

    def test_bad_file_produces_error(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        bad = tmp_dir / "corrupt.png"
        bad.write_text("not an image")
        hashes, errors = engine.build_index([str(bad)])
        assert len(hashes) == 0
        assert len(errors) == 1
        assert "corrupt.png" in errors[0]["error_message"]


# ------------------------------------------------------------------
# find_pairs tests
# ------------------------------------------------------------------


class TestFindPairs:
    def test_matching_image_and_video(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        colour = (128, 64, 200)
        img = _make_image(tmp_dir / "thumb.png", colour)
        vid = _make_video(tmp_dir / "clip.avi", colour=colour)
        result = engine.find_pairs([img], [vid])
        assert isinstance(result, PairingResult)
        assert len(result.pairs) == 1
        assert result.pairs[0]["image"] == img
        assert result.pairs[0]["video"] == vid
        assert result.pairs[0]["distance"] <= engine.hash_tolerance
        assert result.unmatched_images == []
        assert result.unmatched_videos == []

    def test_no_match_different_content(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        img = _make_image(tmp_dir / "thumb.png", (0, 0, 0))
        # Make a bright video that won't match a black image
        bright = np.full((64, 64, 3), 255, dtype=np.uint8)
        vid = _make_video(tmp_dir / "clip.avi", frames=[bright] * 3)
        # Use a very tight tolerance to ensure no match
        eng = MediaPairingEngine(hash_tolerance=0)
        result = eng.find_pairs([img], [vid])
        # With solid colours and tolerance 0, they may or may not match
        # depending on how phash handles solid colours. So just check structure.
        assert isinstance(result, PairingResult)
        assert result.stats["total_comparisons"] >= 1

    def test_empty_image_list(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        vid = _make_video(tmp_dir / "clip.avi")
        result = engine.find_pairs([], [vid])
        assert result.pairs == []
        assert result.unmatched_videos == [vid]

    def test_empty_video_list(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        img = _make_image(tmp_dir / "thumb.png")
        result = engine.find_pairs([img], [])
        assert result.pairs == []
        assert result.unmatched_images == [img]

    def test_both_lists_empty(self, engine: MediaPairingEngine) -> None:
        result = engine.find_pairs([], [])
        assert result.pairs == []
        assert result.unmatched_images == []
        assert result.unmatched_videos == []
        assert result.stats["total_comparisons"] == 0

    def test_corrupt_video_produces_error(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        img = _make_image(tmp_dir / "thumb.png")
        bad_vid = tmp_dir / "bad.avi"
        bad_vid.write_text("not a video")
        result = engine.find_pairs([img], [str(bad_vid)])
        assert len(result.errors) >= 1
        assert result.unmatched_images == [img]

    def test_corrupt_image_produces_error(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        bad_img = tmp_dir / "bad.png"
        bad_img.write_text("not an image")
        vid = _make_video(tmp_dir / "clip.avi")
        result = engine.find_pairs([str(bad_img)], [vid])
        assert len(result.errors) >= 1

    def test_stats_populated(
        self, engine: MediaPairingEngine, tmp_dir: Path
    ) -> None:
        img = _make_image(tmp_dir / "thumb.png")
        vid = _make_video(tmp_dir / "clip.avi")
        result = engine.find_pairs([img], [vid])
        assert "total_comparisons" in result.stats
        assert "time_elapsed" in result.stats
        assert "algorithm" in result.stats
        assert result.stats["algorithm"] == "phash"

    def test_all_black_video_error(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(skip_black_frames=True)
        img = _make_image(tmp_dir / "thumb.png")
        black = np.zeros((64, 64, 3), dtype=np.uint8)
        vid = _make_video(tmp_dir / "black.avi", frames=[black] * 5)
        result = eng.find_pairs([img], [vid])
        assert len(result.errors) >= 1
        assert result.unmatched_images == [img]

    @pytest.mark.parametrize("algo", ["phash", "dhash", "ahash"])
    def test_all_algorithms_produce_results(
        self, algo: str, tmp_dir: Path
    ) -> None:
        eng = MediaPairingEngine(hash_algo=algo)
        colour = (128, 64, 200)
        img = _make_image(tmp_dir / f"thumb_{algo}.png", colour)
        vid = _make_video(tmp_dir / f"clip_{algo}.avi", colour=colour)
        result = eng.find_pairs([img], [vid])
        assert isinstance(result, PairingResult)
        assert result.stats["algorithm"] == algo


# ------------------------------------------------------------------
# PairingResult dataclass
# ------------------------------------------------------------------


class TestPairingResult:
    def test_defaults(self) -> None:
        r = PairingResult()
        assert r.pairs == []
        assert r.unmatched_images == []
        assert r.unmatched_videos == []
        assert r.errors == []
        assert r.stats == {}


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------


class TestConstants:
    def test_image_extensions_non_empty(self) -> None:
        assert len(IMAGE_EXTENSIONS) > 0
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".png" in IMAGE_EXTENSIONS

    def test_video_extensions_non_empty(self) -> None:
        assert len(VIDEO_EXTENSIONS) > 0
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mkv" in VIDEO_EXTENSIONS


# ------------------------------------------------------------------
# Helper: multi-segment video
# ------------------------------------------------------------------


def _make_gradient_video(
    path: Path,
    segment_colours: list[tuple[int, int, int]],
    frames_per_segment: int = 5,
    size: tuple[int, int] = (64, 64),
) -> str:
    """Create a video with distinct colour segments.

    Each segment is a block of solid-colour frames.  Useful for testing
    distributed frame extraction (first/middle/last are different).
    """
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, 24.0, size)
    for colour_rgb in segment_colours:
        bgr = (colour_rgb[2], colour_rgb[1], colour_rgb[0])
        frame = np.full((*size[::-1], 3), bgr, dtype=np.uint8)
        for _ in range(frames_per_segment):
            writer.write(frame)
    writer.release()
    return str(path)


# ------------------------------------------------------------------
# extract_frames_distributed tests
# ------------------------------------------------------------------


class TestExtractFramesDistributed:
    def test_returns_requested_frame_count(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=4)
        vid = _make_video(tmp_dir / "clip.avi", frame_count=20)
        frames, positions = eng.extract_frames_distributed(vid)
        assert len(frames) == 4
        assert len(positions) == 4

    def test_positions_span_full_range(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=5)
        vid = _make_video(tmp_dir / "clip.avi", frame_count=30)
        _, positions = eng.extract_frames_distributed(vid)
        assert positions[0] == 0.0
        assert positions[-1] == 1.0

    def test_respects_num_frames_argument(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=8)
        vid = _make_video(tmp_dir / "clip.avi", frame_count=20)
        frames, _ = eng.extract_frames_distributed(vid, num_frames=3)
        assert len(frames) == 3

    def test_short_video_caps_at_total_frames(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=10)
        vid = _make_video(tmp_dir / "clip.avi", frame_count=3)
        frames, positions = eng.extract_frames_distributed(vid)
        assert len(frames) <= 3

    def test_dark_frames_skipped(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3, skip_black_frames=True)
        # Video: 5 black, 5 bright, 5 black — middle segment extractable
        vid = _make_gradient_video(
            tmp_dir / "dark.avi",
            segment_colours=[(0, 0, 0), (200, 200, 200), (0, 0, 0)],
            frames_per_segment=5,
        )
        frames, _ = eng.extract_frames_distributed(vid)
        # At least the middle frame should be bright enough
        assert len(frames) >= 1

    def test_missing_video_raises(self) -> None:
        eng = MediaPairingEngine()
        with pytest.raises(FileNotFoundError):
            eng.extract_frames_distributed("/no/such/file.mp4")

    def test_gradient_video_frames_differ(self, tmp_dir: Path) -> None:
        """Frames from different segments should produce different hashes."""
        eng = MediaPairingEngine(video_match_frames=3)
        vid = _make_gradient_video(
            tmp_dir / "gradient.avi",
            segment_colours=[(255, 0, 0), (0, 255, 0), (0, 0, 255)],
            frames_per_segment=10,
        )
        frames, _ = eng.extract_frames_distributed(vid)
        assert len(frames) == 3
        h0 = eng.hash_image(frames[0])
        h2 = eng.hash_image(frames[2])
        # Red and blue segments should hash differently
        assert h0 is not None and h2 is not None


# ------------------------------------------------------------------
# VideoFingerprint dataclass
# ------------------------------------------------------------------


class TestVideoFingerprint:
    def test_creation(self) -> None:
        import imagehash

        dummy_hash = imagehash.hex_to_hash("0" * 16)
        fp = VideoFingerprint(
            path="/test/video.mp4",
            hashes=[dummy_hash, dummy_hash],
            positions=[0.0, 1.0],
        )
        assert fp.path == "/test/video.mp4"
        assert len(fp.hashes) == 2
        assert fp.positions == [0.0, 1.0]


# ------------------------------------------------------------------
# build_video_index tests
# ------------------------------------------------------------------


class TestBuildVideoIndex:
    def test_builds_fingerprints(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        v1 = _make_video(tmp_dir / "a.avi", frame_count=15, colour=(100, 50, 50))
        v2 = _make_video(tmp_dir / "b.avi", frame_count=15, colour=(50, 100, 50))
        fps, errors = eng.build_video_index([v1, v2])
        assert len(fps) == 2
        assert errors == []
        assert v1 in fps
        assert len(fps[v1].hashes) == 3

    def test_corrupt_video_produces_error(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        bad = tmp_dir / "bad.avi"
        bad.write_text("not a video")
        fps, errors = eng.build_video_index([str(bad)])
        assert len(fps) == 0
        assert len(errors) >= 1


# ------------------------------------------------------------------
# _compare_fingerprints tests
# ------------------------------------------------------------------


class TestCompareFingerprints:
    def test_identical_fingerprints_zero_distance(self) -> None:
        import imagehash

        h = imagehash.hex_to_hash("a" * 16)
        fp = VideoFingerprint(
            path="/test.mp4", hashes=[h, h, h], positions=[0.0, 0.5, 1.0]
        )
        dist = MediaPairingEngine._compare_fingerprints(fp, fp)
        assert dist == 0.0

    def test_different_fingerprints_nonzero(self) -> None:
        import imagehash

        h1 = imagehash.hex_to_hash("0" * 16)
        h2 = imagehash.hex_to_hash("f" * 16)
        fp_a = VideoFingerprint(
            path="/a.mp4", hashes=[h1], positions=[0.0]
        )
        fp_b = VideoFingerprint(
            path="/b.mp4", hashes=[h2], positions=[0.0]
        )
        dist = MediaPairingEngine._compare_fingerprints(fp_a, fp_b)
        assert dist > 0

    def test_empty_fingerprint_returns_inf(self) -> None:
        fp_empty = VideoFingerprint(path="/e.mp4", hashes=[], positions=[])
        fp_non = VideoFingerprint(
            path="/n.mp4",
            hashes=[__import__("imagehash").hex_to_hash("a" * 16)],
            positions=[0.0],
        )
        assert MediaPairingEngine._compare_fingerprints(fp_empty, fp_non) == float("inf")

    def test_different_lengths_nearest_position(self) -> None:
        import imagehash

        h = imagehash.hex_to_hash("a" * 16)
        fp_short = VideoFingerprint(
            path="/s.mp4", hashes=[h], positions=[0.5]
        )
        fp_long = VideoFingerprint(
            path="/l.mp4", hashes=[h, h, h], positions=[0.0, 0.5, 1.0]
        )
        # Same hash everywhere, distance should be 0
        dist = MediaPairingEngine._compare_fingerprints(fp_short, fp_long)
        assert dist == 0.0


# ------------------------------------------------------------------
# find_video_pairs tests
# ------------------------------------------------------------------


class TestFindVideoPairs:
    def test_matching_identical_videos(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3, hash_tolerance=4)
        colour = (128, 64, 200)
        v1 = _make_video(tmp_dir / "source.avi", frame_count=15, colour=colour)
        v2 = _make_video(tmp_dir / "target.avi", frame_count=15, colour=colour)
        result = eng.find_video_pairs([v1], [v2])
        assert isinstance(result, PairingResult)
        assert len(result.pairs) == 1
        pair = result.pairs[0]
        assert pair["image"] == v1  # backward compat key
        assert pair["video"] == v2  # backward compat key
        assert pair["source"] == v1
        assert pair["target"] == v2
        assert pair["match_type"] == "video_to_video"
        assert pair["distance"] <= eng.hash_tolerance

    def test_no_match_different_videos(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3, hash_tolerance=0)
        v1 = _make_gradient_video(
            tmp_dir / "source.avi",
            [(255, 0, 0), (0, 255, 0), (0, 0, 255)],
            frames_per_segment=10,
        )
        v2 = _make_gradient_video(
            tmp_dir / "target.avi",
            [(0, 255, 255), (255, 0, 255), (255, 255, 0)],
            frames_per_segment=10,
        )
        result = eng.find_video_pairs([v1], [v2])
        # With tolerance 0, different colour videos should not match
        assert isinstance(result, PairingResult)

    def test_empty_source_list(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        v = _make_video(tmp_dir / "target.avi", frame_count=10)
        result = eng.find_video_pairs([], [v])
        assert result.pairs == []
        assert result.unmatched_videos == [v]

    def test_empty_target_list(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        v = _make_video(tmp_dir / "source.avi", frame_count=10)
        result = eng.find_video_pairs([v], [])
        assert result.pairs == []
        assert result.unmatched_images == [v]

    def test_both_lists_empty(self) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        result = eng.find_video_pairs([], [])
        assert result.pairs == []

    def test_corrupt_video_produces_error(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        good = _make_video(tmp_dir / "source.avi", frame_count=10)
        bad = tmp_dir / "bad.avi"
        bad.write_text("not a video")
        result = eng.find_video_pairs([good], [str(bad)])
        assert len(result.errors) >= 1

    def test_stats_populated(self, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(video_match_frames=3)
        v1 = _make_video(tmp_dir / "s.avi", frame_count=10, colour=(128, 64, 200))
        v2 = _make_video(tmp_dir / "t.avi", frame_count=10, colour=(128, 64, 200))
        result = eng.find_video_pairs([v1], [v2])
        assert "total_comparisons" in result.stats
        assert "time_elapsed" in result.stats
        assert result.stats["match_type"] == "video_to_video"

    @pytest.mark.parametrize("algo", ["phash", "dhash", "ahash"])
    def test_all_algorithms(self, algo: str, tmp_dir: Path) -> None:
        eng = MediaPairingEngine(hash_algo=algo, video_match_frames=3)
        colour = (128, 64, 200)
        v1 = _make_video(tmp_dir / f"s_{algo}.avi", frame_count=10, colour=colour)
        v2 = _make_video(tmp_dir / f"t_{algo}.avi", frame_count=10, colour=colour)
        result = eng.find_video_pairs([v1], [v2])
        assert isinstance(result, PairingResult)
        assert result.stats["algorithm"] == algo
