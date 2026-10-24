# Verification record

Observed locally on **24 October 2026**, during implementation. These are actual check results, not benchmark claims.

## Isolated automated tests

Command:

```bash
/home/tharun/hackfest-prep/.venv/bin/python -m pytest -q
```

**137 passed, 0 failed**, in **7.63 seconds** in the final regression run. Two nonfailing dependency deprecation warnings: Starlette's test client recommends `httpx2`, and pypdf deprecates the test-only `add_js` fixture helper. The application and tests use the pinned dependencies successfully.

These tests use synthetic extraction fixtures and transport mocks where isolation is needed. They test evaluator semantics, source/schema validation, API review integrity, stale results, request bounds, rejection/ambiguity, expiry, repair limits and errors. They do not establish model accuracy.

The restricted assistant sandbox blocked the test client's local event-loop communication. API tests ran successfully with permitted execution outside that sandbox. Evaluator and extraction tests also passed within it.

JavaScript syntax (`node --check app/static/app.js`), Python compilation, `pip check`, and Git whitespace checks passed. Existing MIT license content is unchanged.

## Real local model integration

Runtime: **Ollama 0.40.9**, model **gemma4:e2b**, CPU inference on the prepared laptop with approximately 16 GB RAM. Actual verified installed model digest:

```text
b37049369adfe3d2b653af0ab301a062ca5cbe96ace6aa0d3f2559ee9b563fc2
```

Command:

```bash
/home/tharun/hackfest-prep/.venv/bin/python -m scripts.verify_model
```

| Live check | Observed result | Measured pair latency |
| --- | --- | --- |
| Earlier current/proposed policies | Six expected rules, validated excerpts, titles accounted for, all five independent outcome expectations passed. Two model requests; no repair. | 88.580 seconds |
| Earlier held-out wording plus ambiguity variant | Both extracted item maximum 4, duration maximum 9, and no training prerequisite. Special consideration remained unresolved. Two model requests; no repair. | 90.258 seconds |
| Earlier live extraction through browser UI | Six expected rules; full review/evaluation/report workflow passed. Two model requests; no repair. | 86.626 seconds |

| Updated compact-output demo pair | Same six expected rules and all five independent evaluator expectations. Server attaches exact original source paragraphs. Two real requests; no repair. | 53.419 seconds |
| Updated compact-output held-out pair | Both expected rule sets preserved; special consideration unresolved and both headings correctly classified as context. Two real requests; no repair. | 53.916 seconds |
| Updated live extraction through browser UI | Larger text, clearer review actions, source highlighting, corrections, approvals, evaluation, filters, JSON download and stale-result checks all passed. Two real requests; no repair. | 53.611 seconds |

Main expected outcomes: Asha, Ravi and Kiran become disallowed; Meera remains allowed; Dev changes from allowed to Needs review. Therefore **four changed outcomes**, **one allowed under both**, **one requiring review**, across five cases.

The earlier ambiguity variant conservatively put its title into unresolved as well as its special-consideration clause; the updated compact-output variant classified the heading correctly. It did not invent an exception. The app preserves that uncertainty. Earlier development probes misread negated training or omitted title coverage; those runs were failures and were used to revise the prompt and output schema. They were not counted as successful integration checks.

Only two synthetic policy pairs and repeated demonstration calls were examined. No general accuracy, reliability percentage, or production fitness is claimed. The model verification script's auto-review fixture is a test harness, not a human approval.

## Real Chromium checks

Used installed headless Chromium through its local DevTools protocol, against the actual FastAPI application and real Gemma endpoint. No mocked API responses or replayed extraction were used for the main workflow.

Verified:

- Initial empty state has no analysis and blocks the analyze action.
- Example loading supplies actual fictional text and cases, with a real backend model indicator.
- Desktop (1440 px) and mobile (390 px) layouts have no document-wide horizontal overflow. The comparison table has its own horizontal scroll on mobile.
- The updated review screen was also checked at 320, 390, 768 and 1440 px, with no document-wide horizontal overflow. Evidence text is 16 px; the Approve reading / Edit / Reject reading controls have a visible explanation. Policy text is 15 px and the interface's body text is 16 px.
- Fresh Gemma analysis displays 7 days → 5 days, item limits and the training prerequisite change.
- Source links open a dialog, highlight and scroll to the corresponding paragraph.
- Editing a rule retains the original proposal and source, and shows reviewer modification.
- Individual review actions and context acknowledgment enable the next stage.
- Evaluating five cases produces real counts **5 / 4 / 1 / 1** and the independently expected outcomes.
- Needs-review filter isolates Dev; all-cases restores the full table.
- JSON download completes, parses correctly, and contains the server-held results and audit trail.
- Editing a request invalidates visible results and report access; editing policy text invalidates review and downstream navigation.
- No JavaScript exceptions were observed during the main workflow.
- Separate upload checks passed: invalid extension, empty file, binary control characters, oversize file, invalid UTF-8, preservation of the previous good text, valid replacement, and literal treatment of HTML text.

Two QA harness issues (DOM-object truthiness and awaiting example-loading completion) were corrected during initial verification; neither was an application failure. The updated complete browser check finished successfully, including live inference, the full review/evaluation/download path, responsive checks and file validation. Keyboard focus styles, semantic labels, reduced-motion rules and responsive behavior were inspected; this was not a full screen-reader or WCAG conformance audit.

Screenshots: [policies](policies.png), [rule review](review.png), [results](results.png), [report](report.png), [mobile policies](mobile-policies.png), [mobile results](mobile-results.png). They show fictional data and automated QA review actions from verified live inference.

## Delivery state

