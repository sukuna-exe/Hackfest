"""Isolated, bounded PDF text extraction. PDF actions and attachments are ignored."""
from io import BytesIO
import json
import re
import sys
import textwrap

from .limits import MAX_PDF_PAGES, MAX_PDF_STREAM_BYTES, MAX_POLICY_BYTES


class ImportFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def extract_pdf(data):
    from pypdf import PdfReader
    if not data.startswith(b"%PDF-"):
        raise ImportFailure("invalid_pdf", "This file is not a valid PDF. Choose a PDF containing selectable text.")
    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ImportFailure("encrypted_pdf", "Password-protected PDFs are not supported. Upload an unlocked copy or paste the policy text.")
    count = len(reader.pages)
    if not 1 <= count <= MAX_PDF_PAGES:
        raise ImportFailure("pdf_page_limit", f"Choose a PDF with 1–{MAX_PDF_PAGES} pages.")
    parts, locations = [], []
    byte_count = char_count = 0
    for number, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > MAX_PDF_STREAM_BYTES:
            raise ImportFailure("pdf_too_complex", f"Page {number} is too complex to extract on this laptop. Export a simpler PDF or paste its text.")
        text = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False) or ""
        # Remove common layout padding while retaining relative list indentation.
        text = textwrap.dedent("\n".join(line.rstrip() for line in text.splitlines()))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            # Never silently omit an image-only or unreadable page from a policy.
            raise ImportFailure("pdf_no_text", f"Page {number} has no extractable text. Scanned or image-only PDFs need OCR; upload a text-based PDF or paste the complete policy.")
        if any(ord(c) < 32 and c not in "\n\t\r" for c in text):
            raise ImportFailure("pdf_unreadable_text", "The PDF text contains unreadable characters. Export a text-based copy or paste its text.")
        separator = "\n\n" if parts else ""
        byte_count += len((separator+text).encode("utf-8"))
        if byte_count > MAX_POLICY_BYTES:
            raise ImportFailure("pdf_text_too_large", "The extracted policy text exceeds 2 MB. Split the document into smaller policies.")
        char_count += len(separator)
        locations.append({"page":number,"start":char_count,"end":char_count+len(text)})
        char_count += len(text)
        parts.append(text)
    return {"text":"\n\n".join(parts),"page_count":count,"text_bytes":byte_count,"pages":locations}


def main():
    # Linux resource limits contain expensive/malformed content streams independently
    # of the API process. The parent also enforces a finite wall-clock deadline.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU, (25, 30))
    except ImportError:
        pass
    try:
        data = sys.stdin.buffer.read(MAX_POLICY_BYTES+1)
        if not data or len(data) > MAX_POLICY_BYTES:
            raise ImportFailure("pdf_size", "Choose a nonempty PDF up to 2 MB.")
        result = {"ok":True,"document":extract_pdf(data)}
    except ImportFailure as exc:
        result = {"ok":False,"error":{"code":exc.code,"message":exc.message}}
    except MemoryError:
        result = {"ok":False,"error":{"code":"pdf_too_complex","message":"The PDF exceeds local extraction memory limits. Export a simpler copy or paste its text."}}
    except Exception:
        result = {"ok":False,"error":{"code":"invalid_pdf","message":"The PDF is damaged or cannot be read. Export another copy or paste the policy text."}}
    sys.stdout.write(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":
    main()
