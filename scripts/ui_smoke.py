"""End-to-end UI smoke test with Playwright (headless Chromium).

Starts the Streamlit app on a spare port, drives the demo flow, asserts the key
outcomes and saves screenshots to docs/screenshots/.

Flow: load rules (AI if a key is set, otherwise the labelled offline demo) -> build
-> expect "0 rule violations" -> report an absence -> expect a repair message.
With a key it also adds an impossible rule and expects the conflict card.

Usage: python scripts/ui_smoke.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
PORT = 8765


def wait_port(port: int, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError("streamlit did not start")


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from novbe import llm

    has_key = llm.available()
    SHOTS.mkdir(parents=True, exist_ok=True)
    exe = Path(sys.executable).with_name("streamlit.exe" if os.name == "nt" else "streamlit")
    proc = subprocess.Popen([str(exe), "run", "app.py", "--server.port", str(PORT), "--server.headless", "true"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    try:
        wait_port(PORT)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 2600}, device_scale_factor=1.25)
            page.goto(f"http://127.0.0.1:{PORT}")
            expect(page.get_by_text("Team and rules")).to_be_visible(timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=SHOTS / "1_input.png", full_page=True)

            if has_key:
                page.get_by_role("button", name="Read the rules").click()
            else:
                page.get_by_role("button", name="Offline demo").click()
            expect(page.get_by_text("Check what was understood")).to_be_visible(timeout=120000)
            expect(page.get_by_text("Needs your answer")).to_be_visible()
            checks.append("rules read; ambiguous sentence surfaced")
            page.wait_for_timeout(1500)
            page.screenshot(path=SHOTS / "2_confirm.png", full_page=True)

            page.get_by_role("button", name="Build schedule").click()
            expect(page.get_by_text("0 rule violations — independent check")).to_be_visible(timeout=120000)
            checks.append("schedule built; independent check reports 0 violations")
            page.wait_for_timeout(1500)
            page.screenshot(path=SHOTS / "3_schedule.png", full_page=True)
            grid = page.locator(".nv-scroll")
            grid.scroll_into_view_if_needed()
            grid.screenshot(path=SHOTS / "grid.png")

            page.get_by_role("button", name="Repair").click()
            expect(page.get_by_text("Repair done.")).to_be_visible(timeout=120000)
            expect(page.get_by_text("0 rule violations — independent check")).to_be_visible()
            checks.append("absence repaired; still 0 violations")
            page.wait_for_timeout(1500)
            page.locator(".nv-scroll").screenshot(path=SHOTS / "4_repair_grid.png")

            mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
            mobile.goto(f"http://127.0.0.1:{PORT}")
            expect(mobile.get_by_text("Team and rules")).to_be_visible(timeout=60000)
            mobile.wait_for_timeout(1500)
            overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            mobile.screenshot(path=SHOTS / "mobile.png", full_page=False)
            checks.append(f"mobile 390px: horizontal page overflow = {overflow}")

            if has_key:
                page.get_by_role("button", name="Add a clash").click()
                page.wait_for_timeout(1000)
                page.get_by_role("button", name="Read the rules").click()
                expect(page.get_by_text("Check what was understood")).to_be_visible(timeout=120000)
                page.get_by_role("button", name="Build schedule").click()
                expect(page.get_by_text("These rules cannot all be true at once")).to_be_visible(timeout=120000)
                checks.append("impossible rule -> conflict card shown")
                page.wait_for_timeout(1500)
                page.screenshot(path=SHOTS / "5_conflict.png", full_page=True)
            browser.close()
    finally:
        proc.terminate()
    for c in checks:
        print("PASS", c)
    print(f"screenshots in {SHOTS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
