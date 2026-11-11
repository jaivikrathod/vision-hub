import pytest

from app.core.exceptions import AppError, UnsupportedFormatError
from app.core.security import (
    resolve_managed_path,
    sanitize_display_name,
    sniff_container,
    validate_content,
    validate_extension,
)


def test_extension_validation():
    assert validate_extension("clip.MP4") == ".mp4"
    with pytest.raises(UnsupportedFormatError):
        validate_extension("malware.exe")
    with pytest.raises(UnsupportedFormatError):
        validate_extension("noext")


def test_container_sniffing():
    assert sniff_container(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8) == "mp4"
    assert sniff_container(b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8) == "mov"
    assert sniff_container(b"RIFF\x00\x00\x00\x00AVI LIST") == "avi"
    assert sniff_container(b"\x1a\x45\xdf\xa3\x00\x00") == "mkv"
    assert sniff_container(b"hello world, not a video") is None
    with pytest.raises(UnsupportedFormatError):
        validate_content(".avi", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8)


def test_display_name_sanitized():
    assert sanitize_display_name("../../etc/passwd") == "passwd"
    assert sanitize_display_name('we"ird<name>.mp4') == "we_ird_name_.mp4"


def test_path_confinement():
    with pytest.raises(AppError):
        resolve_managed_path("/etc/passwd")
    with pytest.raises(AppError):
        resolve_managed_path("uploads/../../../etc/passwd")
