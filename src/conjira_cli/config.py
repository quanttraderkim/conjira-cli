from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set, Tuple


class ConfigError(RuntimeError):
    pass


@dataclass
class BaseSettings:
    base_url: str
    token: str
    timeout_seconds: int = 30


@dataclass
class ConfluenceSettings(BaseSettings):
    allowed_space_keys: Optional[Set[str]] = None
    allowed_parent_ids: Optional[Set[str]] = None
    allowed_page_ids: Optional[Set[str]] = None
    export_default_dir: Optional[str] = None
    export_staging_dir: Optional[str] = None


@dataclass
class JiraSettings(BaseSettings):
    allowed_project_keys: Optional[Set[str]] = None
    allowed_issue_keys: Optional[Set[str]] = None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        raise ConfigError("Env file not found: {0}".format(path))

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError("Invalid env line: {0}".format(raw_line))
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_quotes(value.strip())
    return values


def _parse_csv_set(value: Optional[str]) -> Optional[Set[str]]:
    if not value:
        return None
    items = {item.strip() for item in value.split(",") if item.strip()}
    return items or None


def _read_token_from_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def _read_token_from_keychain(
    service: Optional[str],
    account: Optional[str],
) -> Optional[str]:
    if not service or not account:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ConfigError("macOS security command not found for keychain lookup.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else "Unknown keychain lookup error"
        raise ConfigError("Failed to read token from macOS Keychain: {0}".format(stderr)) from exc
    return result.stdout.strip()


def _resolve_common_settings(
    *,
    prefix: str,
    label: str,
    base_url: Optional[str],
    token: Optional[str],
    token_file: Optional[str],
    token_keychain_service: Optional[str],
    token_keychain_account: Optional[str],
    timeout_seconds: Optional[int],
    env_file: Optional[str] = None,
) -> Tuple[Dict[str, str], str, str, int]:
    env: Dict[str, str] = {}
    if env_file:
        env = load_env_file(Path(env_file))

    base_url_key = "{0}_BASE_URL".format(prefix)
    token_key = "{0}_PAT".format(prefix)
    token_file_key = "{0}_PAT_FILE".format(prefix)
    token_keychain_service_key = "{0}_PAT_KEYCHAIN_SERVICE".format(prefix)
    token_keychain_account_key = "{0}_PAT_KEYCHAIN_ACCOUNT".format(prefix)
    timeout_key = "{0}_TIMEOUT_SECONDS".format(prefix)

    resolved_base_url = (
        base_url
        or os.environ.get(base_url_key)
        or env.get(base_url_key)
    )
    resolved_token = token
    if not resolved_token:
        resolved_token = _read_token_from_file(
            token_file or os.environ.get(token_file_key) or env.get(token_file_key)
        )
    if not resolved_token:
        resolved_token = _read_token_from_keychain(
            token_keychain_service
            or os.environ.get(token_keychain_service_key)
            or env.get(token_keychain_service_key),
            token_keychain_account
            or os.environ.get(token_keychain_account_key)
            or env.get(token_keychain_account_key),
        )
    if not resolved_token:
        resolved_token = os.environ.get(token_key) or env.get(token_key)
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        raw_timeout = os.environ.get(timeout_key) or env.get(timeout_key)
        resolved_timeout = int(raw_timeout) if raw_timeout else 30

    if not resolved_base_url:
        raise ConfigError(
            "Missing {0} base URL. Set --base-url or {1}.".format(label, base_url_key)
        )
    if not resolved_token:
        raise ConfigError(
            "Missing {0} token. Use --token, --token-file, Keychain options, or {1}.".format(
                label,
                token_key,
            )
        )

    return env, resolved_base_url.rstrip("/"), resolved_token, resolved_timeout


def build_confluence_settings(
    base_url: Optional[str],
    token: Optional[str],
    token_file: Optional[str],
    token_keychain_service: Optional[str],
    token_keychain_account: Optional[str],
    timeout_seconds: Optional[int],
    env_file: Optional[str] = None,
) -> ConfluenceSettings:
    env, resolved_base_url, resolved_token, resolved_timeout = _resolve_common_settings(
        prefix="CONFLUENCE",
        label="Confluence",
        base_url=base_url,
        token=token,
        token_file=token_file,
        token_keychain_service=token_keychain_service,
        token_keychain_account=token_keychain_account,
        timeout_seconds=timeout_seconds,
        env_file=env_file,
    )
    allowed_space_keys = _parse_csv_set(
        os.environ.get("CONFLUENCE_ALLOWED_SPACE_KEYS") or env.get("CONFLUENCE_ALLOWED_SPACE_KEYS")
    )
    allowed_parent_ids = _parse_csv_set(
        os.environ.get("CONFLUENCE_ALLOWED_PARENT_IDS") or env.get("CONFLUENCE_ALLOWED_PARENT_IDS")
    )
    allowed_page_ids = _parse_csv_set(
        os.environ.get("CONFLUENCE_ALLOWED_PAGE_IDS") or env.get("CONFLUENCE_ALLOWED_PAGE_IDS")
    )
    export_default_dir = (
        os.environ.get("CONFLUENCE_EXPORT_DEFAULT_DIR")
        or env.get("CONFLUENCE_EXPORT_DEFAULT_DIR")
    )
    export_staging_dir = (
        os.environ.get("CONFLUENCE_EXPORT_STAGING_DIR")
        or env.get("CONFLUENCE_EXPORT_STAGING_DIR")
    )

    return ConfluenceSettings(
        base_url=resolved_base_url.rstrip("/"),
        token=resolved_token,
        timeout_seconds=resolved_timeout,
        allowed_space_keys=allowed_space_keys,
        allowed_parent_ids=allowed_parent_ids,
        allowed_page_ids=allowed_page_ids,
        export_default_dir=export_default_dir,
        export_staging_dir=export_staging_dir,
    )


def build_jira_settings(
    base_url: Optional[str],
    token: Optional[str],
    token_file: Optional[str],
    token_keychain_service: Optional[str],
    token_keychain_account: Optional[str],
    timeout_seconds: Optional[int],
    env_file: Optional[str] = None,
) -> JiraSettings:
    env, resolved_base_url, resolved_token, resolved_timeout = _resolve_common_settings(
        prefix="JIRA",
        label="Jira",
        base_url=base_url,
        token=token,
        token_file=token_file,
        token_keychain_service=token_keychain_service,
        token_keychain_account=token_keychain_account,
        timeout_seconds=timeout_seconds,
        env_file=env_file,
    )
    allowed_project_keys = _parse_csv_set(
        os.environ.get("JIRA_ALLOWED_PROJECT_KEYS") or env.get("JIRA_ALLOWED_PROJECT_KEYS")
    )
    allowed_issue_keys = _parse_csv_set(
        os.environ.get("JIRA_ALLOWED_ISSUE_KEYS") or env.get("JIRA_ALLOWED_ISSUE_KEYS")
    )

    return JiraSettings(
        base_url=resolved_base_url.rstrip("/"),
        token=resolved_token,
        timeout_seconds=resolved_timeout,
        allowed_project_keys=allowed_project_keys,
        allowed_issue_keys=allowed_issue_keys,
    )


def build_settings(
    base_url: Optional[str],
    token: Optional[str],
    token_file: Optional[str],
    token_keychain_service: Optional[str],
    token_keychain_account: Optional[str],
    timeout_seconds: Optional[int],
    env_file: Optional[str] = None,
) -> ConfluenceSettings:
    return build_confluence_settings(
        base_url=base_url,
        token=token,
        token_file=token_file,
        token_keychain_service=token_keychain_service,
        token_keychain_account=token_keychain_account,
        timeout_seconds=timeout_seconds,
        env_file=env_file,
    )
