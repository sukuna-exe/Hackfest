"""Real browser check of large-document comparison and scoped Gemma notes."""
import json
from pathlib import Path
import time
import tempfile

from scripts.browser_check import Browser
from pypdf import PdfReader


def main():
    b=Browser()
    b.viewport(1440,1100)
    b.call("Page.navigate",{"url":"http://127.0.0.1:8000"})
    b.wait("document.querySelector('#model-label')?.textContent.includes('Connected')")
    assert not b.js("document.body.textContent.includes('HACKFEST')")
    assert b.js("document.querySelector('#compare-documents').disabled")
    old="Fictional Insurance Policy\n\nThe waiting period is 30 days.\n\nFlood damage is excluded."
    new="Fictional Insurance Policy\n\nThe waiting period is 60 days.\n\nFlood damage is excluded.\n\nClaim documentation must include photographs."
    for version,text in [("current",old),("proposed",new)]:
        b.js(f"(() => {{const e=document.querySelector('#text-{version}');e.value={json.dumps(text)};e.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
    b.screenshot("documents-workspace.png")
    b.click("#compare-documents")
    b.wait("!document.querySelector('#document-review-area').hidden")
    assert b.js("state.document.coverage.ai_reviewed_changes") == 0
    assert b.js("state.document.summary.modified") == 1
    assert b.js("state.document.summary.added") == 1
    for width in [320,390,768,1440]:
        b.viewport(width,1100)
        assert not b.overflow(),f"Document comparison overflow at {width}"
    b.viewport(1440,1100)
    b.wait("document.querySelector('#toast').hidden")
    b.screenshot("document-changes.png")
    b.click("[data-select-change]")
    b.click("#interpret-changes")
    b.wait("state.document.coverage.ai_reviewed_changes===1 || !document.querySelector('#error').hidden",seconds=310)
    assert b.js("document.querySelector('#error').hidden"),b.js("document.querySelector('#error-message').textContent")
    b.wait("!state.busy")
    note=b.js("Object.values(state.document.notes)[0]")
    assert "30" in note["original"]["summary"] and "60" in note["original"]["summary"],note
    assert note["status"]=="pending"
    b.click('[data-note-action="edit"]')
    b.wait("document.querySelector('#note-edit-dialog').open")
    b.js("document.querySelector('#note-correction').value='The stated waiting period changes from 30 to 60 days; coverage is not determined.'")
    b.click('#note-edit-form button[type="submit"]')
    b.wait("!document.querySelector('#note-edit-dialog').open")
    assert b.js("state.document.coverage.human_reviewed_notes") == 1
    b.screenshot("document-notes.png")
    b.click("[data-document-report]")
    b.wait("!document.querySelector('#document-report-area').hidden")
    download_dir=Path(tempfile.mkdtemp(prefix="ruletrace-document-downloads-"))
    b.call("Browser.setDownloadBehavior",{"behavior":"allow","downloadPath":str(download_dir)})
    b.click("#download-document-report")
    b.wait("document.querySelector('#toast').textContent.includes('downloaded')")
    time.sleep(.5)
    pdf=PdfReader(download_dir / "ruletrace-document-report.pdf")
    assert "Reviewer correction" in " ".join(page.extract_text() for page in pdf.pages)
    b.wait("!state.busy")
    b.click("#download-document-json")
    b.wait("document.querySelector('#toast').textContent.includes('JSON audit data downloaded')")
    time.sleep(.5)
    report=json.loads((download_dir / "ruletrace-document-report.json").read_text())
    assert report["coverage"]["ai_reviewed_changes"]==1 and report["coverage"]["total_changes"]==2
    assert report["policies"]["current"]==old
    print("REAL scoped Gemma note PASS",note["inference"],flush=True)
    # Direct paste retains support for large text independently of the PDF file limit.
    b.click('[data-stage="0"]')
    text=("General terms and conditions apply to this fictional policy. "*8+"\n\n")*3500
    for version,content in [("current",text),("proposed",text+"\nA new exclusion applies.")]:
        b.js(f"(() => {{const area=document.querySelector('#text-{version}');area.value={json.dumps(content)};area.dispatchEvent(new Event('input',{{bubbles:true}}));}})()")
    b.click("#compare-documents")
    b.wait("state.document && state.document.summary.current_sections===3500")
    assert b.js("state.document.summary.changed_sections")==1
    assert b.js("state.document.coverage.ai_reviewed_changes")==0
    b.viewport(390,844)
    assert not b.overflow()
    b.screenshot("mobile-document-changes.png")
    b.viewport(1440,1100)
    assert not b.errors,b.errors
    measured={"scoped_note_inference":note["inference"],"large_text":{"bytes_per_current_policy":len(text.encode()),"comparison_seconds":b.js("state.document.latency_seconds"),"current_sections":3500,"changes":1},"browser_status":"passed"}
    Path("docs/document-verification.json").write_text(json.dumps(measured,indent=2)+"\n")
    print("Large-text paste/comparison, note correction, JSON download, responsive layouts PASS",measured["large_text"],flush=True)
    b.ws.close()


if __name__=="__main__":
    main()