Application source, tests, documentation, screenshots and the submission draft are prepared. The developer has authorized committing and pushing the repository to GitHub. Repository publication is separate from hosted deployment and OrganizerHQ submission; neither of those actions is included in this authorization.

## Large-document workspace update

The current interface removes event branding and uses a navigation rail, larger reading text, highlighted text replacements and separate document/equipment workflows. UTF-8 uploads and paste now accept 2,097,152 bytes per version. A deterministic full-text comparison does not imply AI review.

The actual browser check uploaded two files over 1 MB, compared 3,500 source sections, found one added section, exercised a real selected insurance-text Gemma note, edited it with audit preservation, and downloaded the complete report. Desktop and mobile review layouts passed at 320, 390, 768 and 1440 px with no document-wide overflow. All inputs were fictional.

| Measured operation | Actual result |
| --- | --- |
| Complete text comparison of 1,715,000-byte current document against proposed text with one added section | 0.042 seconds of server comparison time; no AI call |
| Fresh selected insurance waiting-period note | 27.537 seconds; one real Gemma call, correct 30 → 60 day summary |
| Additional fresh selected documentation change, with model loaded | 16.265 seconds; one real Gemma call, correctly described the added photograph requirement |

Fresh AI inference below 15 seconds has not been established. An experimental tuple-output fast path took 42.505 seconds and produced incorrect source references; it was rejected and is not used in the application. Identical equipment inputs can now reuse prior verified inference, clearly labelled with its original timestamp and latency; no example responses are seeded, and proposals require fresh human review.

See [document-verification.json](document-verification.json), [document workspace](documents-workspace.png), [text differences](document-changes.png), [reviewed AI note](document-notes.png), and [mobile document changes](mobile-document-changes.png).

The redesigned equipment browser workflow also passed in full. Its fresh extraction took 54.843 seconds. A subsequent exact-input reuse returned in 0.026 seconds end to end, was labelled `cached-local-ollama`, made zero new model calls, and returned all review entries pending. The latest regression run passed 91 tests with zero failures.

## Readable PDF reports

Both workflows now make PDF the primary report download and keep JSON as a secondary audit export. The final PDF test suite passed **98 tests, 0 failures**. Seven new checks parse generated PDFs to verify actual contents, outcomes, source excerpts, pending/rejected/corrected review labels, literal untrusted markup, Unicode characters, all changes beyond the first UI page, long-source pagination and stale-review rejection.

The real browser check downloaded and parsed a two-page document PDF, then downloaded the secondary JSON audit export. It verified both source values, explicit absence of AI review for that comparison, and the report screen at desktop and mobile sizes. PDF rendering itself made no inference calls. Document and equipment PDF preview pages were rasterized with the installed MuPDF tool and visually inspected for readable typography, margins, tables and pagination.

The runtime adds ReportLab; the development requirements add pypdf for content verification. Fonts are bundled under their separate original license. Original application MIT license remains unchanged.

The equipment workflow also passed through live browser extraction, explicit QA review actions, deterministic evaluation and both PDF/JSON downloads. Its PDF was parsed to confirm the case results were present. No JavaScript exceptions were observed.

## Selected-change notes regression

A reported failure was reproduced on Changes 1, 2 and 3 of the fictional equipment example. The former array schema allowed only one item, so Gemma returned a note only for Change 1 in both the initial and repair responses. The application rejected these incomplete responses, but its generic error did not identify the missing changes.

The revised internal output schema requires an object property for every selected change ID. It preserves the public API shape, retains strict source validation and uses one specific, bounded repair without accumulating bad output in the 4K context. Metadata-only logging identifies future validation failures without logging policy contents.

The corrected adapter returned all three actual notes in one real Gemma call (39.014 seconds), preserving the three-to-two item limit and seven-to-five day duration. Nineteen new regression cases cover exact selection coverage, order-independent responses, missing/unknown/duplicate references, malformed or truncated JSON, invalid/blank fields, bounded repair and invalid selections. The full suite passed 117 tests with zero failures. The active comparison, existing notes and review actions were preserved during activation.

The retry through the running API also returned HTTP 200 with all three selected notes in one model call (20.178 seconds). The existing approved reading for the unselected fourth change remained intact. Public API response fields stayed compatible with the already-open browser, so re-uploading or refreshing the whole page was unnecessary.

## PDF policy input

The file picker and drag-and-drop workflow now accept `.pdf` input, with direct text paste retained. The canonical fictional current/proposed policies are also provided as `examples/old_policy.pdf` and `examples/new_policy.pdf`; their extracted text matches the adjacent `.txt` fixtures exactly after trimming the final newline. PDFs are generated from those canonical sources with `python -m scripts.build_example_pdfs`.

Real extraction tests cover both samples, the document comparison, page offsets, uppercase PDF filenames, content signatures rather than MIME-only acceptance, encrypted files, damaged files, scanned pages, mixed readable/unreadable pages, excessive page counts, decoded-stream budgets, nested indentation, worker timeout/cleanup and ignored active PDF actions. The whole suite passed **137 tests, 0 failures**.

The browser check uploaded both actual example PDFs, checked the extracted previews, compared all four source changes, downloaded a readable PDF report, verified failed-upload preservation, and checked widths 320, 390, 768 and 1440 px. No JavaScript exceptions were observed.

A separate real integration check uploaded both PDFs through the running API, performed fresh Gemma extraction (67.672 seconds, two model requests without repair), exercised review actions only in the QA harness, and produced the five independently expected outcomes. The final readable report parsed successfully with 5 pages. This verifies the fictional samples, not general PDF extraction or model accuracy. See [PDF upload verification](pdf-upload-verification.json) and [PDF upload workspace](pdf-upload-workspace.png).
