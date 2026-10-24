"""Optional local Chromium CDP smoke check (requires websockets, not an app dependency).

Start Chromium with --remote-debugging-port=9223. This script uses real UI actions
and live inference, and automatically clicks review controls ONLY as a QA harness.
"""
import base64
import json
from pathlib import Path
import sys
import time
import tempfile

import httpx
from websockets.sync.client import connect
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


class Browser:
    def __init__(self):
        tabs = httpx.get("http://127.0.0.1:9223/json", trust_env=False).json()
        self.ws = connect(next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"), max_size=20_000_000, legacy=True)
        self.seq = 0
        self.errors = []
        self.call("Runtime.enable")
        self.call("Page.enable")

    def call(self, method, params=None):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            result = json.loads(self.ws.recv(timeout=30))
            if result.get("method") == "Runtime.exceptionThrown":
                self.errors.append(result["params"])
            if result.get("id") == self.seq:
                if "error" in result:
                    raise RuntimeError(result)
                return result.get("result", {})

    def js(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            raise RuntimeError(result)
        return result.get("result", {}).get("value")

    def wait(self, expression, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.js(f"Boolean({expression})"):
                return
            time.sleep(.3)
        raise AssertionError(f"Timed out: {expression}; UI error: {self.js('document.querySelector("#error-message").textContent')}")

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")

    def viewport(self, width, height):
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})

    def screenshot(self, name):
        image = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        (ROOT / "docs" / name).write_bytes(base64.b64decode(image["data"]))

    def overflow(self):
        return self.js("document.documentElement.scrollWidth > window.innerWidth")


def verify_uploads(browser):
    browser.click('[data-stage="0"]')
    browser.js("loadExample()")
    old_text = browser.js("document.querySelector('#text-current').value")
    for name, content in [("wrong.txt", "data"), ("empty.pdf", ""), ("disguised.pdf", "<script>not a PDF</script>"), ("large.pdf", "x" * (2*1024*1024+1))]:
        browser.js("document.querySelector('#file-error-current').hidden=true")
        browser.js(f"(() => {{const dt=new DataTransfer();dt.items.add(new File([{json.dumps(content)}],{json.dumps(name)},{{type:'application/pdf'}}));const input=document.querySelector('#file-current');input.files=dt.files;input.dispatchEvent(new Event('change',{{bubbles:true}}));}})()")
        browser.wait("!document.querySelector('#file-error-current').hidden")
        browser.wait("!state.busy")
        assert browser.js("document.querySelector('#text-current').value") == old_text, name
    root=browser.call("DOM.getDocument")["root"]["nodeId"]
    node=browser.call("DOM.querySelector",{"nodeId":root,"selector":"#file-current"})["nodeId"]
    browser.call("DOM.setFileInputFiles",{"nodeId":node,"files":[str(ROOT / "examples/old_policy.pdf")]})
    browser.wait("document.querySelector('#filename-current').textContent.includes('old_policy.pdf')")
    browser.wait("!state.busy")
    assert browser.js("document.querySelector('#text-current').value") == (ROOT / "examples/old_policy.txt").read_text().strip()
    browser.js("(() => {const area=document.querySelector('#text-current');area.value='<img src=x onerror=alert(1)>';area.dispatchEvent(new Event('input',{bubbles:true}));})()")
    assert not browser.js("document.querySelector('img')"), "Pasted HTML must remain text"
    browser.js("loadExample()")
    print("PDF validation PASS: extension, empty, disguised content, size, previous input preservation, real PDF extraction, literal pasted HTML", flush=True)


def main():
    browser = Browser()
    if "--uploads-only" in sys.argv:
        verify_uploads(browser)
        browser.ws.close()
        return
    browser.viewport(1440, 1120)
    browser.call("Page.navigate", {"url": "http://127.0.0.1:8000"})
    browser.wait("document.querySelector('#analyze') && document.querySelector('#model-label').textContent.includes('Connected')")
    assert not browser.js("document.querySelector('#analyze').disabled === false"), "Empty input must block analysis"
    browser.screenshot("policies-empty.png")
    assert not browser.overflow()
    browser.click("#load-example")
    browser.wait("document.querySelector('#text-current').value.includes('seven days')")
    browser.wait("document.querySelector('#toast').hidden")
    browser.screenshot("policies.png")
    browser.viewport(390, 844)
    assert not browser.overflow(), "Mobile policy page overflow"
    browser.screenshot("mobile-policies.png")
    browser.viewport(1440, 1120)
    print("Policy workspace: desktop and mobile pass", flush=True)
    browser.click("#analyze")
    browser.wait("!document.querySelector('#stage-1').hidden || !document.querySelector('#error').hidden", seconds=320)
    assert browser.js("document.querySelector('#error').hidden"), browser.js("document.querySelector('#error-message').textContent")
    browser.wait("document.querySelector('[data-action=accept]')")
    assert browser.js("document.querySelector('.review-help').textContent.includes('Gemma’s interpretation')")
    assert browser.js("parseFloat(getComputedStyle(document.querySelector('.entry-box blockquote')).fontSize) >= 16")
    assert browser.js("document.querySelector('[data-action=accept]').textContent.includes('Approve reading')")
    for width in [320, 390, 768, 1440]:
        browser.viewport(width, 1120)
        assert not browser.overflow(), f"Review workspace overflow at {width}px"
    browser.viewport(1440, 1120)
    browser.wait("document.querySelector('#toast').hidden")
    browser.screenshot("review.png")
    assert browser.js("document.querySelector('#rule-cards').textContent.includes('7 days') && document.querySelector('#rule-cards').textContent.includes('5 days')")
    browser.click(".source-link")
    browser.wait("document.querySelector('#source-dialog').open")
    assert browser.js("!!document.querySelector('.source-paragraph.highlighted')")
    browser.click('[data-close="source-dialog"]')
    # Verify editable, auditable corrections using the same intended value.
    browser.click('[data-action="edit"]')
    browser.wait("document.querySelector('#edit-dialog').open")
    browser.click('#edit-form button[type="submit"]')
    browser.wait("!document.querySelector('#edit-dialog').open")
    assert browser.js("document.querySelector('#rule-cards').textContent.includes('Reviewer edited')")
    for _ in range(30):
        selector = browser.js("(() => {const box=[...document.querySelectorAll('.entry-box,.context-entry')].find(e=>e.querySelector('.badge.pending')); return box ? (box.querySelector('[data-action=accept]') || box.querySelector('[data-action=acknowledge]')).dataset.entry : null})()")
        if not selector:
            break
        browser.click(f'[data-entry="{selector}"][data-action="accept"], [data-entry="{selector}"][data-action="acknowledge"]')
        browser.wait(f"!document.querySelector('[data-entry=\"{selector}\"]').closest('.entry-box,.context-entry').querySelector('.badge.pending')")
    assert browser.js("!document.querySelector('#to-requests').disabled"), "Review did not finish"
    browser.click("#to-requests")
    browser.wait("!document.querySelector('#stage-2').hidden")
    browser.click("#evaluate")
    browser.wait("!document.querySelector('#results').hidden")
    assert browser.js("[...document.querySelectorAll('.metric strong')].map(e=>e.textContent).join(',')") == "5,4,1,1"
    browser.wait("document.querySelector('#toast').hidden")
    browser.screenshot("results.png")
    browser.click('[data-filter="review"]')
    assert browser.js("document.querySelector('#result-rows').textContent.includes('Dev') && !document.querySelector('#result-rows').textContent.includes('Asha')")
    browser.click('[data-filter="all"]')
    browser.viewport(390, 844)
    assert not browser.overflow(), "Mobile results page overflow"
    browser.screenshot("mobile-results.png")
    browser.viewport(1440, 1120)
    browser.click("#to-report")
    browser.wait("!document.querySelector('#stage-3').hidden")
    browser.screenshot("report.png")
    download_dir=Path(tempfile.mkdtemp(prefix="ruletrace-downloads-"))
    browser.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(download_dir)})
    browser.click("#download")
    browser.wait("document.querySelector('#toast').textContent.includes('downloaded')")
    time.sleep(.5)
    pdf=PdfReader(download_dir / "ruletrace-report.pdf")
    assert "Dev" in " ".join(page.extract_text() for page in pdf.pages)
    browser.wait("!state.busy")
    browser.click("#download-json")
    browser.wait("document.querySelector('#toast').textContent.includes('JSON audit data downloaded')")
    time.sleep(.5)
    report = json.loads((download_dir / "ruletrace-report.json").read_text())
    assert report["evaluation"]["summary"]["changed"] == 4
    browser.click('[data-stage="2"]')
    browser.js("document.querySelector('#case-editor').open=true")
    browser.js("const input=document.querySelector('#case-rows input'); input.value='Edited name'; input.dispatchEvent(new Event('input',{bubbles:true}));")
    assert browser.js("document.querySelector('#results').hidden && document.querySelector('[data-stage=\"3\"]').disabled"), "Editing a case must invalidate results"
    browser.click('[data-stage="0"]')
    browser.js("const area=document.querySelector('#text-current'); area.value+='\\nEdited.'; area.dispatchEvent(new Event('input',{bubbles:true}));")
    assert browser.js("document.querySelector('[data-stage=\"1\"]').disabled && document.querySelector('[data-stage=\"2\"]').disabled"), "Policy edit must invalidate review"
    assert not browser.errors, browser.errors
    print("LIVE browser workflow PASS: inference, source highlight, edit, approvals, cases, evaluation, filters, download, stale input guards; no JS exceptions", flush=True)
    # Leave a useful clean example workspace, without pretending it has been analyzed.
    verify_uploads(browser)
    browser.ws.close()


if __name__ == "__main__":
    main()
