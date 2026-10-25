#!/usr/bin/env python3
"""
playwright_funnel_harness/runner/observers/dom_mutation.py
Asset #14: Core MutationObserver Quiescence Engine.
Decouples Playwright from fragile static wait times by waiting for DOM stability.
"""

import asyncio

class DomStabilityObserver:
    def __init__(self, quiet_for_ms: int = 400, timeout_ms: int = 8000):
        self.quiet_for = quiet_for_ms
        self.timeout = timeout_ms

    async def wait_for_quiescence(self, page) -> bool:
        """
        Injects a MutationObserver into the page context. 
        Resolves when no DOM changes occur for quiet_for_ms, or throws when timeout is exceeded.
        """
        js_script = f"""
        (async () => {{
            return new Promise((resolve, reject) => {{
                let timer;
                const timeoutTimer = setTimeout(() => {{
                    observer.disconnect();
                    reject(new Error("DOM Quiescence Timeout Exceeded"));
                }}, {self.timeout});

                const observer = new MutationObserver(() => {{
                    clearTimeout(timer);
                    timer = setTimeout(() => {{
                        observer.disconnect();
                        clearTimeout(timeoutTimer);
                        resolve(true);
                    }}, {self.quiet_for});
                }});

                observer.observe(document.body, {{
                    childList: true,
                    subtree: true,
                    attributes: true,
                    characterData: true
                }});

                // Initial timer trigger
                timer = setTimeout(() => {{
                    observer.disconnect();
                    clearTimeout(timeoutTimer);
                    resolve(true);
                }}, {self.quiet_for});
            }});
        }})()
        """
        try:
            await page.evaluate(js_script)
            return True
        except Exception as e:
            if "Timeout" in str(e):
                return False
            raise e
