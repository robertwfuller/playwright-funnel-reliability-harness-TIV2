#!/usr/bin/env python3
"""
stress_test/funnel_stress_test.py
Scope: Deterministic Playwright route & popup validator with strict non-zero exit codes on failure (R-06 / V-06 / G-06).
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DEFAULT_BASE_URL = os.environ.get("TARGET_URL", "https://thoughtfulinnovations.com")
DEFAULT_ROUTES = ["/", "/business-diagnostic", "/the-trust-engine"]
POPUP_WAIT_TIMEOUT = int(os.environ.get("POPUP_WAIT_TIMEOUT_MS", "10000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def run_route_check(browser, base_url: str, route: str, timeout_ms: int) -> dict:
    target = f"{base_url.rstrip('/')}{route}" if base_url.startswith("http") else f"{base_url}{route}"
    logging.info("Testing Route: %s", target)
    ctx = browser.new_context()
    page = ctx.new_page()
    start_ts = time.time()
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=15000)
        dialog = page.query_selector("dialog.ti-report-popup")
        if not dialog:
            msg = f"'dialog.ti-report-popup' missing from DOM on {route}"
            logging.error("  [FAIL] %s", msg)
            return {"route": route, "url": target, "passed": False, "error": msg, "elapsed_ms": int((time.time() - start_ts) * 1000)}

        page.wait_for_selector("dialog.ti-report-popup[open]", state="visible", timeout=timeout_ms)
        logging.info("  [PASS] Popup auto-opened cleanly ([open] state verified)")
        return {"route": route, "url": target, "passed": True, "error": None, "elapsed_ms": int((time.time() - start_ts) * 1000)}
    except PlaywrightTimeoutError:
        msg = f"Timed out waiting for [open] state on {route}"
        logging.error("  [FAIL] %s", msg)
        return {"route": route, "url": target, "passed": False, "error": msg, "elapsed_ms": int((time.time() - start_ts) * 1000)}
    except Exception as e:
        msg = f"Error on {route}: {e}"
        logging.error("  [FAIL] %s", msg)
        return {"route": route, "url": target, "passed": False, "error": msg, "elapsed_ms": int((time.time() - start_ts) * 1000)}
    finally:
        ctx.close()


def main():
    parser = argparse.ArgumentParser(description="Deterministic Funnel Entry Validator")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL to test")
    parser.add_argument("--routes", nargs="+", default=DEFAULT_ROUTES, help="Deterministic list of routes")
    parser.add_argument("--timeout-ms", type=int, default=POPUP_WAIT_TIMEOUT, help="Popup wait timeout in ms")
    parser.add_argument("--output-json", default="", help="Optional path to write JSON report")
    args = parser.parse_args()

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=os.environ.get("HEADLESS", "true").lower() != "false")
        try:
            for route in args.routes:
                results.append(run_route_check(browser, args.base_url, route, args.timeout_ms))
        finally:
            browser.close()

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "total_routes": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nCompleted: {passed}/{len(results)} routes passed.")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
