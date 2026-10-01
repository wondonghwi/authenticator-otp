#!/usr/bin/env python3
"""Scan publishable files and Git history blobs without printing matched values.

This is a supplemental pattern check, not a complete secret scanner or audit.
"""

from pathlib import Path
import re
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "api-token": re.compile(r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{15,})"),
    "cloud-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "literal-otp-secret": re.compile(r"(?:secret\s*[=:]\s*[\"']?)([A-Z2-7]{16,}={0,6})", re.I),
    "personal-home-path": re.compile(
        re.escape("/" + "Users/") + r"[A-Za-z0-9_.-]+/|" +
        re.escape("/" + "home/") + r"[A-Za-z0-9_.-]+/"
    ),
}
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
FORBIDDEN_PARTS = {".env", "credentials.json", "secrets.json"}
FORBIDDEN_SUFFIXES = {".keychain", ".keychain-db", ".p12", ".pem"}


def png_metadata(data):
    """Do not mistake compressed pixels for text; reject ancillary metadata."""
    allowed = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"sRGB", b"gAMA", b"cHRM"}
    at = 8
    while at < len(data):
        if at + 12 > len(data):
            return True
        size = struct.unpack(">I", data[at:at + 4])[0]
        kind = data[at + 4:at + 8]
        if kind not in allowed or at + size + 12 > len(data):
            return True
        at += size + 12
    return at != len(data)


def binary_findings(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ["image-metadata"] if png_metadata(data) else []
    if data.startswith(b"icns"):
        if len(data) < 8 or struct.unpack(">I", data[4:8])[0] != len(data):
            return ["invalid-icon"]
        at = 8
        while at < len(data):
            if at + 8 > len(data):
                return ["invalid-icon"]
            kind = data[at:at + 4]
            size = struct.unpack(">I", data[at + 4:at + 8])[0]
            if size < 8 or at + size > len(data):
                return ["invalid-icon"]
            chunk = data[at + 8:at + size]
            if chunk.startswith(b"\x89PNG\r\n\x1a\n"):
                if png_metadata(chunk):
                    return ["image-metadata"]
            elif kind not in {b"ic04", b"ic05"}:
                return ["icon-metadata"]
            at += size
        return []
    if b"\0" in data:
        return ["unreviewed-binary"]
    return None


def findings(path, data):
    issues = []
    parts = Path(path).parts
    if (any(part in FORBIDDEN_PARTS or part.endswith(".app") for part in parts)
            or Path(path).suffix in FORBIDDEN_SUFFIXES
            or Path(path).name.startswith(".env.")):
        issues.append("sensitive-file-name")
    binary = binary_findings(data)
    if binary is not None:
        return issues + binary
    text = data.decode("utf-8", errors="ignore")
    for name, pattern in PATTERNS.items():
        if pattern.search(text):
            issues.append(name)
    for match in EMAIL.finditer(text):
        domain = match.group().rsplit("@", 1)[1].lower()
        if domain not in {"example.com", "example.org", "example.net", "example.invalid"}:
            issues.append("personal-email")
            break
    return issues


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, check=True).stdout


def main():
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    issues = []
    count = 0
    for name in sorted(set(paths.decode().split("\0")) - {""}):
        path = ROOT / name
        if path.is_symlink():
            issues.append((name, "symbolic-link"))
            continue
        if not path.is_file():
            continue
        count += 1
        issues.extend((name, category) for category in findings(name, path.read_bytes()))

    # Git author identity is intentionally public metadata, not a source file.
    # Inspect it separately before publishing; this scan covers history blobs.
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
                          capture_output=True)
    blobs = 0
    if head.returncode == 0:
        objects = git("rev-list", "--objects", "--all").decode().splitlines()
        for line in objects:
            sha, _, path = line.partition(" ")
            if git("cat-file", "-t", sha).strip() != b"blob":
                continue
            blobs += 1
            issues.extend(("history:" + path, category)
                          for category in findings(path, git("cat-file", "blob", sha)))
    if issues:
        for path, category in sorted(set(issues)):
            print(f"FAIL {path}: {category}", file=sys.stderr)
        return 1
    print(f"Pattern check passed: {count} files, {blobs} history blobs. "
          "Manual review is still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
