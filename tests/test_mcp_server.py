import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import conjira_cli

from conjira_cli.mcp_server import CommandService, command_catalog
from conjira_cli.config import ConfigError, ConfluenceSettings

HAS_MCP = sys.version_info >= (3, 10) and importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "Install the optional mcp extra on Python 3.10+")
class McpServiceTests(unittest.TestCase):
    def test_catalog_covers_every_canonical_cli_command(self):
        catalog = command_catalog()
        self.assertEqual(len(catalog), 31)
        self.assertEqual(len({item["command"] for item in catalog.values()}), 31)
        for item in catalog.values():
            self.assertFalse(
                {"token", "base_url", "env_file"}
                & set(item["input_schema"]["properties"])
            )

    def test_rejects_unknown_arguments_and_writes_before_authentication(self):
        service = CommandService()
        with mock.patch.object(service, "_context") as context:
            with self.assertRaises(ConfigError):
                service.execute(
                    "confluence_get_page", {"page_id": "1", "token": "not-a-token"}
                )
            with self.assertRaisesRegex(ConfigError, "writes are disabled"):
                service.execute(
                    "confluence_create_page",
                    {
                        "space_key": "DOCS",
                        "title": "Test",
                        "body_html": "<p>Test</p>",
                        "allow_write": True,
                    },
                )
        context.assert_not_called()

    def test_roots_block_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            service = CommandService(roots=[root])
            with self.assertRaises(ConfigError):
                service._check_path(root / ".." / "outside" / "a.md")
            try:
                (root / "link").symlink_to(outside, target_is_directory=True)
            except OSError:
                return  # Windows without symlink privileges still tested traversal.
            with self.assertRaises(ConfigError):
                service._check_path(root / "link" / "a.md")

    def test_repeated_calls_resolve_credentials_once(self):
        service = CommandService()
        settings = ConfluenceSettings(
            "https://wiki.example", "synthetic", rate_limit_enabled=False
        )
        with mock.patch(
            "conjira_cli.mcp_server.build_confluence_settings", return_value=settings
        ) as build:
            first = service._context(False)
            second = service._context(False)
        build.assert_called_once()
        self.assertIs(first[1], second[1])


