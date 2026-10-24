"""Human-readable PDFs from validated report snapshots; no inference or HTML input."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_active_exports = 0


async def pdf_response(builder, snapshot, filename):
    """Bound concurrent PDF work and keep it off the application's event loop."""
    from fastapi.responses import Response
    from starlette.concurrency import run_in_threadpool
    from .extraction import TraceError
    global _active_exports
    if _active_exports >= 2:
        raise TraceError("pdf_busy", "Two PDF reports are already being prepared. Try again shortly.", 409)
    _active_exports += 1
    try:
        content = await run_in_threadpool(builder, snapshot)
        return Response(content, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})
    finally:
        _active_exports -= 1


FONT_DIR = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("RuleTrace", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("RuleTrace-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("RuleTrace", normal="RuleTrace", bold="RuleTrace-Bold")
NAVY = colors.HexColor("#14243a")
BLUE = colors.HexColor("#315e91")
MUTED = colors.HexColor("#52647a")
BORDER = colors.HexColor("#d2dce8")
WIDTH = A4[0] - 88
LABELS = {"items_requested": "Equipment items", "days_requested": "Borrowing duration", "training_completed": "Training prerequisite"}
STATUSES = {"pending": "Awaiting human review", "accepted": "Approved reading", "edited": "Corrected by reviewer", "rejected": "Rejected reading", "acknowledged": "Acknowledged"}


def timestamp(value):
    if not value:
        return "Not recorded"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, TypeError):
        return str(value)


def safe_text(value):
    # Policy/model/reviewer text is escaped before entering ReportLab's markup parser.
    text = "".join(c for c in str(value) if ord(c) >= 32 or c in "\n\t")
    return escape(text).replace("\n", "<br/>").replace("\t", "    ")


class ReadableReport:
    def __init__(self, title, subtitle):
        self.title = title
        self.story = []
        base = dict(fontName="RuleTrace", fontSize=10.3, leading=16, textColor=NAVY,
                    spaceAfter=9, alignment=TA_LEFT, splitLongWords=True)
        self.styles = {
            "body": ParagraphStyle("body", **base),
            "title": ParagraphStyle("title", fontName="RuleTrace-Bold", fontSize=27, leading=33, textColor=NAVY, spaceAfter=12),
            "section": ParagraphStyle("section", fontName="RuleTrace-Bold", fontSize=15, leading=21, textColor=NAVY, spaceBefore=22, spaceAfter=11, keepWithNext=True),
            "subhead": ParagraphStyle("subhead", fontName="RuleTrace-Bold", fontSize=11, leading=17, textColor=BLUE, spaceBefore=12, spaceAfter=6, keepWithNext=True),
            "small": ParagraphStyle("small", fontName="RuleTrace", fontSize=8.7, leading=13, textColor=MUTED, spaceAfter=7, splitLongWords=True),
            "source": ParagraphStyle("source", **{**base, "fontSize": 9.8, "leading": 15, "leftIndent": 11, "rightIndent": 11, "backColor": colors.HexColor("#f0f5fb"), "borderPadding": 9, "spaceBefore": 5, "spaceAfter": 13}),
            "table": ParagraphStyle("table", fontName="RuleTrace", fontSize=8.7, leading=13, textColor=NAVY, spaceAfter=0, splitLongWords=True),
            "table_head": ParagraphStyle("table_head", fontName="RuleTrace-Bold", fontSize=8.7, leading=13, textColor=colors.white, spaceAfter=0),
            "metric": ParagraphStyle("metric", fontName="RuleTrace-Bold", fontSize=23, leading=29, textColor=BLUE, spaceAfter=4),
        }
        self.add("POLICY INTELLIGENCE / RULETRACE AI", "small")
        self.add(title, "title")
        self.add(subtitle)
        self.add(f"Report generated {timestamp(datetime.now(timezone.utc).isoformat())}", "small")
        self.story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceBefore=8, spaceAfter=13))

    def paragraph(self, text, style="body"):
        return Paragraph(safe_text(text), self.styles[style])

    def add(self, text, style="body"):
        self.story.append(self.paragraph(text, style))

    def section(self, text):
        self.add(text, "section")

    def metrics(self, values):
        cells = [[self.paragraph(str(value), "metric"), self.paragraph(label, "small")] for label, value in values]
        table = Table([cells], colWidths=[WIDTH/len(cells)]*len(cells), hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1),colors.HexColor("#eef4fb")),
            ("VALIGN", (0,0),(-1,-1),"TOP"), ("BOX", (0,0),(-1,-1),.6,BORDER),
            ("INNERGRID", (0,0),(-1,-1),.5,BORDER), ("LEFTPADDING",(0,0),(-1,-1),13),
            ("RIGHTPADDING",(0,0),(-1,-1),13), ("TOPPADDING",(0,0),(-1,-1),12), ("BOTTOMPADDING",(0,0),(-1,-1),8)]))
        self.story.extend([table, Spacer(1, 13)])

    def table(self, headers, rows, fractions):
        data = [[self.paragraph(h, "table_head") for h in headers]]
        data += [[self.paragraph(value, "table") for value in row] for row in rows]
        table = Table(data, colWidths=[WIDTH*f for f in fractions], repeatRows=1, hAlign="LEFT", splitInRow=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),NAVY),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f3f6fa")]),
            ("VALIGN",(0,0),(-1,-1),"TOP"), ("BOX",(0,0),(-1,-1),.5,BORDER),
            ("LINEBELOW",(0,0),(-1,0),1,BLUE), ("LINEBELOW",(0,1),(-1,-1),.35,BORDER),
            ("LEFTPADDING",(0,0),(-1,-1),9), ("RIGHTPADDING",(0,0),(-1,-1),9),
            ("TOPPADDING",(0,0),(-1,-1),9), ("BOTTOMPADDING",(0,0),(-1,-1),9)]))
        self.story.extend([table, Spacer(1, 8)])

    def source(self, version, ref, text):
        self.add(f"{version} policy | source {ref}", "subhead")
        self.add(text, "source")

    def inference(self, info):
        reused = info.get("mode") == "cached-local-ollama"
        self.add(f"Model: {info['model']}")
        self.add("Mode: reused verified extraction; no fresh model call." if reused else "Mode: live local Ollama inference.")
        self.add(f"Generation timestamp: {timestamp(info.get('generated_at'))}", "small")
        self.add(f"{'Response' if reused else 'Inference'} latency: {info['latency_seconds']:.3f} seconds; model requests: {info['attempts']}.", "small")
        if reused and info.get("original_latency_seconds") is not None:
            self.add(f"Original inference latency: {info['original_latency_seconds']:.3f} seconds.", "small")
        self.add(f"Model digest: {info['digest']}", "small")

    def build(self):
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=44, rightMargin=44,
            topMargin=56, bottomMargin=49, title=f"RuleTrace AI - {self.title}",
            author="RuleTrace AI", subject="Source-linked policy comparison and human review", pageCompression=1)

        def page_chrome(canvas, document):
            canvas.saveState()
            canvas.setStrokeColor(BORDER)
            canvas.line(44, A4[1]-34, A4[0]-44, A4[1]-34)
            canvas.setFont("RuleTrace-Bold", 8)
            canvas.setFillColor(BLUE)
            canvas.drawString(44, A4[1]-24, "RULETRACE AI")
            canvas.setFont("RuleTrace", 8)
            canvas.setFillColor(MUTED)
            canvas.drawRightString(A4[0]-44, A4[1]-24, "See what a policy change changes.")
            canvas.line(44, 35, A4[0]-44, 35)
            canvas.drawString(44, 23, "Decision support | Human review required")
            canvas.drawRightString(A4[0]-44, 23, f"Page {document.page}")
            canvas.restoreState()

        doc.build(self.story, onFirstPage=page_chrome, onLaterPages=page_chrome)
        return output.getvalue()


