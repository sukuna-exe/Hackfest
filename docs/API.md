# Local API contract

The frontend and API share an origin. FastAPI publishes typed schemas at `/docs` and `/openapi.json`.
Every error uses `{"error":{"code":"…","message":"…","issues":[]}}` (`issues` only for input errors).

| Method / path | Input | Behavior |
| --- | --- | --- |
| GET `/api/health` | none | Checks installed Gemma 4 identity, digest and actual loaded state through Ollama. Connected means reachable and installed; loaded is separate. |
| GET `/api/examples` | none | Fictional policy text and requests. No generated analysis. |
| POST `/api/analyze` | `{current, proposed}` text | Live model extraction or explicitly labelled reuse, using compact rule values and source paragraph IDs; the server attaches verbatim paragraph evidence. Returns analysis ID, revision, source paragraphs, pending proposals, latency and model digest. |
| POST `/api/analyses/{id}/rules/{entry}/review` | `{revision, policies:{current,proposed}, action, correction?}` | Explicit accept/edit/reject per rule; acknowledge/reject per context or unresolved clause. Edit correction is `{field,operator,value}`. Server retains original evidence and review history. |
| DELETE `/api/analyses/{id}` | none | Invalidates analysis, approvals and evaluations when text changes. |
| POST `/api/evaluate` | `{analysis_id,revision,policies,cases}` | Requires completed review. Uses server-held rules only. Cases have name, nullable items_requested/days_requested/training_completed. |
| POST `/api/report` | `{evaluation_id,policies}` | Downloads the latest server-held evaluation and matching reviewed analysis. Use `?format=pdf` for PDF; JSON remains the API default for compatibility. |

An unknown case input is JSON `null`. Training rule `eq,false` explicitly means no prerequisite, not a requirement to be untrained. Limits are integers 1–365. Each policy is at most 2,097,152 UTF-8 bytes; equipment extraction accepts at most 6,500 bytes per policy to leave room in the configured 4K context. Larger files use the document-comparison endpoints below. At most 40 paragraphs and 100 cases. HTTP request bodies are capped at 16 MB. Model responses are bounded; inference has a 150-second request timeout and a 310-second total deadline. One repair per policy, no concurrent inference in this single process.

Evaluation never accepts client-supplied rule objects or approval flags. Policy hashes and a monotonically increasing server revision reject stale use. Any review mutation removes previous evaluations. Rejected rules, unresolved clauses, conflicts, missing concepts and unapproved context prevent definitive outcomes. Completed review of unresolved text permits only conservative needs-review evaluation for the affected policy.

This is a local single-user demo, not authenticated review identity. An opaque analysis ID is a capability, not a login. A caller with it can perform explicit review actions. Sessions live in memory, expire after two hours, and are limited to 64; restarting loses them. Run one Uvicorn worker bound to loopback. Do not expose this prototype as a public multi-user service.

## Document comparison API

The current upload/paste limit is **2,097,152 UTF-8 bytes (2 MB) per policy**, with a **16 MB request-body cap**. The earlier 10 KB input cap is superseded. Equipment inference retains its separate 6,500-byte / 40-paragraph context bound; it is not the large-document workflow.

| Method / path | Request | Response / behavior |
| --- | --- | --- |
| POST `/api/documents/compare` | `{current, proposed}` | Compares the entire text without a model call. Returns an opaque document ID, hashes, real counts, server comparison latency, first page of source changes, notes and explicit AI coverage. |
| GET `/api/documents/{id}/changes?offset=0&limit=20&kind=all` | Pagination/filter query | Typed source change page; max page size 50. Filters: all, added, removed, modified. |
| POST `/api/documents/{id}/notes` | `{change_ids:[...]}` | One to three distinct actual changes. Real Gemma interpretation covers only those server-held source passages. Notes start pending human review. |
| POST `/api/documents/{id}/notes/{change}/review` | `{revision, action, correction?}` | Accept, edit or reject a model note. Edits retain original proposal and source. Regeneration archives prior proposals and review history. |
| GET `/api/documents/{id}/report` | none | Downloads full original text, all changes, notes/history and explicit coverage counts. Does not imply all changes were AI-reviewed or determine coverage. |
| DELETE `/api/documents/{id}` | none | Invalidates the document comparison and notes. |