@unittest.skipUnless(HAS_MCP, "Install the optional mcp extra on Python 3.10+")
class McpProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.writes = []
        self.requests = []
        self.page = {
            "id": "1",
            "type": "page",
            "title": "Demo",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "body": {"storage": {"value": "<h2>Plan</h2><p>Original</p>"}},
        }
        test = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value, status=200):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def do_GET(self):
                test.requests.append(self.path)
                path = self.path.split("?")[0]
                if path == "/rest/api/content/1":
                    self.respond(test.page)
                elif path == "/rest/api/user/current":
                    self.respond({"username": "reviewer", "displayName": "Reviewer"})
                else:
                    self.respond({"message": "Not found"}, 404)

            def do_PUT(self):
                body = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                )
                if body["version"]["number"] != test.page["version"]["number"] + 1:
                    self.respond({"message": "Conflict"}, 409)
                    return
                test.writes.append(body)
                test.page = body
                self.respond(body)

        self.api = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.thread.start()
        self.env_file = self.directory / "agent.env"
        self.env_file.write_text(
            f"CONFLUENCE_BASE_URL=http://127.0.0.1:{self.api.server_port}\nCONFLUENCE_PAT=synthetic-test-token\nCONJIRA_RATE_LIMIT_ENABLED=false\nCONFLUENCE_ALLOWED_PAGE_IDS=1\n"
        )
        self.env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONPATH": str(Path(conjira_cli.__file__).resolve().parents[1]),
            "PYTHONUNBUFFERED": "1",
        }
        if "SYSTEMROOT" in os.environ:
            self.env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def parameters(self, *extra):
        from mcp import StdioServerParameters

        return StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "conjira_cli.mcp_server",
                "--env-file",
                str(self.env_file),
                "--root",
                str(self.directory),
                *extra,
            ],
            env=self.env,
            cwd=str(self.directory),
        )

    async def test_stdio_current_protocol_read_preview_write_and_conflict(self):
        from mcp import Client

        async with Client(
            self.parameters("--allow-write"), read_timeout_seconds=15
        ) as client:
            tools = await client.list_tools()
            self.assertEqual(len(tools.tools), 31)
            read = await client.call_tool(
                "confluence_get_page_markdown", {"page_id": "1"}
            )
            self.assertFalse(read.is_error)
            self.assertIn("Original", read.structured_content["markdown"])
            args = {"page_id": "1", "heading": "Plan", "section_html": "<p>Changed</p>"}
            preview = await client.call_tool("confluence_replace_section", args)
            self.assertFalse(preview.is_error)
            self.assertTrue(preview.structured_content["dry_run"])
            self.assertEqual(len(self.writes), 0)
            result = await client.call_tool(
                "confluence_replace_section",
                {
                    **args,
                    "allow_write": True,
                    "expected_version": preview.structured_content["current_version"],
                },
            )
            self.assertFalse(result.is_error)
            self.assertEqual(len(self.writes), 1)
            self.assertEqual(self.page["version"]["number"], 8)
            conflict = await client.call_tool(
                "confluence_replace_section",
                {**args, "allow_write": True, "expected_version": 7},
            )
            self.assertTrue(conflict.is_error)
            self.assertEqual(conflict.structured_content["status_code"], 409)
            self.assertEqual(len(self.writes), 1)
            resources = await client.list_resources()
            self.assertEqual(len(resources.resources), 1)
            resource = await client.read_resource("conjira://capabilities")
            self.assertIn("0.3.0", resource.contents[0].text)
            prompt = await client.get_prompt("review-page", {"page_id": "1"})
            self.assertIn("expected_version", prompt.messages[0].content.text)

    async def test_stdio_legacy_protocol_and_error_result(self):
        from mcp import Client

        async with Client(
            self.parameters(), mode="legacy", read_timeout_seconds=15
        ) as client:
            result = await client.call_tool("confluence_get_page", {"page_id": "1"})
            self.assertFalse(result.is_error)
            blocked = await client.call_tool(
                "confluence_replace_section",
                {
                    "page_id": "1",
                    "heading": "Plan",
                    "section_html": "<p>Changed</p>",
                    "allow_write": True,
                },
            )
            self.assertTrue(blocked.is_error)
            self.assertEqual(self.writes, [])
            invalid = await client.call_tool(
                "confluence_get_page",
                {"page_id": "1", "base_url": "https://other.example"},
            )
            self.assertTrue(invalid.is_error)

    async def test_http_bearer_auth_and_sdk_roundtrip(self):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        token = "synthetic-http-token-for-tests-only-0123456789"
        token_file = self.directory / "http-token"
        token_file.write_text(token)
        params = self.parameters(
            "--transport",
            "streamable-http",
            "--port",
            str(port),
            "--http-token-file",
            str(token_file),
        )
        process = subprocess.Popen(
            [params.command, *params.args],
            cwd=params.cwd,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        url = f"http://127.0.0.1:{port}/mcp/"
        try:
            async with httpx2.AsyncClient() as http:
                for _ in range(100):
                    try:
                        response = await http.get(url)
                        if response.status_code == 401:
                            break
                    except httpx2.TransportError:
                        pass
                    await asyncio.sleep(0.05)
                else:
                    self.fail("HTTP server did not become ready")
                self.assertEqual(response.status_code, 401)
                response = await http.post(
                    url,
                    headers={
                        "Authorization": "Bearer " + token,
                        "Origin": "https://other.example",
                    },
                )
                self.assertEqual(response.status_code, 403)
            async with httpx2.AsyncClient(
                headers={"Authorization": "Bearer " + token}
            ) as http:
                async with Client(
                    streamable_http_client(url, http_client=http),
                    read_timeout_seconds=15,
                ) as client:
                    result = await client.call_tool(
                        "confluence_get_page_markdown", {"page_id": "1"}
                    )
                    self.assertFalse(result.is_error)
                    self.assertIn("Original", result.structured_content["markdown"])
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
