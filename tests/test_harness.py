#!/usr/bin/env python3
"""
tests/test_harness.py
Scope: Canonical import verification, unit tests, required fail-closed Chromium DOM MutationObserver tests,
and deterministic route runner exit-code + JSON artifact tests (Task 2: V-02 / G-02).
"""

import asyncio
import http.server
import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
import pytest
from playwright.async_api import async_playwright
import playwright_funnel_harness_dom_mutation as dom_mod
from playwright_funnel_harness_dom_mutation import DomStabilityObserver

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER_SCRIPT = REPO_ROOT / "stress_test" / "funnel_stress_test.py"


class MockPage:
    def __init__(self, error_to_raise=None):
        self.error_to_raise = error_to_raise
        self.evaluated_scripts = []

    async def evaluate(self, js_script):
        self.evaluated_scripts.append(js_script)
        if self.error_to_raise:
            raise self.error_to_raise
        return True


def test_canonical_import_is_from_src():
    resolved = Path(dom_mod.__file__).resolve()
    assert "src" in resolved.parts, f"Shadowing detected! Imported from {resolved}"


def test_unit_quiescence_success():
    observer = DomStabilityObserver(quiet_for_ms=250, timeout_ms=2000)
    page = MockPage()
    assert asyncio.run(observer.wait_for_quiescence(page)) is True
    assert "250" in page.evaluated_scripts[0]
    assert "2000" in page.evaluated_scripts[0]


def test_unit_quiescence_timeout_returns_false():
    observer = DomStabilityObserver(quiet_for_ms=250, timeout_ms=500)
    page = MockPage(error_to_raise=Exception("DOM Quiescence Timeout Exceeded"))
    assert asyncio.run(observer.wait_for_quiescence(page)) is False


def test_unit_unexpected_error_propagates():
    observer = DomStabilityObserver(quiet_for_ms=250, timeout_ms=500)
    page = MockPage(error_to_raise=RuntimeError("Target page, context or browser has been closed"))
    with pytest.raises(RuntimeError, match="closed"):
        asyncio.run(observer.wait_for_quiescence(page))


def test_real_browser_dom_stability_cases():
    """
    Fail-closed real Chromium verification (no pytest.skip).
    Exercises static pages, delayed mutations, and sustained mutations exceeding timeout.
    """
    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                # 1. Static page settles after quiet_for_ms
                await page.set_content("<html><body><div id='app'>Ready</div></body></html>")
                obs_fast = DomStabilityObserver(quiet_for_ms=150, timeout_ms=1500)
                assert await obs_fast.wait_for_quiescence(page) is True

                # 2. Delayed mutations settle before timeout
                await page.set_content("""
                <html><body><div id='log'></div><script>
                  let count = 0;
                  const iv = setInterval(() => {
                    const el = document.createElement('span');
                    el.textContent = 'm' + (++count);
                    document.getElementById('log').appendChild(el);
                    if (count >= 4) clearInterval(iv);
                  }, 50);
                </script></body></html>
                """)
                obs_delayed = DomStabilityObserver(quiet_for_ms=160, timeout_ms=2000)
                assert await obs_delayed.wait_for_quiescence(page) is True

                # 3. Sustained mutations exceed timeout and return False
                await page.set_content("""
                <html><body><div id='noisy'></div><script>
                  setInterval(() => {
                    document.getElementById('noisy').setAttribute('data-ts', String(Date.now() + Math.random()));
                  }, 25);
                </script></body></html>
                """)
                obs_timeout = DomStabilityObserver(quiet_for_ms=200, timeout_ms=450)
                assert await obs_timeout.wait_for_quiescence(page) is False
            finally:
                await browser.close()

    asyncio.run(_run())


def test_route_runner_deterministic_pass_and_fail_json(tmp_path):
    """
    Verifies that stress_test/funnel_stress_test.py deterministically visits every configured route,
    writes structured JSON artifacts, exits 0 when all routes pass, and exits 1 when any route fails.
    """
    pass_html = b"<!DOCTYPE html><html><body><dialog class='ti-report-popup' open>OK</dialog></body></html>"
    fail_html = b"<!DOCTYPE html><html><body><div>Missing dialog</div></body></html>"

    class LocalHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if self.path == "/missing-popup":
                self.wfile.write(fail_html)
            else:
                self.wfile.write(pass_html)

        def log_message(self, format, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), LocalHandler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"

        try:
            # 1. Passing run across 3 deterministic routes
            pass_json = tmp_path / "pass_report.json"
            res_pass = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_SCRIPT),
                    "--base-url", base_url,
                    "--routes", "/", "/business-diagnostic", "/the-trust-engine",
                    "--timeout-ms", "1500",
                    "--output-json", str(pass_json),
                ],
                capture_output=True,
                text=True,
            )
            assert res_pass.returncode == 0, f"Expected 0, got {res_pass.returncode}: {res_pass.stderr}"
            data_pass = json.loads(pass_json.read_text(encoding="utf-8"))
            assert data_pass["total_routes"] == 3
            assert data_pass["passed"] == 3
            assert data_pass["failed"] == 0
            assert [r["route"] for r in data_pass["results"]] == ["/", "/business-diagnostic", "/the-trust-engine"]

            # 2. Failing run when a route is missing the popup
            fail_json = tmp_path / "fail_report.json"
            res_fail = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_SCRIPT),
                    "--base-url", base_url,
                    "--routes", "/", "/missing-popup",
                    "--timeout-ms", "1000",
                    "--output-json", str(fail_json),
                ],
                capture_output=True,
                text=True,
            )
            assert res_fail.returncode == 1, f"Expected 1, got {res_fail.returncode}"
            data_fail = json.loads(fail_json.read_text(encoding="utf-8"))
            assert data_fail["total_routes"] == 2
            assert data_fail["passed"] == 1
            assert data_fail["failed"] == 1
        finally:
            httpd.shutdown()
