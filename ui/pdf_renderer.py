from __future__ import annotations

from pathlib import Path


RENDERER_NAME = "pymupdf"


def render_pdf_page(path: str | Path, page_number: int, dpi: int = 130) -> bytes:
    import pymupdf

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    with pymupdf.open(path) as document:
        if page_number < 1 or page_number > document.page_count:
            raise IndexError(f"Page {page_number} is outside the document's 1-{document.page_count} range.")
        page = document.load_page(page_number - 1)
        scale = dpi / 72
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")

