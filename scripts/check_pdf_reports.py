"""Browser PDF/JSON download check. No model call is required for PDF export."""
import json
from pathlib import Path
import tempfile
import time

from pypdf import PdfReader

from scripts.browser_check import Browser


def downloaded(path):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if path.exists():
            return path
        time.sleep(.1)
    raise AssertionError(f"Report was not downloaded: {path}")


def main():
    b=Browser()
    directory=Path(tempfile.mkdtemp(prefix="ruletrace-pdf-check-"))
    b.call("Browser.setDownloadBehavior",{"behavior":"allow","downloadPath":str(directory)})
    b.viewport(1440,1000)
    b.call("Page.navigate",{"url":"http://127.0.0.1:8000"})
    b.wait("document.querySelector('#compare-documents')")
    for version,text in [("current","Fictional policy\n\nThe waiting period is 30 days."),("proposed","Fictional policy\n\nThe waiting period is 60 days.")]:
        b.js(f"(() => {{const e=document.querySelector('#text-{version}');e.value={json.dumps(text)};e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
    b.click("#compare-documents")
    b.wait("!document.querySelector('#document-review-area').hidden")
    b.wait("!state.busy")
    b.click("[data-document-report]")
    b.wait("document.querySelector('#download-document-report')?.textContent.includes('PDF')")
    b.click("#download-document-report")
    b.wait("document.querySelector('#toast').textContent.includes('PDF comparison report downloaded')")
    path=downloaded(directory/"ruletrace-document-report.pdf")
    reader=PdfReader(path)
    text=" ".join(page.extract_text() for page in reader.pages)
    assert "30 days" in text and "60 days" in text and "No AI review was requested" in text
    b.wait("!state.busy")
    b.click("#download-document-json")
    b.wait("document.querySelector('#toast').textContent.includes('JSON audit data downloaded')")
    audit=json.loads(downloaded(directory/"ruletrace-document-report.json").read_text())
    assert audit["coverage"]["ai_reviewed_changes"]==0
    b.wait("document.querySelector('#toast').hidden")
    b.screenshot("pdf-report-screen.png")
    b.viewport(390,844)
    assert not b.overflow(),"Report screen overflow on mobile"
    b.screenshot("mobile-pdf-report-screen.png")
    assert not b.errors,b.errors
    print(f"PDF primary download and optional JSON audit export PASS; {len(reader.pages)} PDF pages; files: {directory}",flush=True)
    b.ws.close()


if __name__=="__main__":
    main()