def rule_value(rule):
    if rule["field"] == "training_completed":
        return "Training required" if rule["value"] else "No training prerequisite"
    return f"Maximum {rule['value']} {'days' if rule['field'] == 'days_requested' else 'items'}"


def equipment_pdf(data):
    analysis, evaluation = data["analysis"], data["evaluation"]
    summary = evaluation["summary"]
    pdf = ReadableReport("Policy impact report", "Equipment borrowing | Reviewed rules and evaluated requests")
    pdf.metrics([("Requests evaluated",summary["total"]),("Changed outcomes",summary["changed"]),("Needing review",summary["needs_review"])])
    pdf.add(f"{summary['changed']} of {summary['total']} requests change outcome under the proposed reviewed policy. "
            f"Allowed under both policies: {summary['allowed_both']}. Requiring review under at least one policy: {summary['needs_review']}.")
    pdf.add("These outcomes apply only to the reviewed equipment rules and supplied facts. AI interpretation and source citations do not establish institutional or legal authority.", "small")
    pdf.section("1. Outcomes at a glance")
    rows=[]
    for result in evaluation["results"]:
        decision=result["proposed"]
        reasons=[c["explanation"] for c in decision["conditions"] if c["status"] != "pass"]
        impact=" ".join(reasons) if reasons else " ".join(decision["explanations"]) if decision["outcome"] == "Needs review" else "All reviewed conditions pass."
        rows.append([result["case"]["name"],result["current"]["outcome"],decision["outcome"],impact])
    pdf.table(["Request","Current policy","Proposed policy","Explanation"],rows,[.13,.24,.24,.39])
    entries={entry["id"]:entry for p in analysis["policies"] for entry in p["entries"]}
    pdf.story.append(PageBreak())
    pdf.section("2. Why each outcome follows")
    for result in evaluation["results"]:
        case=result["case"]
        trained="Unknown" if case["training_completed"] is None else "Yes" if case["training_completed"] else "No"
        pdf.add(case["name"]+(" | Outcome changed" if result["changed"] else " | Outcome unchanged"),"subhead")
        pdf.add(f"Items: {case['items_requested'] if case['items_requested'] is not None else 'Unknown'}; days: {case['days_requested'] if case['days_requested'] is not None else 'Unknown'}; completed training: {trained}.","small")
        for version in ("current","proposed"):
            decision=result[version]
            pdf.add(f"{version.title()} policy: {decision['outcome']}")
            if not decision["conditions"]:
                for reason in decision["explanations"]:
                    pdf.add(reason,"small")
            for condition in decision["conditions"]:
                entry=entries.get(condition["rule_id"])
                reference=entry["rule"]["paragraph_id"] if entry and entry.get("rule") else "Not available"
                label={"pass":"Pass","fail":"Failed condition","unknown":"Missing information"}[condition["status"]]
                pdf.add(f"{label}: {condition['explanation']} Source: {version.title()} {reference}.","small")
    pdf.section("3. Reviewed rules and source evidence")
    pdf.add("Approval confirms a human reading of the quoted source. It does not certify the policy or guarantee the AI's interpretation.","small")
    for policy in analysis["policies"]:
        pdf.add(f"{policy['version'].title()} policy", "subhead")
        for entry in policy["entries"]:
            if entry["kind"] != "rule":
                continue
            rule=entry["rule"]
            pdf.add(f"{LABELS[rule['field']]}: {rule_value(rule)} | {STATUSES[entry['status']]}","subhead")
            if entry.get("correction"):
                pdf.add(f"Original AI reading: {rule_value(entry['original'])}. Reviewer correction: {rule_value(rule)}.")
            pdf.source(policy["version"].title(),rule["paragraph_id"],rule["excerpt"])
            for event in entry["history"]:
                pdf.add(f"Review action: {event['action']} | {timestamp(event.get('at'))}","small")
    pdf.section("4. Unresolved interpretations and review status")
    unresolved=[e for p in analysis["policies"] for e in p["entries"] if e["kind"] == "unresolved" or e["status"] == "rejected"]
    pdf.add(f"Review actions: {'complete' if analysis['review_complete'] else 'incomplete'}. Review revision: {analysis['revision']}.")
    if not unresolved:
        pdf.add("No unresolved or rejected source entries are recorded.")
    for entry in unresolved:
        pdf.add(f"{entry['version'].title()} policy | {entry['reason'] or 'Rejected interpretation'} | {STATUSES[entry['status']]}")
        if entry.get("original"):
            pdf.source(entry["version"].title(),entry["original"]["paragraph_id"],entry["original"]["excerpt"])
    pdf.section("5. Inference and provenance")
    pdf.inference(analysis["inference"])
    pdf.add(f"Evaluation timestamp: {timestamp(evaluation['created_at'])}","small")
    for policy in analysis["policies"]:
        pdf.add(f"{policy['version'].title()} policy SHA-256: {policy['hash']}","small")
    pdf.add("The optional JSON audit export contains the full original policy texts, machine-readable rules and review history.","small")
    return pdf.build()


