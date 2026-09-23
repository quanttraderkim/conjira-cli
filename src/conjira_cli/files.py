"""Atomic exports with source identity and local-edit protection."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.parse
import uuid
from pathlib import Path

from conjira_cli.config import ConfigError


def metadata(text: str) -> dict[str, str]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.DOTALL)
    if not match:
        return {}
    return {
        key.strip(): value.strip().strip("\"'")
        for line in match.group(1).splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def body_digest(text: str) -> str:
    body = re.sub(
        r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", "", text, count=1, flags=re.DOTALL
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def stamp_export(text: str, base_url: str) -> str:
    return text.replace(
        "---\n",
        "---\nconjira_base_url: "
        + base_url.rstrip("/")
        + "\nconjira_content_sha256: "
        + body_digest(text)
        + "\n",
        1,
    )


def validate_source(data: dict[str, str], base_url: str) -> None:
    source = data.get("conjira_base_url") or data.get("source_url")
    if not source:
        raise ConfigError("Export has no source URL; refusing to guess its server.")
    expected = urllib.parse.urlsplit(base_url.rstrip("/"))
    actual = urllib.parse.urlsplit(source)

    def origin(url):
        return (
            url.scheme.lower(),
            (url.hostname or "").lower(),
            url.port or (443 if url.scheme == "https" else 80),
        )

    path_ok = (
        actual.path.rstrip("/") == expected.path.rstrip("/")
        if data.get("conjira_base_url")
        else actual.path.startswith(expected.path.rstrip("/") + "/")
    )
    if not data.get("conjira_base_url"):
        for marker in ("/pages/", "/display/", "/spaces/", "/x/"):
            if marker in actual.path:
                path_ok = actual.path.split(marker, 1)[0].rstrip(
                    "/"
                ) == expected.path.rstrip("/")
                break
    if origin(actual) != origin(expected) or not path_ok:
        raise ConfigError(
            "Export belongs to another Confluence installation. Use its original server configuration."
        )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_export(
    path: Path, text: str, *, page_id: str, base_url: str, force: bool = False
) -> str | None:
    backup = None
    if path.exists():
        old = path.read_text(encoding="utf-8")
        data = metadata(old)
        if data.get("confluence_page_id") != str(page_id):
            raise ConfigError(
                "Output file belongs to another page; choose a different filename."
            )
        validate_source(data, base_url)
        digest = data.get("conjira_content_sha256")
        if not force and (not digest or digest != body_digest(old)):
            raise ConfigError(
                "Local edits or a legacy export detected. Review the file, then use --force to refresh with a backup."
            )
        backup = str(path.with_name(path.name + ".bak-" + uuid.uuid4().hex[:12]))
        shutil.copy2(path, backup)
    atomic_write(path, text)
    return backup
