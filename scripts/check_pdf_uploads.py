"""Real browser PDF input, source comparison, and generated PDF report verification."""
from pathlib import Path
import tempfile

from pypdf import PdfReader

from scripts.browser_check import Browser, verify_uploads, ROOT
from scripts.check_pdf_reports import downloaded


def main():
    b=Browser();b.viewport(1440,1080)
    b.call("Page.navigate",{"url":"http://127.0.0.1:8000"})
    b.wait("document.querySelector('#file-current')?.accept.includes('.pdf')")
    for version,name in [("current","old_policy"),("proposed","new_policy")]:
        root=b.call("DOM.getDocument")["root"]["nodeId"]
        node=b.call("DOM.querySelector",{"nodeId":root,"selector":f"#file-{version}"})["nodeId"]
        b.call("DOM.setFileInputFiles",{"nodeId":node,"files":[str(ROOT/"examples"/f"{name}.pdf")]})
        b.wait(f"document.querySelector('#filename-{version}').textContent.includes('{name}.pdf')")
        b.wait("!state.busy")
        assert b.js(f"document.querySelector('#text-{version}').value")==(ROOT/"examples"/f"{name}.txt").read_text().strip()
    for width in [320,390,768,1440]:
        b.viewport(width,1080);assert not b.overflow(),f"PDF upload workspace overflow: {width}px"
    b.wait("document.querySelector('#toast').hidden")
    b.screenshot("pdf-upload-workspace.png")
    b.click("#compare-documents")
    b.wait("state.document?.summary.modified===4")
    b.wait("!state.busy")
    assert b.js("document.querySelector('#document-review-area').textContent.includes('seven days')")
    assert b.js("document.querySelector('#document-review-area').textContent.includes('five days')")
    b.click("[data-document-report]")
    b.wait("document.querySelector('#download-document-report')")
    directory=Path(tempfile.mkdtemp(prefix="ruletrace-pdf-roundtrip-"))
    b.call("Browser.setDownloadBehavior",{"behavior":"allow","downloadPath":str(directory)})
    b.click("#download-document-report")
    b.wait("document.querySelector('#toast').textContent.includes('PDF comparison report downloaded')")
    reader=PdfReader(downloaded(directory/"ruletrace-document-report.pdf"))
    text=" ".join(page.extract_text() for page in reader.pages)
    assert "seven days" in text and "five days" in text and "No AI review was requested" in text
    verify_uploads(b)
    assert not b.errors,b.errors
    print("PDF upload → extracted text → comparison → readable PDF report PASS; responsive layouts and failed-upload preservation PASS",flush=True)
    b.ws.close()


if __name__=="__main__":
    main()
