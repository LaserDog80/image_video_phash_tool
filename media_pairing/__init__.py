"""Media Pairing — match images to videos using perceptual hashing."""

from media_pairing.excel_export import export_rename_to_excel
from media_pairing.file_renamer import MediaFileRenamer, RenameResult
from media_pairing.file_scanner import ScanResult, scan_directory
from media_pairing.pairing_engine import (
    MediaPairingEngine,
    PairingResult,
    VideoFingerprint,
)

__all__ = [
    "MediaPairingEngine",
    "PairingResult",
    "VideoFingerprint",
    "MediaFileRenamer",
    "RenameResult",
    "ScanResult",
    "scan_directory",
    "export_rename_to_excel",
]
