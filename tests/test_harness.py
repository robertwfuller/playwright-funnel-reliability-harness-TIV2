#!/usr/bin/env python3
"""
tests/test_harness.py
Scope: Canonical import verification, unit tests, and real Chromium DOM MutationObserver tests (V-04 / G-04).
"""

import asyncio
from pathlib import Path
import pytest
import playwright_funnel_harness_dom_mutation as dom_mod
from playwright_funnel_harness_dom_mutation import DomStabilityObserver


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
    playwright_async = pytest.importorskip("playwright.async_api")

    async def _run():
        async with playwright_async.async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Chromium binary not available: {exc}")
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
