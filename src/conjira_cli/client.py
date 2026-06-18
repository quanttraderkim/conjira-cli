from __future__ import annotations

import email.utils
import hashlib
import json
import os
import random
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from conjira_cli.footer_comments import build_footer_comment_summary
from conjira_cli.inline_comments import build_inline_comment_summary

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX fallback
    msvcrt = None  # type: ignore[assignment]


DEFAULT_RATE_LIMIT_RPS = 4.0
DEFAULT_RATE_LIMIT_BURST = 8
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_SECONDS = 1.0
DEFAULT_RETRY_MAX_SECONDS = 30.0


class AtlassianError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        payload: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ConfluenceError(AtlassianError):
    pass


class JiraError(AtlassianError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: Optional[Any] = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+")
        if fcntl is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            msvcrt.locking(self._file.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._file is None:
            return False
        if fcntl is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        self._file.close()
        return False


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    stripped = value.strip()
    try:
        return max(0.0, float(stripped))
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    return max(0.0, retry_at.timestamp() - time.time())


def _read_error_payload(exc: urllib.error.HTTPError) -> tuple[str, Any]:
    raw = exc.read().decode("utf-8", errors="replace")
    payload: Any
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    message = "API request failed"
    if isinstance(payload, dict):
        if payload.get("message"):
            message = payload["message"]
        elif payload.get("errorMessages"):
            message = "; ".join(payload["errorMessages"])
    return message, payload


def validate_storage_html(body_html: str) -> None:
    """Check that *body_html* is well-formed XHTML before sending to Confluence.

    Raises :class:`ConfluenceError` with a descriptive message if parsing
    fails, giving the caller a chance to fix the content instead of getting
    a cryptic 400 from the server.
    """
    wrapped = (
        '<root xmlns:ac="urn:ac" xmlns:ri="urn:ri"'
        ' xmlns:atlassian="urn:atlassian">'
        + body_html
        + "</root>"
    )
    try:
        ET.fromstring(wrapped)
    except ET.ParseError as exc:
        raise ConfluenceError(
            f"Body HTML is not well-formed XHTML — Confluence will reject it. "
            f"Detail: {exc}",
        ) from exc


class BaseAtlassianClient:
    product_name = "Atlassian"
    error_cls = AtlassianError

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: int = 30,
        *,
        rate_limit_enabled: Optional[bool] = None,
        rate_limit_rps: Optional[float] = None,
        rate_limit_burst: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_base_seconds: Optional[float] = None,
        retry_max_seconds: Optional[float] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.rate_limit_enabled = (
            _env_bool("CONJIRA_RATE_LIMIT_ENABLED", True)
            if rate_limit_enabled is None
            else rate_limit_enabled
        )
        self.rate_limit_rps = (
            _env_float("CONJIRA_RATE_LIMIT_RPS", DEFAULT_RATE_LIMIT_RPS)
            if rate_limit_rps is None
            else rate_limit_rps
        )
        self.rate_limit_burst = (
            _env_int("CONJIRA_RATE_LIMIT_BURST", DEFAULT_RATE_LIMIT_BURST)
            if rate_limit_burst is None
            else rate_limit_burst
        )
        self.max_retries = (
            _env_int("CONJIRA_MAX_RETRIES", DEFAULT_MAX_RETRIES)
            if max_retries is None
            else max_retries
        )
        self.retry_base_seconds = (
            _env_float("CONJIRA_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS)
            if retry_base_seconds is None
            else retry_base_seconds
        )
        self.retry_max_seconds = (
            _env_float("CONJIRA_RETRY_MAX_SECONDS", DEFAULT_RETRY_MAX_SECONDS)
            if retry_max_seconds is None
            else retry_max_seconds
        )
        self._rate_limit_state_path = self._build_rate_limit_state_path()

    def _build_rate_limit_state_path(self) -> Path:
        configured_dir = os.environ.get("CONJIRA_RATE_LIMIT_DIR")
        base_dir = (
            Path(configured_dir).expanduser()
            if configured_dir
            else Path(tempfile.gettempdir()) / "conjira-cli-rate-limit"
        )
        identity = "{0}:{1}:{2}".format(self.product_name, self.base_url, self.token)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return base_dir / "{0}.json".format(digest)

    def _wait_for_rate_limit_slot(self) -> None:
        if (
            not self.rate_limit_enabled
            or self.rate_limit_rps <= 0
            or self.rate_limit_burst <= 0
        ):
            return

        state_path = self._rate_limit_state_path
        lock_path = state_path.with_suffix(".lock")

        while True:
            with _FileLock(lock_path):
                now = time.time()
                state = self._read_rate_limit_state(state_path)
                updated_at = float(state.get("updated_at", now))
                tokens = float(state.get("tokens", self.rate_limit_burst))
                elapsed = max(0.0, now - updated_at)
                tokens = min(
                    float(self.rate_limit_burst),
                    tokens + (elapsed * self.rate_limit_rps),
                )

                if tokens >= 1.0:
                    self._write_rate_limit_state(
                        state_path,
                        tokens=tokens - 1.0,
                        updated_at=now,
                    )
                    return

                wait_seconds = (1.0 - tokens) / self.rate_limit_rps
                self._write_rate_limit_state(
                    state_path,
                    tokens=tokens,
                    updated_at=now,
                )

            time.sleep(wait_seconds + random.uniform(0.0, 0.05))

    @staticmethod
    def _read_rate_limit_state(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _write_rate_limit_state(
        path: Path,
        *,
        tokens: float,
        updated_at: float,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "tokens": tokens,
            "updated_at": updated_at,
        }
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(path)

    def _retry_delay_seconds(self, exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = _parse_retry_after(exc.headers.get("Retry-After"))
        if retry_after is not None:
            return min(retry_after, self.retry_max_seconds)
        backoff = self.retry_base_seconds * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0.0, min(0.5, self.retry_base_seconds))
        return min(backoff + jitter, self.retry_max_seconds)

    def _should_retry_http_error(self, exc: urllib.error.HTTPError, attempt: int) -> bool:
        return exc.code == 429 and attempt <= self.max_retries

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        if body is not None and raw_body is not None:
            raise ValueError("request accepts either body or raw_body, not both")

        url = self.base_url + path
        if query:
            filtered = {key: value for key, value in query.items() if value is not None}
            url += "?" + urllib.parse.urlencode(filtered, doseq=True)

        request_headers = {
            "Authorization": "Bearer {0}".format(self.token),
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            request_headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif raw_body is not None:
            data = raw_body
        if headers:
            request_headers.update(headers)

        attempt = 0
        while True:
            attempt += 1
            request = urllib.request.Request(
                url,
                data=data,
                headers=request_headers,
                method=method.upper(),
            )

            self._wait_for_rate_limit_slot()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8")
                    if not raw:
                        return None
                    content_type = response.headers.get("Content-Type", "")
                    if "application/json" in content_type:
                        return json.loads(raw)
                    stripped = raw.lstrip()
                    if stripped.startswith("{") or stripped.startswith("["):
                        try:
                            return json.loads(raw)
                        except json.JSONDecodeError:
                            pass
                    return raw
            except urllib.error.HTTPError as exc:
                if self._should_retry_http_error(exc, attempt):
                    time.sleep(self._retry_delay_seconds(exc, attempt))
                    continue
                message, payload = _read_error_payload(exc)
                if message == "API request failed":
                    message = "{0} API request failed".format(self.product_name)
                raise self.error_cls(message, status_code=exc.code, payload=payload) from exc
            except urllib.error.URLError as exc:
                raise self.error_cls(
                    "Failed to connect to {0}: {1}".format(self.product_name, exc.reason)
                ) from exc


class ConfluenceClient(BaseAtlassianClient):
    product_name = "Confluence"
    error_cls = ConfluenceError

    def auth_check(self) -> Dict[str, Any]:
        data = self.request("GET", "/rest/api/space", query={"limit": 1})
        results = data.get("results", []) if isinstance(data, dict) else []
        return {
            "base_url": self.base_url,
            "authenticated": True,
            "space_count_sample": len(results),
            "first_space_key": results[0].get("key") if results else None,
        }

    def get_page(self, page_id: str, expand: Optional[str] = None) -> Dict[str, Any]:
        query = {"expand": expand} if expand else None
        return self.request("GET", "/rest/api/content/{0}".format(page_id), query=query)

    def get_child_pages(
        self,
        page_id: str,
        *,
        limit: int = 200,
        start: int = 0,
    ) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/rest/api/content/{0}/child/page".format(page_id),
            query={"limit": limit, "start": start},
        )

    def list_child_pages(
        self,
        page_id: str,
        *,
        limit: int = 200,
    ) -> list[Dict[str, Any]]:
        pages: list[Dict[str, Any]] = []
        start = 0

        while True:
            result = self.get_child_pages(page_id, limit=limit, start=start)
            batch = result.get("results", []) if isinstance(result, dict) else []
            if not batch:
                break
            pages.extend(batch)

            batch_size = len(batch)
            if batch_size < limit:
                break
            start += batch_size

        return pages

    def create_page(
        self,
        *,
        space_key: str,
        title: str,
        body_html: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        validate_storage_html(body_html)
        payload: Dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_html,
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return self.request("POST", "/rest/api/content", body=payload)

    def update_page(
        self,
        *,
        page_id: str,
        new_title: Optional[str] = None,
        new_body_html: Optional[str] = None,
        append_html: Optional[str] = None,
        new_parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        current = self.get_page(page_id, expand="body.storage,version,space")
        return self.update_page_from_snapshot(
            current,
            new_title=new_title,
            new_body_html=new_body_html,
            append_html=append_html,
            new_parent_id=new_parent_id,
        )

    def update_page_from_snapshot(
        self,
        current: Dict[str, Any],
        *,
        new_title: Optional[str] = None,
        new_body_html: Optional[str] = None,
        append_html: Optional[str] = None,
        new_parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        current_body = (((current.get("body") or {}).get("storage") or {}).get("value")) or ""
        updated_body = new_body_html if new_body_html is not None else current_body
        if append_html:
            updated_body += append_html

        validate_storage_html(updated_body)

        payload = {
            "id": current["id"],
            "type": current["type"],
            "title": new_title or current["title"],
            "space": {"key": (current.get("space") or {})["key"]},
            "body": {
                "storage": {
                    "value": updated_body,
                    "representation": "storage",
                }
            },
            "version": {
                "number": ((current.get("version") or {}).get("number") or 0) + 1,
            },
        }
        if new_parent_id is not None:
            payload["ancestors"] = [{"id": new_parent_id}]
        return self.request("PUT", "/rest/api/content/{0}".format(current["id"]), body=payload)

    def search(
        self,
        *,
        cql: str,
        limit: int = 10,
        expand: Optional[str] = None,
        start: int = 0,
    ) -> Dict[str, Any]:
        query = {
            "cql": cql,
            "limit": limit,
            "start": start,
            "expand": expand,
        }
        return self.request("GET", "/rest/api/content/search", query=query)

    def get_inline_comments(
        self,
        page_id: str,
        *,
        limit: int = 200,
        start: int = 0,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = {
            "location": "inline",
            "expand": "body.storage,extensions.inlineProperties,extensions.resolution,history,container",
            "limit": limit,
            "start": start,
            "depth": "all",
            "status": status,
        }
        return self.request(
            "GET",
            "/rest/api/content/{0}/child/comment".format(page_id),
            query=query,
        )

    def list_inline_comments(
        self,
        page_id: str,
        *,
        limit: int = 200,
    ) -> list[Dict[str, Any]]:
        comments: list[Dict[str, Any]] = []
        start = 0

        while True:
            result = self.get_inline_comments(
                page_id,
                limit=limit,
                start=start,
            )
            batch = result.get("results", []) if isinstance(result, dict) else []
            if not batch:
                break
            comments.extend(batch)

            batch_size = len(batch)
            if batch_size < limit:
                break
            start += batch_size

        return comments

    def get_footer_comments(
        self,
        page_id: str,
        *,
        limit: int = 200,
        start: int = 0,
    ) -> Dict[str, Any]:
        query = {
            "location": "footer",
            "expand": "body.storage,history,container,ancestors",
            "limit": limit,
            "start": start,
            "depth": "all",
        }
        return self.request(
            "GET",
            "/rest/api/content/{0}/child/comment".format(page_id),
            query=query,
        )

    def list_footer_comments(
        self,
        page_id: str,
        *,
        limit: int = 200,
    ) -> list[Dict[str, Any]]:
        comments: list[Dict[str, Any]] = []
        start = 0

        while True:
            result = self.get_footer_comments(
                page_id,
                limit=limit,
                start=start,
            )
            batch = result.get("results", []) if isinstance(result, dict) else []
            if not batch:
                break
            comments.extend(batch)

            batch_size = len(batch)
            if batch_size < limit:
                break
            start += batch_size

        return comments

    def get_attachments(
        self,
        page_id: str,
        *,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        return self.request(
            "GET",
            "/rest/api/content/{0}/child/attachment".format(page_id),
            query={"limit": limit},
        )

    def upload_attachment(
        self,
        *,
        page_id: str,
        file_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        comment: Optional[str] = None,
        minor_edit: bool = True,
    ) -> Dict[str, Any]:
        existing = None
        attachments = self.get_attachments(page_id)
        for item in attachments.get("results", []):
            if item.get("title") == file_name:
                existing = item
                break

        payload, boundary = self._build_attachment_form(
            file_name=file_name,
            content=content,
            content_type=content_type,
            comment=comment,
            minor_edit=minor_edit,
        )
        if existing:
            path = "/rest/api/content/{0}/child/attachment/{1}/data".format(
                page_id,
                existing["id"],
            )
        else:
            path = "/rest/api/content/{0}/child/attachment".format(page_id)

        return self.request(
            "POST",
            path,
            raw_body=payload,
            headers={
                "Content-Type": "multipart/form-data; boundary={0}".format(boundary),
                "X-Atlassian-Token": "no-check",
            },
        )

    @staticmethod
    def _build_attachment_form(
        *,
        file_name: str,
        content: bytes,
        content_type: str,
        comment: Optional[str],
        minor_edit: bool,
    ) -> tuple[bytes, str]:
        boundary = "----conjira-{0}".format(time.time_ns())
        body = bytearray()

        def add_text_part(name: str, value: str) -> None:
            body.extend("--{0}\r\n".format(boundary).encode("utf-8"))
            body.extend(
                'Content-Disposition: form-data; name="{0}"\r\n\r\n'.format(name).encode("utf-8")
            )
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        add_text_part("minorEdit", "true" if minor_edit else "false")
        if comment:
            add_text_part("comment", comment)

        body.extend("--{0}\r\n".format(boundary).encode("utf-8"))
        body.extend(
            'Content-Disposition: form-data; name="file"; filename="{0}"\r\n'.format(
                file_name
            ).encode("utf-8")
        )
        body.extend("Content-Type: {0}\r\n\r\n".format(content_type).encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")
        body.extend("--{0}--\r\n".format(boundary).encode("utf-8"))
        return bytes(body), boundary

    @staticmethod
    def webui_url(content: Dict[str, Any]) -> Optional[str]:
        links = content.get("_links") or {}
        base = links.get("base")
        webui = links.get("webui")
        if base and webui:
            return "{0}{1}".format(base, webui)
        return None

    @staticmethod
    def attachment_download_url(attachment: Dict[str, Any]) -> Optional[str]:
        links = attachment.get("_links") or {}
        base = links.get("base")
        download = links.get("download")
        if base and download:
            return "{0}{1}".format(base, download)
        return None

    @staticmethod
    def summarize_page(content: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": content.get("id"),
            "type": content.get("type"),
            "status": content.get("status"),
            "title": content.get("title"),
            "space_key": (content.get("space") or {}).get("key"),
            "version": ((content.get("version") or {}).get("number")),
            "webui_url": ConfluenceClient.webui_url(content),
        }

    @staticmethod
    def summarize_attachment(content: Dict[str, Any]) -> Dict[str, Any]:
        extensions = content.get("extensions") or {}
        metadata = content.get("metadata") or {}
        return {
            "id": content.get("id"),
            "title": content.get("title"),
            "media_type": metadata.get("mediaType"),
            "file_size": extensions.get("fileSize"),
            "download_url": ConfluenceClient.attachment_download_url(content),
        }

    @staticmethod
    def summarize_search_results(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        results = [ConfluenceClient.summarize_page(item) for item in items]
        return {"results": results, "count": len(results)}

    def summarize_inline_comments(
        self,
        *,
        page: Dict[str, Any],
        comments: Iterable[Dict[str, Any]],
        status_filter: str = "all",
    ) -> Dict[str, Any]:
        return build_inline_comment_summary(
            base_url=self.base_url,
            page_id=page.get("id") or "",
            page_title=page.get("title") or "Untitled",
            page_url=self.webui_url(page) or "",
            raw_comments=comments,
            status_filter=status_filter,
        )

    def summarize_footer_comments(
        self,
        *,
        page: Dict[str, Any],
        comments: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return build_footer_comment_summary(
            base_url=self.base_url,
            page_id=page.get("id") or "",
            page_title=page.get("title") or "Untitled",
            page_url=self.webui_url(page) or "",
            raw_comments=comments,
        )


class JiraClient(BaseAtlassianClient):
    product_name = "Jira"
    error_cls = JiraError

    def auth_check(self) -> Dict[str, Any]:
        data = self.request("GET", "/rest/api/2/serverInfo")
        return {
            "base_url": self.base_url,
            "authenticated": True,
            "version": data.get("version"),
            "build_number": data.get("buildNumber"),
            "deployment_type": data.get("deploymentType"),
        }

    def get_issue(
        self,
        issue_key: str,
        *,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = {"fields": fields, "expand": expand}
        return self.request("GET", "/rest/api/2/issue/{0}".format(issue_key), query=query)

    def search(
        self,
        *,
        jql: str,
        limit: int = 10,
        start: int = 0,
        fields: Optional[str] = None,
        expand: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = {
            "jql": jql,
            "maxResults": limit,
            "startAt": start,
            "fields": fields,
            "expand": expand,
        }
        return self.request("GET", "/rest/api/2/search", query=query)

    def get_createmeta(
        self,
        *,
        project_key: str,
        issue_type_name: Optional[str] = None,
        expand: Optional[str] = None,
    ) -> Dict[str, Any]:
        query = {
            "projectKeys": project_key,
            "issuetypeNames": issue_type_name,
            "expand": expand,
        }
        return self.request("GET", "/rest/api/2/issue/createmeta", query=query)

    def create_issue(
        self,
        *,
        project_key: str,
        summary: str,
        issue_type_name: str,
        description: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type_name},
        }
        if description is not None:
            fields["description"] = description
        if extra_fields:
            fields.update(extra_fields)
        payload = {"fields": fields}
        return self.request("POST", "/rest/api/2/issue", body=payload)

    def add_comment(self, *, issue_key: str, body: str) -> Dict[str, Any]:
        payload = {"body": body}
        return self.request("POST", "/rest/api/2/issue/{0}/comment".format(issue_key), body=payload)

    @staticmethod
    def browse_url(base_url: str, issue_key: Optional[str]) -> Optional[str]:
        if not issue_key:
            return None
        return "{0}/browse/{1}".format(base_url.rstrip("/"), issue_key)

    @staticmethod
    def _comment_body_preview(value: Any, limit: int = 280) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            collapsed = " ".join(value.split())
        else:
            collapsed = " ".join(json.dumps(value, ensure_ascii=False).split())
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 1].rstrip() + "…"

    def summarize_issue(
        self,
        issue: Dict[str, Any],
        *,
        include_comments: bool = False,
        comments_limit: int = 3,
    ) -> Dict[str, Any]:
        fields = issue.get("fields") or {}
        status = fields.get("status") or {}
        issue_type = fields.get("issuetype") or {}
        project = fields.get("project") or {}
        assignee = fields.get("assignee") or {}
        reporter = fields.get("reporter") or {}
        summary = {
            "id": issue.get("id"),
            "key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": status.get("name"),
            "issue_type": issue_type.get("name"),
            "project_key": project.get("key"),
            "assignee": assignee.get("displayName"),
            "reporter": reporter.get("displayName"),
            "updated": fields.get("updated"),
            "browse_url": self.browse_url(self.base_url, issue.get("key")),
        }
        if include_comments:
            comment_block = fields.get("comment") or {}
            comments = comment_block.get("comments") or []
            limited = comments[-comments_limit:] if comments_limit > 0 else comments
            summary["comment_count"] = comment_block.get("total", len(comments))
            summary["recent_comments"] = [
                {
                    "id": comment.get("id"),
                    "author": ((comment.get("author") or {}).get("displayName")),
                    "created": comment.get("created"),
                    "updated": comment.get("updated"),
                    "body_preview": self._comment_body_preview(comment.get("body")),
                }
                for comment in limited
            ]
        return summary

    def summarize_search_results(self, items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        results = [self.summarize_issue(item) for item in items]
        return {"results": results, "count": len(results)}

    def summarize_createmeta(self, data: Dict[str, Any]) -> Dict[str, Any]:
        projects = data.get("projects") or []
        summarized_projects = []
        for project in projects:
            issue_types = project.get("issuetypes") or []
            summarized_projects.append(
                {
                    "project_key": project.get("key"),
                    "project_name": project.get("name"),
                    "issue_types": [
                        {
                            "id": issue_type.get("id"),
                            "name": issue_type.get("name"),
                            "subtask": issue_type.get("subtask"),
                        }
                        for issue_type in issue_types
                    ],
                }
            )
        return {"projects": summarized_projects, "count": len(summarized_projects)}
