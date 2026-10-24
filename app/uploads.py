"""PDF input transport; extraction never runs inside the application process."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from fastapi import APIRouter, File, UploadFile
from pydantic import Field

from .extraction import TraceError
from .limits import MAX_POLICY_BYTES, PDF_IMPORT_TIMEOUT_SECONDS
from .schemas import PolicyInputs, StrictModel

router = APIRouter(prefix="/api/policies", tags=["PDF policy uploads"])
_active_imports = 0


class PdfPageLocation(StrictModel):
    page: int
    start: int
    end: int


class PdfImport(StrictModel):
    filename: str
    file_bytes: int
    sha256: str
    page_count: int
    text: str = Field(max_length=MAX_POLICY_BYTES)
    text_bytes: int
    pages: list[PdfPageLocation]
    message: str = "Review the extracted text before comparing. PDF reading order and table formatting can differ from the original."


async def extract_in_worker(data):
    global _active_imports
    if _active_imports >= 2:
        raise TraceError("pdf_import_busy", "Two PDFs are being read. Wait briefly and retry.", 409)
    _active_imports += 1
    process = None
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.pdf_import_worker",
            cwd=str(Path(__file__).resolve().parents[1]),
            env={"PATH":os.defpath,"PYTHONIOENCODING":"utf-8","LANG":"C.UTF-8"},
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:
            output,_ = await asyncio.wait_for(process.communicate(data),timeout=PDF_IMPORT_TIMEOUT_SECONDS)
        except TimeoutError:
            raise TraceError("pdf_import_timeout", "PDF extraction timed out. Upload a simpler PDF or paste its text.", 422)
        if process.returncode != 0 or len(output) > 8*1024*1024:
            raise TraceError("pdf_too_complex", "The PDF exceeds local extraction limits. Export a simpler copy or paste its text.")
        try:
            result=json.loads(output)
        except (ValueError,TypeError):
            raise TraceError("invalid_pdf", "The PDF could not be read. Export another copy or paste the policy text.")
        if not result.get("ok"):
            error=result.get("error",{})
            raise TraceError(error.get("code","invalid_pdf"),error.get("message","The PDF could not be read."))
        return result["document"]
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.communicate()
        _active_imports -= 1


@router.post("/extract", response_model=PdfImport)
async def extract_policy(file: UploadFile = File(...)):
    filename=(file.filename or "").replace("\\","/").rsplit("/",1)[-1]
    try:
        if not filename.lower().endswith(".pdf"):
            raise TraceError("pdf_required", "Choose a .pdf policy file. You can paste plain text directly into the editor.")
        data=await file.read(MAX_POLICY_BYTES+1)
        if not data:
            raise TraceError("empty_pdf", "The PDF is empty. Choose a PDF containing selectable policy text.")
        if len(data)>MAX_POLICY_BYTES:
            raise TraceError("pdf_size", "Each PDF must be at most 2 MB.",413)
    finally:
        await file.close()
    document=await extract_in_worker(data)
    # Reuse the same UTF-8, binary-character and byte-size validation as pasted text.
    validated=PolicyInputs(current=document["text"],proposed=document["text"])
    return PdfImport(filename=filename,file_bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                     **{**document,"text":validated.current})
