# Fictional demonstration policies

Upload these PDF files into RuleTrace's two policy panels:

- [old_policy.pdf](old_policy.pdf) → **Current policy**.
- [new_policy.pdf](new_policy.pdf) → **Proposed policy**.

They contain selectable text and match the adjacent `.txt` source files. All policies and request names are fictional.

After uploading, check the extracted text. Choose **Compare documents** for text changes and selected Gemma notes, or **Extract equipment rules** for the reviewed borrowing-request evaluation demo.

Regenerate the PDFs after changing the canonical example text:

```bash
python -m scripts.build_example_pdfs
```

Scanned/image-only, unreadable, and password-protected PDFs are rejected rather than treated as complete policy text. You can also paste policy text directly into either editor.
