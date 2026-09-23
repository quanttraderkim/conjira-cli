"""Reproducible local benchmark; no credentials or external services."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from conjira_cli.client import ConfluenceClient
from conjira_cli.operations import batch_read


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(0.04)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"id":"synthetic","title":"Demo"}')

    def log_message(self, *_):
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = ConfluenceClient(
        f"http://127.0.0.1:{server.server_port}", "synthetic", rate_limit_enabled=False
    )
    try:
        start = time.perf_counter()
        for index in range(12):
            client.get_page(str(index))
        sequential = time.perf_counter() - start
        start = time.perf_counter()
        result = batch_read(",".join(map(str, range(12))), client.get_page, workers=4)
        parallel = time.perf_counter() - start
        print(
            json.dumps(
                {
                    "environment": "localhost mock API, 40 ms response delay, rate limiting disabled",
                    "objects": 12,
                    "workers": 4,
                    "succeeded": result["succeeded"],
                    "sequential_seconds": round(sequential, 4),
                    "parallel_seconds": round(parallel, 4),
                    "speedup": round(sequential / parallel, 2),
                },
                indent=2,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
