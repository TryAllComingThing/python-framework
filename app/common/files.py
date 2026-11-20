"""Pure, bounded validation of supported upload content and filenames."""

from __future__ import annotations

import re
import unicodedata
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, LargeZipFile, ZipFile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

CONTENT_TYPES = MappingProxyType(
    {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".txt": "text/plain; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


@dataclass(frozen=True)
class ValidatedUpload:
    """Normalized filename, trusted suffix and canonical media type."""

    filename: str
    suffix: str
    content_type: str


def _valid_png(data: bytes) -> bool:
    """Validate PNG signature, chunk bounds/CRC, critical chunks and IEND."""
    if len(data) < 45 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    offset = 8
    saw_ihdr = saw_idat = saw_iend = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            return False
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(data[offset + 8 + length : chunk_end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            return False
        if not saw_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                return False
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            if width == 0 or height == 0:
                return False
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            saw_idat = True
        elif chunk_type == b"IEND":
            if length != 0 or chunk_end != len(data):
                return False
            saw_iend = True
        offset = chunk_end
    return saw_ihdr and saw_idat and saw_iend and offset == len(data)


def _valid_jpeg(data: bytes) -> bool:
    """Scan JPEG markers and entropy-coded scans through the EOI marker."""
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        return False
    offset = 2
    in_scan = False
    saw_scan = False
    while offset < len(data):
        if data[offset] != 0xFF:
            if not in_scan:
                return False
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return False
        marker = data[offset]
        offset += 1
        if marker == 0x00:
            if not in_scan:
                return False
            continue
        if marker == 0xD9:
            return saw_scan
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if offset + 2 > len(data):
            return False
        segment_length = int.from_bytes(data[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(data):
            return False
        offset += segment_length
        if marker == 0xDA:
            in_scan = True
            saw_scan = True
        elif in_scan:
            # A non-restart marker terminates the current entropy-coded scan.
            in_scan = False
            offset -= segment_length
            offset -= 2
    return False


def _valid_pdf(data: bytes) -> bool:
    """Check PDF header, cross-reference marker and terminal EOF marker."""
    if not re.match(rb"%PDF-[12]\.[0-9]", data[:16]):
        return False
    trimmed = data.rstrip(b"\x00\t\n\f\r ")
    if not trimmed.endswith(b"%%EOF"):
        return False
    tail = trimmed[-4096:].lower()
    return b"startxref" in tail and b"obj" in data[: min(len(data), 1_000_000)].lower()


# Restrictive OOXML policy: spreadsheets only, no active/external content.
# A strict policy intentionally rejects some otherwise valid rich workbooks.
ALLOWED_RELATIONSHIP_SUFFIXES = frozenset(
    {
        "officedocument",
        "worksheet",
        "styles",
        "sharedstrings",
        "theme",
        "calcchain",
        "core-properties",
        "extended-properties",
    }
)
BLOCKED_PATH_SEGMENTS = frozenset(
    {
        "vba",
        "activex",
        "embeddings",
        "externallinks",
        "connections",
        "querytables",
        "pivotcache",
        "customxml",
        "webextensions",
        "printersettings",
        "ctrlprops",
        "drawings",
        "media",
        "charts",
    }
)
MAX_XML_PART_BYTES = 8_000_000
_ALLOWED_XML_PREFIXES = (
    "http://schemas.openxmlformats.org/officedocument/2006/relationships/",
    "http://schemas.openxmlformats.org/package/2006/relationships/",
    "http://purl.oclc.org/ooxml/officedocument/relationships/",
)


def _safe_ooxml_xml(data: bytes) -> ET.Element:
    """Parse bounded OOXML XML with DTD/entity and stylesheet processing rejected."""
    if len(data) > MAX_XML_PART_BYTES:
        raise ValueError("oversized XML part")
    lowered = data.lower()
    if any(token in lowered for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet")):
        raise ValueError("DTD, entities and stylesheet processing are forbidden")
    return ET.fromstring(data)


def _ooxml_policy(archive: ZipFile, names: set[str]) -> bool:
    """Enforce macro-free, external-link-free, bounded workbook semantics."""
    content_types = _safe_ooxml_xml(archive.read("[Content_Types].xml"))
    ct_ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    allowed_workbook = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    workbook_types = [
        element.attrib.get("ContentType")
        for element in content_types
        if element.tag == ct_ns + "Override"
        and element.attrib.get("PartName") == "/xl/workbook.xml"
    ]
    if workbook_types != [allowed_workbook]:
        return False
    for element in content_types:
        content_type = element.attrib.get("ContentType", "").lower()
        if any(
            bad in content_type
            for bad in ("macroenabled", "vba", "activex", "oleobject", "external")
        ):
            return False
    for name in names:
        norm = name.lower()
        if any(part in BLOCKED_PATH_SEGMENTS for part in norm.split("/")):
            return False
        if not name.endswith((".xml", ".rels")):
            continue
        root = _safe_ooxml_xml(archive.read(name))
        if name.endswith(".rels"):
            for relation in root:
                if relation.attrib.get("TargetMode", "").lower() == "external":
                    return False
                kind = unquote(relation.attrib.get("Type", "")).casefold()
                if (
                    not kind.startswith(_ALLOWED_XML_PREFIXES)
                    or kind.rsplit("/", 1)[-1] not in ALLOWED_RELATIONSHIP_SUFFIXES
                ):
                    return False
                target = unquote(relation.attrib.get("Target", ""))
                parsed = urlsplit(target)
                if (
                    parsed.scheme
                    or parsed.netloc
                    or target.startswith("\\")
                    or "\\" in target
                    or ".." in target.split("/")
                ):
                    return False
        # Reject formula execution and workbook links; this is a data-only upload policy.
        if any(
            element.tag.rsplit("}", 1)[-1] in ("f", "externalReferences", "hyperlink")
            for element in root.iter()
        ):
            return False
    return True


def _valid_xlsx(data: bytes) -> bool:
    """Validate OOXML container membership and reject suspicious entries.

    Inspects relationship and XML policies; rejects macros, formulas, external
    links and disallowed embedded parts. This is not malware scanning.
    """
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if not members or len(members) > 1000:
                return False
            names = {item.filename for item in members}
            if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
                return False
            if len(names) != len(members):
                return False
            total = 0
            for item in members:
                path = item.filename.replace("\\", "/")
                if path.startswith("/") or ".." in path.split("/"):
                    return False
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    return False
                if item.flag_bits & 0x1:
                    return False
                if item.filename.lower().endswith(("vbaproject.bin", ".exe", ".dll")):
                    return False
                total += item.file_size
                if item.file_size > 20_000_000 or total > 50_000_000:
                    return False
            verified_total = 0
            for item in members:
                member_total = 0
                with archive.open(item) as stream:
                    while chunk := stream.read(64 * 1024):
                        member_total += len(chunk)
                        verified_total += len(chunk)
                        if member_total > 20_000_000 or verified_total > 50_000_000:
                            return False
                if member_total != item.file_size:
                    return False
            return _ooxml_policy(archive, names)
    except (
        DefusedXmlException,
        ET.ParseError,
        KeyError,
        BadZipFile,
        LargeZipFile,
        OSError,
        ValueError,
        RuntimeError,
        EOFError,
        NotImplementedError,
        zlib.error,
    ):
        return False


def validate_upload(
    data: bytes,
    filename: str,
    max_bytes: int = 5_000_000,
) -> ValidatedUpload:
    """Return canonical upload metadata or raise ``ValueError``.

    The bytes must already be capped by the caller; detection is based on file
    structure rather than the untrusted multipart Content-Type or extension.
    """
    if not data or len(data) > max_bytes:
        raise ValueError("invalid upload size")
    if (
        not filename
        or len(filename) > 255
        or filename.strip() != filename
        or any(ch in filename for ch in ("/", "\\", "\x00", "\r", "\n"))
        or filename in (".", "..")
    ):
        raise ValueError("invalid filename")
    normalized = unicodedata.normalize("NFC", filename)
    if any(unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in normalized):
        raise ValueError("control or formatting character in filename")
    suffix = Path(normalized).suffix.lower()
    if suffix not in CONTENT_TYPES:
        raise ValueError("extension not allowed")
    if suffix == ".pdf" and not _valid_pdf(data):
        raise ValueError("invalid PDF content")
    if suffix == ".png" and not _valid_png(data):
        raise ValueError("invalid PNG content")
    if suffix in (".jpg", ".jpeg") and not _valid_jpeg(data):
        raise ValueError("invalid JPEG content")
    if suffix == ".xlsx" and not _valid_xlsx(data):
        raise ValueError("invalid XLSX content")
    if suffix in (".txt", ".csv"):
        if b"\x00" in data:
            raise ValueError("binary content not allowed for text")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("text must be UTF-8") from exc
    return ValidatedUpload(normalized, suffix, CONTENT_TYPES[suffix])
