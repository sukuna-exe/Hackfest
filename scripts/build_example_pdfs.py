"""Build text-selectable fictional policy PDFs from the canonical example text."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate

from app.pdf_reports import safe_text  # Registers the bundled report fonts.

ROOT = Path(__file__).resolve().parents[1]


def build_example_pdfs():
    title=ParagraphStyle("ExampleTitle",fontName="RuleTrace-Bold",fontSize=14,leading=22,
                         textColor=colors.HexColor("#14243a"),spaceAfter=25)
    body=ParagraphStyle("ExamplePolicy",fontName="RuleTrace",fontSize=12,leading=20,
                        textColor=colors.HexColor("#263c57"),spaceAfter=20)
    for name in ["old_policy","new_policy"]:
        source=(ROOT/"examples"/f"{name}.txt").read_text()
        paragraphs=source.strip().split("\n\n")
        target=ROOT/"examples"/f"{name}.pdf"
        doc=SimpleDocTemplate(str(target),pagesize=A4,leftMargin=52,rightMargin=52,topMargin=60,bottomMargin=52,
                              title=paragraphs[0],author="RuleTrace AI",subject="Fictional policy for demonstration",invariant=True)
        doc.build([Paragraph(safe_text(text),title if i==0 else body) for i,text in enumerate(paragraphs)])
        print(f"Created {target.relative_to(ROOT)}")


if __name__ == "__main__":
    build_example_pdfs()
