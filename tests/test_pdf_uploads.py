"""Real PDF parsing tests; no model calls or mocked extraction text."""
import asyncio
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
import pytest

from app import main, uploads
from app.extraction import TraceError
from app.limits import MAX_PDF_PAGES, MAX_POLICY_BYTES
from app.pdf_import_worker import ImportFailure, extract_pdf

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def post_pdf(client,data,filename="policy.pdf",mime="application/pdf"):
    return client.post("/api/policies/extract",files={"file":(filename,data,mime)})


@pytest.mark.parametrize("name",["old_policy","new_policy"])
def test_example_pdf_extraction_roundtrips_the_canonical_policy(client,name):
    data=(ROOT/"examples"/f"{name}.pdf").read_bytes()
    response=post_pdf(client,data,f"{name}.pdf")
    assert response.status_code==200,response.text
    result=response.json()
    assert result["text"]==(ROOT/"examples"/f"{name}.txt").read_text().strip()
    assert result["page_count"]==1 and result["file_bytes"]==len(data)
    assert result["text_bytes"]==len(result["text"].encode())
    assert result["text"][result["pages"][0]["start"]:result["pages"][0]["end"]]==result["text"]


def test_pdf_inputs_feed_the_existing_document_comparison(client):
    texts={version:post_pdf(client,(ROOT/"examples"/f"{name}_policy.pdf").read_bytes()).json()["text"]
           for version,name in [("current","old"),("proposed","new")]}
    response=client.post("/api/documents/compare",json=texts)
    assert response.status_code==200
    assert response.json()["summary"]["modified"]==4
    assert response.json()["coverage"]["ai_reviewed_changes"]==0


@pytest.mark.parametrize("version,name",[("current","old_policy"),("proposed","new_policy")])
def test_example_pdfs_can_be_downloaded_from_the_app(client,version,name):
    response=client.get(f"/api/examples/{version}/pdf")
    assert response.status_code==200 and response.headers["content-type"]=="application/pdf"
    assert response.content==(ROOT/"examples"/f"{name}.pdf").read_bytes()


@pytest.mark.parametrize("filename,data,status,code",[
    ("policy.txt",b"Not a PDF",422,"pdf_required"),
    ("empty.pdf",b"",422,"empty_pdf"),
    ("disguised.pdf",b"<script>alert('no')</script>",422,"invalid_pdf"),
    ("broken.pdf",b"%PDF-1.7\nmalformed",422,"invalid_pdf"),
    ("oversized.pdf",b"%PDF-"+b"x"*MAX_POLICY_BYTES,413,"pdf_size"),
])
def test_bad_uploads_have_distinct_clear_errors(client,filename,data,status,code):
    response=post_pdf(client,data,filename)
    assert response.status_code==status,response.text
    assert response.json()["error"]["code"]==code


def test_actual_pdf_content_is_required_even_with_correct_mime(client):
    response=post_pdf(client,b"arbitrary text",mime="application/pdf")
    assert response.status_code==422 and response.json()["error"]["code"]=="invalid_pdf"
    valid=(ROOT/"examples/old_policy.pdf").read_bytes()
    assert post_pdf(client,valid,"POLICY.PDF","application/octet-stream").status_code==200


def test_encrypted_pdf_is_not_silently_treated_as_empty(client):
    writer=PdfWriter(clone_from=PdfReader(ROOT/"examples/old_policy.pdf"))
    writer.encrypt("test-only-pdf-password")
    output=BytesIO();writer.write(output)
    response=post_pdf(client,output.getvalue())
    assert response.status_code==422 and response.json()["error"]["code"]=="encrypted_pdf"


def test_scanned_page_is_rejected_with_ocr_message(client):
    output=BytesIO();pdf=canvas.Canvas(output)
    pdf.drawImage(ImageReader(Image.new("RGB",(30,30),"white")),30,30,100,100)
    pdf.save()
    response=post_pdf(client,output.getvalue())
    assert response.status_code==422 and response.json()["error"]["code"]=="pdf_no_text"
    assert "OCR" in response.json()["error"]["message"]


def test_mixed_pdf_does_not_silently_skip_an_unreadable_page(client):
    writer=PdfWriter(clone_from=PdfReader(ROOT/"examples/old_policy.pdf"))
    writer.add_blank_page(width=595,height=842)
    output=BytesIO();writer.write(output)
    response=post_pdf(client,output.getvalue())
    assert response.status_code==422 and "Page 2" in response.json()["error"]["message"]


def test_many_pages_are_bounded_before_text_extraction(client):
    writer=PdfWriter()
    for _ in range(MAX_PDF_PAGES+1):
        writer.add_blank_page(width=595,height=842)
    output=BytesIO();writer.write(output)
    response=post_pdf(client,output.getvalue())
    assert response.status_code==422 and response.json()["error"]["code"]=="pdf_page_limit"


def test_active_pdf_actions_are_not_executed(client):
    writer=PdfWriter(clone_from=PdfReader(ROOT/"examples/old_policy.pdf"))
    writer.add_js("app.alert('This must never execute');")
    output=BytesIO();writer.write(output)
    response=post_pdf(client,output.getvalue())
    assert response.status_code==200
    assert response.json()["text"]==(ROOT/"examples/old_policy.txt").read_text().strip()


def test_page_text_offsets_are_preserved(client):
    writer=PdfWriter()
    for name in ["old_policy","new_policy"]:
        writer.append(PdfReader(ROOT/"examples"/f"{name}.pdf"))
    output=BytesIO();writer.write(output)
    response=post_pdf(client,output.getvalue()).json()
    assert response["page_count"]==2
    for location,name in zip(response["pages"],["old_policy","new_policy"]):
        assert response["text"][location["start"]:location["end"]]==(ROOT/"examples"/f"{name}.txt").read_text().strip()


def test_content_stream_budget(monkeypatch):
    monkeypatch.setattr("app.pdf_import_worker.MAX_PDF_STREAM_BYTES",10)
    with pytest.raises(ImportFailure) as exc:
        extract_pdf((ROOT/"examples/old_policy.pdf").read_bytes())
    assert exc.value.code=="pdf_too_complex"


def test_relative_indentation_is_not_flattened(client):
    output=BytesIO();pdf=canvas.Canvas(output)
    pdf.drawString(72,740,"Main policy condition applies.")
    pdf.drawString(108,716,"Exception: review the additional condition.")
    pdf.save()
    result=post_pdf(client,output.getvalue()).json()
    lines=[line for line in result["text"].splitlines() if line.strip()]
    assert lines[0].startswith("Main policy")
    assert lines[1].startswith(" ") and "Exception:" in lines[1]


def test_pdf_worker_timeout_kills_and_reaps_child(monkeypatch):
    class Worker:
        returncode=None
        killed=False
        async def communicate(self,data=None):
            if data is None:
                self.returncode=-9
                return b"",b""
            await asyncio.Event().wait()
        def kill(self):
            self.killed=True
    worker=Worker()
    async def start(*args,**kwargs):return worker
    monkeypatch.setattr(uploads.asyncio,"create_subprocess_exec",start)
    monkeypatch.setattr(uploads,"PDF_IMPORT_TIMEOUT_SECONDS",.01)
    with pytest.raises(TraceError) as exc:
        asyncio.run(uploads.extract_in_worker(b"%PDF-test"))
    assert exc.value.code=="pdf_import_timeout" and worker.killed and uploads._active_imports==0
