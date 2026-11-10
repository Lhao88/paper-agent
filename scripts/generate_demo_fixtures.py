"""Create original, deterministic PDFs for the mock research workflow."""

from pathlib import Path

from reportlab.pdfgen import canvas


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "documents"
    root.mkdir(parents=True, exist_ok=True)
    for identifier, subject in (("paper-1", "graph retrieval"), ("paper-2", "evidence grounding")):
        path = root / f"{identifier}.pdf"
        if path.exists():
            continue
        document = canvas.Canvas(str(path), invariant=1)
        document.drawString(50, 750, "Methods (original synthetic software-test fixture)")
        document.drawString(50, 720, f"This synthetic study evaluates {subject} on ToyCorpus.")
        document.drawString(50, 690, "It is not a published scientific paper.")
        document.showPage()
        document.drawString(50, 750, "Results and limitations")
        document.drawString(50, 720, "ToyCorpus is synthetic; no real-world effectiveness is claimed.")
        document.save()
    print("Original synthetic PDF fixtures ready (existing files preserved).")


if __name__ == "__main__":
    main()
