# Playwright Funnel Reliability Harness

A Playwright test harness for funnel pages that waits for DOM mutation quiescence (`MutationObserver`) and deterministically validates entry routes.

## Implemented Capabilities
* **DOM Mutation Quiescence (`DomStabilityObserver` in `src/playwright_funnel_harness_dom_mutation.py`):** Injects a `MutationObserver` on `document.body` and resolves when no DOM changes occur for `quiet_for_ms`, or returns `False` on timeout.
* **Deterministic Route Runner (`stress_test/funnel_stress_test.py`):** Iterates through all configured routes deterministically, ensures browser contexts close on every path, writes optional JSON artifacts, and exits with a non-zero status code when any required route check fails.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
pytest -v
```