Source sections are exact source substrings bounded to 900 UTF-8 bytes. Blank-line formatting and whitespace around sections are ignored when aligning sections; the full original texts remain in the report. Up to 12,000 sections; long paragraphs are split safely. Diff alignment uses deterministic text sequence matching and positional pairing within replacement regions, not inferred legal meaning. The complete comparison is retained; page boundaries do not truncate the report.

Document sessions are in-memory, expire after two hours and are limited to 24. A document comparison ID is not an equipment analysis ID and cannot authorize deterministic eligibility evaluation.

### Labelled extraction reuse

`POST /api/analyze` may reuse a previously verified response for identical equipment policy text, prompt and verified model digest. The response has `inference.mode = cached-local-ollama`, zero new model attempts, current response latency, original generation timestamp and original inference latency. All returned proposals still require a fresh explicit review. `POST /api/analyze?fresh=true` bypasses reuse. No fixed example responses are seeded. This cache holds at most eight pairs and is cleared on restart.

## Human-readable PDF export

The website's primary action is **Download PDF report**. Both report endpoints accept `format=pdf|json`:

- `POST /api/report?format=pdf` uses the same `{evaluation_id, policies}` request and stale-review validation as JSON.
- `GET /api/documents/{id}/report?format=pdf` includes every changed section and explicit AI/human review coverage.

PDF responses use `Content-Type: application/pdf` and attachment filenames `ruletrace-report.pdf` or `ruletrace-document-report.pdf`. `format=json` and the omitted parameter retain existing JSON exports. Unsupported format values return the standard validation error.

PDF rendering runs outside the application event loop, with up to two concurrent exports. It uses an immutable copy of the validated report data, makes no inference call, and escapes policy/model/reviewer text before creating PDF paragraphs. Source tags are rendered literally rather than interpreted as markup. Report fonts are embedded for offline portability. Both PDFs and JSON obey the same expiry and revision guards.

### Exact selected-change coverage

The internal Ollama notes schema uses an object with one required property per selected change ID and disallows unselected properties. The external document API response remains unchanged. Validation rejects missing, fabricated or duplicate source keys, blank summaries, invalid attention flags and truncated output. At most one repair uses the specific failure and exact required IDs in a bounded replacement prompt. Logs contain validation codes and counts, never policy text or generated prose.

## PDF policy input

`POST /api/policies/extract` accepts multipart form data with one `file` field. It requires a nonempty `.pdf` filename and valid PDF content, at most 2,097,152 bytes and 200 pages. Text paste through existing JSON endpoints remains supported.

The typed response contains `filename`, `file_bytes`, SHA-256 of the uploaded PDF, `page_count`, `text`, `text_bytes`, `pages` (page number and start/end character offsets in extracted text), and a preview-review message. Relative indentation is preserved where the extractor can recover it. The application compares and cites this extracted text; it does not execute PDF actions or retain the uploaded binary.

The worker runs outside the API process, with a 40-second wall-clock limit, at most two imports, Linux memory/CPU limits, and an 8 MB per-page decoded content-stream budget. It rejects encrypted files, unreadable/scanned pages, excessive page counts, malformed content, oversized output and timeouts with distinct `error.code` values. No unreadable page is silently treated as an empty policy.

`GET /api/examples/current/pdf` and `GET /api/examples/proposed/pdf` download the fictional example PDFs. The same files are in `examples/old_policy.pdf` and `examples/new_policy.pdf`. Regenerate them with `python -m scripts.build_example_pdfs`.