def document_pdf(data):
    summary, coverage = data["summary"],data["coverage"]
    pdf=ReadableReport("Policy comparison report", "Document changes | Source passages and selected human-reviewed AI notes")
    pdf.metrics([("Changed sections",summary["changed_sections"]),("AI-reviewed changes",coverage["ai_reviewed_changes"]),("Human-reviewed notes",coverage["human_reviewed_notes"])])
    pdf.add(f"This comparison contains {summary['modified']} modified, {summary['added']} added and {summary['removed']} removed source sections. {summary['unchanged_sections']} sections are unchanged.")
    pdf.section("1. What this report covers")
    pdf.add(f"The text comparison covers both submitted documents. Gemma has interpreted {coverage['ai_reviewed_changes']} of {coverage['total_changes']} changes. Humans have reviewed {coverage['human_reviewed_notes']} of those AI notes.")
    if not coverage["ai_reviewed_changes"]:
        pdf.add("No AI review was requested. This report contains deterministic text differences only.")
    else:
        pending=sum(n["status"] == "pending" for n in data["notes"].values())
        pdf.add(f"AI notes awaiting human review: {pending}. Unselected changes have not been interpreted by AI.")
    pdf.add("No insurance coverage, claim eligibility, legal or medical determination is performed. A human-approved reading is an interpretation of source text, not a coverage decision.","small")
    pdf.add("Blank-line formatting and spacing around source sections are ignored for text alignment. Long paragraphs are split into bounded source sections. This PDF includes all changed passages; the optional JSON audit export also contains both full original documents.","small")
    pdf.section("2. Changes and exact source passages")
    if not data["changes"]:
        pdf.add("No changes were found in the compared text sections.")
    for number,change in enumerate(data["changes"],1):
        pdf.add(f"Change {number} | {change['kind'].title()}","subhead")
        for field,version,empty in [("before","Current","No previous text; this section was added."),("after","Proposed","No replacement text; this section was removed.")]:
            source=change.get(field)
            if source:
                pdf.source(version,source["id"],source["text"])
            else:
                pdf.add(f"{version} policy: {empty}","small")
        note=data["notes"].get(change["id"])
        if not note:
            pdf.add("AI review: not requested for this change.","small")
            continue
        reading_start=len(pdf.story)
        pdf.add(f"Change {number} | Gemma reading | {STATUSES[note['status']]}","subhead")
        pdf.add(note["original"]["summary"])
        pdf.add(f"Model attention flag: {note['original']['attention']}. This note covers this change only.","small")
        if note.get("reviewed_summary"):
            pdf.add("Reviewer correction", "subhead")
            pdf.add(note["reviewed_summary"])
        pdf.story[reading_start:]=[KeepTogether(pdf.story[reading_start:])]
        for event in note["history"]:
            pdf.add(f"Review action: {event['action']} | {timestamp(event.get('at'))}","small")
            if event.get("correction"):
                pdf.add(f"Recorded correction: {event['correction']}","small")
        for previous in note.get("previous_proposals",[]):
            pdf.add(f"Earlier proposal | {STATUSES[previous['status']]}","subhead")
            pdf.add(previous["original"]["summary"],"small")
            if previous.get("reviewed_summary"):
                pdf.add(f"Earlier reviewer correction: {previous['reviewed_summary']}","small")
    pdf.section("3. Inference and document provenance")
    seen=set()
    for note in data["notes"].values():
        info=note["inference"]
        key=(info["model"],info.get("generated_at"),info["latency_seconds"])
        if key not in seen:
            pdf.inference(info)
            seen.add(key)
    if not seen:
        pdf.add("No model inference was performed for this comparison.")
    pdf.add(f"Comparison created: {timestamp(data['created_at'])}","small")
    pdf.add(f"Text comparison time: {data['comparison_latency_seconds']:.3f} seconds. Review revision: {data['review_revision']}.","small")
    for version in ("current","proposed"):
        pdf.add(f"{version.title()} policy: {len(data['policies'][version].encode('utf-8')):,} UTF-8 bytes. SHA-256: {data['hashes'][version]}","small")
    return pdf.build()
