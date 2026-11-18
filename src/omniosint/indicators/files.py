"""Classification of files by their content.

Only the first bytes are read. Nothing is parsed, opened or executed: that is
the work of the document and image modules (Phase 9) with their safety limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from omniosint.indicators.model import Candidate, candidate
from omniosint.indicators.types import IndicatorType

HEAD_BYTES = 4096


@dataclass(frozen=True, slots=True)
class FileKind:
    kind: IndicatorType
    format: str
    mime: str
    extensions: tuple[str, ...]


def _kind(kind: IndicatorType, fmt: str, mime: str, *extensions: str) -> FileKind:
    return FileKind(kind, fmt, mime, extensions)


_IMAGE = IndicatorType.IMAGE
_DOCUMENT = IndicatorType.DOCUMENT
_FILE = IndicatorType.FILE

_SIGNATURES: tuple[tuple[bytes, int, FileKind], ...] = (
    (b"\x89PNG\r\n\x1a\n", 0, _kind(_IMAGE, "PNG image", "image/png", "png")),
    (b"\xff\xd8\xff", 0, _kind(_IMAGE, "JPEG image", "image/jpeg", "jpg", "jpeg")),
    (b"GIF87a", 0, _kind(_IMAGE, "GIF image", "image/gif", "gif")),
    (b"GIF89a", 0, _kind(_IMAGE, "GIF image", "image/gif", "gif")),
    (b"BM", 0, _kind(_IMAGE, "BMP image", "image/bmp", "bmp")),
    (b"II*\x00", 0, _kind(_IMAGE, "TIFF image", "image/tiff", "tif", "tiff")),
    (b"MM\x00*", 0, _kind(_IMAGE, "TIFF image", "image/tiff", "tif", "tiff")),
    (b"\x00\x00\x01\x00", 0, _kind(_IMAGE, "Windows icon", "image/vnd.microsoft.icon", "ico")),
    (b"%PDF-", 0, _kind(_DOCUMENT, "PDF document", "application/pdf", "pdf")),
    (b"{\\rtf", 0, _kind(_DOCUMENT, "RTF document", "application/rtf", "rtf")),
    (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        0,
        _kind(
            _DOCUMENT,
            "Microsoft Office document (legacy format)",
            "application/x-ole-storage",
            "doc",
            "xls",
            "ppt",
            "msg",
        ),
    ),
    (
        b"MZ",
        0,
        _kind(
            _FILE,
            "Windows executable",
            "application/vnd.microsoft.portable-executable",
            "exe",
            "dll",
            "sys",
        ),
    ),
    (b"\x7fELF", 0, _kind(_FILE, "ELF executable", "application/x-elf", "so", "bin", "elf")),
    (b"\xcf\xfa\xed\xfe", 0, _kind(_FILE, "Mach-O executable", "application/x-mach-binary")),
    (
        b"\xca\xfe\xba\xbe",
        0,
        _kind(_FILE, "Mach-O universal binary or Java class", "application/octet-stream", "class"),
    ),
    (b"\x1f\x8b", 0, _kind(_FILE, "gzip archive", "application/gzip", "gz", "tgz")),
    (b"7z\xbc\xaf\x27\x1c", 0, _kind(_FILE, "7-Zip archive", "application/x-7z-compressed", "7z")),
    (b"Rar!\x1a\x07", 0, _kind(_FILE, "RAR archive", "application/vnd.rar", "rar")),
    (b"ustar", 257, _kind(_FILE, "tar archive", "application/x-tar", "tar")),
)
_ZIP_KIND = _kind(_FILE, "ZIP archive", "application/zip", "zip")
_ZIP_DOCUMENTS: tuple[tuple[bytes, FileKind], ...] = (
    (
        b"word/",
        _kind(
            _DOCUMENT,
            "Word document",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "docx",
        ),
    ),
    (
        b"xl/",
        _kind(
            _DOCUMENT,
            "Excel workbook",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        ),
    ),
    (
        b"ppt/",
        _kind(
            _DOCUMENT,
            "PowerPoint presentation",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "pptx",
        ),
    ),
    (
        b"mimetypeapplication/vnd.oasis.opendocument",
        _kind(
            _DOCUMENT,
            "OpenDocument file",
            "application/vnd.oasis.opendocument",
            "odt",
            "ods",
            "odp",
        ),
    ),
    (
        b"mimetypeapplication/epub+zip",
        _kind(_DOCUMENT, "EPUB book", "application/epub+zip", "epub"),
    ),
)
_TEXT_DOCUMENT_EXTENSIONS = ("txt", "md", "csv", "tsv", "json", "xml", "html", "htm", "log", "eml")
_SCRIPT_EXTENSIONS = (
    "ps1",
    "psm1",
    "bat",
    "cmd",
    "vbs",
    "vbe",
    "js",
    "jse",
    "wsf",
    "hta",
    "sh",
    "py",
    "pl",
    "rb",
    "php",
    "lnk",
)
_EXECUTABLE_NOTE = "Executable content. OmniOSINT never runs submitted files."


def _sniff(head: bytes) -> FileKind | None:
    for signature, offset, kind in _SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return kind
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypavif"):
        return _kind(_IMAGE, "HEIF/AVIF image", "image/heif", "heic", "avif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _kind(_IMAGE, "WebP image", "image/webp", "webp")
    if head[:4] == b"PK\x03\x04":
        compact = head.replace(b"\x00", b"")
        for marker, kind in _ZIP_DOCUMENTS:
            if marker in compact:
                return kind
        return _ZIP_KIND
    return None


def _looks_like_text(head: bytes) -> bool:
    if not head:
        return False
    if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        return True
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as error:
        # The sample may end in the middle of a character.
        if error.start < len(head) - 4:
            return False
    printable = sum(1 for byte in head if byte >= 32 or byte in (9, 10, 13))
    return printable / len(head) > 0.95


def classify_file_content(
    name: str | None, head: bytes, size: int | None = None, sha256: str | None = None
) -> list[Candidate]:
    extension = PurePath(name).suffix.lower().lstrip(".") if name else ""
    kind = _sniff(head)
    notes: list[str] = []
    if kind is None and _looks_like_text(head):
        text = head[:512].lstrip().lower()
        if text.startswith(b"<svg") or (b"<svg" in text and text.startswith(b"<?xml")):
            kind = _kind(_IMAGE, "SVG image", "image/svg+xml", "svg")
        elif extension in _SCRIPT_EXTENSIONS or head.startswith(b"#!"):
            kind = _kind(_FILE, "Script", "text/plain", *_SCRIPT_EXTENSIONS)
        else:
            kind = _kind(_DOCUMENT, "Text document", "text/plain", *_TEXT_DOCUMENT_EXTENSIONS)
    if kind is None:
        kind = _kind(_FILE, "Unrecognised binary data", "application/octet-stream")
    if extension and kind.extensions and extension not in kind.extensions:
        notes.append(
            f"The name ends in .{extension} but the content is a {kind.format}: "
            "the extension may be misleading."
        )
    if (
        kind.format.endswith("executable")
        or kind.format.startswith("Mach-O")
        or kind.format == "Script"
    ):
        notes.append(_EXECUTABLE_NOTE)
    notes.append(
        "Detected from the first bytes only. Uploads and content analysis arrive in Phase 9."
    )
    details: dict[str, object] = {"format": kind.format, "media_type": kind.mime}
    if name:
        details["name"] = PurePath(name).name
    if size is not None:
        details["size"] = size
    if sha256:
        details["sha256"] = sha256
    label = PurePath(name).name if name else "file"
    value = sha256 or label
    reason = f"The content is a {kind.format}."
    results = [
        candidate(
            kind.kind,
            value,
            display=label,
            rank="strong",
            reason=reason,
            notes=notes,
            details=details,
        )
    ]
    if kind.kind is not _FILE:
        results.append(
            candidate(
                _FILE,
                value,
                display=label,
                rank="weak",
                reason="Any file can also be examined as a file (hashes, reputation).",
                details=details,
            )
        )
    return results
