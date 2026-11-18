"""Static checks for the /admin printer picker (Bluetooth section)."""

import re
from pathlib import Path

JS = Path("static/admin/script.js")
HTML = Path("static/admin/index.html")


def _fn_body(src: str, name: str) -> str:
    start = src.index(f"function {name}")
    nxt = re.search(r"\n(async )?function ", src[start + 1 :])
    return src[start : start + 1 + nxt.start()] if nxt else src[start:]


def test_html_has_printer_block():
    html = HTML.read_text(encoding="utf-8")
    for el_id in (
        "bt-printer-current",
        "bt-printer-scan-btn",
        "bt-printer-list",
        "bt-printer-scanning",
    ):
        assert f'id="{el_id}"' in html, el_id


def test_js_scans_and_saves_printer():
    js = JS.read_text(encoding="utf-8")
    scan = _fn_body(js, "scanPrinters")
    assert "/api/printer/scan" in scan
    choose = _fn_body(js, "choosePrinter")
    assert "/api/printer/device" in choose
    assert "'PUT'" in choose
    load = _fn_body(js, "loadCurrentPrinter")
    assert "/api/printer/device" in load


def test_printer_names_rendered_as_text_only():
    # A BT advertisement name is attacker-controlled: never innerHTML it.
    js = JS.read_text(encoding="utf-8")
    row = _fn_body(js, "createPrinterItem")
    assert "textContent" in row
    assert "innerHTML" not in row


def test_printer_section_wired_into_bt_init():
    js = JS.read_text(encoding="utf-8")
    init = _fn_body(js, "initBtSection")
    assert "bt-printer-scan-btn" in init
    assert "loadCurrentPrinter()" in init
