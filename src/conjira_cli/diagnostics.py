from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

from conjira_cli import __version__
from conjira_cli.config import load_env_file, resolve_env_file_path


def doctor(env_file=None):
    resolved = resolve_env_file_path(env_file)
    values = load_env_file(Path(resolved)) if resolved else {}

    def value(key):
        return os.environ.get(key) or values.get(key)

    products = {}
    for product in ("CONFLUENCE", "JIRA"):
        source = "missing"
        for suffix, label in [
            ("PAT_FILE", "token_file"),
            ("PAT_KEYCHAIN_SERVICE", "keychain"),
            ("PAT", "environment_or_env_file"),
        ]:
            if value(product + "_" + suffix):
                source = label
                break
        parsed = urllib.parse.urlsplit(value(product + "_BASE_URL") or "")
        products[product.lower()] = {
            "base_url": urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", "")
            ),
            "credential_source": source,
            "configured": bool(parsed.netloc and source != "missing"),
        }
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "module": str(Path(__file__).resolve().parent),
        "env_file": resolved,
        "products": products,
        "credentials_checked": False,
    }
