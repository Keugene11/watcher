import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import common
import dashboard


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.H)
    port = srv.server_address[1]
    dashboard.PORT = port
    dashboard.ALLOWED_HOSTS = {f"127.0.0.1:{port}", f"localhost:{port}"}
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield port
    srv.shutdown()


def req(port, method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read().decode(), dict(r.getheaders())


def test_page_and_state(server):
    s, body, h = req(server, "GET", "/")
    assert s == 200 and "<title>Watcher</title>" in body
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    s, body, _ = req(server, "GET", "/api/state")
    assert s == 200 and json.loads(body)["status"] in ("watching", "paused", "stopped")


def test_unknown_path_404(server):
    assert req(server, "GET", "/etc/passwd")[0] == 404


def test_dns_rebinding_blocked(server):
    s, _, _ = req(server, "GET", "/api/state", {"Host": "evil.example:%d" % server})
    assert s == 403


def test_csrf_post_without_header_blocked(server):
    con = common.db()
    common.meta_set(con, "paused", 0)
    # what a cross-site <form> or fetch(no-cors) can send: no custom header
    s, _, _ = req(server, "POST", "/api/pause", {"Origin": "https://evil.example"})
    assert s == 403
    s, _, _ = req(server, "POST", "/api/pause", {})
    assert s == 403
    assert common.meta_get(con, "paused") == "0"


def test_cross_origin_with_header_blocked(server):
    s, _, _ = req(server, "POST", "/api/pause", {"X-Watcher": "1", "Origin": "https://evil.example"})
    assert s == 403


def test_pause_resume_check(server):
    con = common.db()
    h = {"X-Watcher": "1", "Origin": f"http://127.0.0.1:{server}"}
    assert req(server, "POST", "/api/pause", h)[0] == 200
    assert common.meta_get(con, "paused") == "1"
    assert req(server, "POST", "/api/resume", h)[0] == 200
    assert common.meta_get(con, "paused") == "0"
    assert req(server, "POST", "/api/check", h)[0] == 200
    assert common.meta_get(con, "force_check") == "1"
    common.meta_set(con, "force_check", 0)


def test_binds_loopback_only():
    src = open(dashboard.__file__, encoding="utf-8").read()
    assert 'ThreadingHTTPServer(("127.0.0.1", PORT)' in src
