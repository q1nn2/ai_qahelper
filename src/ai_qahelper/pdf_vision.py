from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ai_qahelper.llm_client import LlmClient
    from ai_qahelper.models import LlmConfig


def _extract_pdf_text_pypdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks).strip()


def extract_pdf_text_fitz(path: Path) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        parts: list[str] = []
        for i in range(len(doc)):
            page = doc.load_page(i)
            t = page.get_text("text") or ""
            if t.strip():
                parts.append(f"--- Страница {i + 1} ---\n{t}")
        return "\n\n".join(parts).strip()
    finally:
        doc.close()


def render_pdf_pages_png(
    path: Path,
    *,
    max_pages: int,
    scale: float,
) -> list[tuple[int, bytes]]:
    """Возвращает список (номер страницы с 1, PNG bytes)."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        n = min(len(doc), max(1, max_pages))
        mat = fitz.Matrix(scale, scale)
        out: list[tuple[int, bytes]] = []
        for i in range(n):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out.append((i + 1, pix.tobytes("png")))
        return out
    finally:
        doc.close()


def build_pdf_requirement_content(
    path: Path,
    llm: LlmClient,
    llm_cfg: LlmConfig,
    *,
    pdf_vision: bool,
) -> str:
    """
    Текст PDF (PyMuPDF или pypdf) + при pdf_vision — описание визуала страниц через vision-модель.
    """
    try:
        text_body = extract_pdf_text_fitz(path)
    except ImportError:
        logger.warning("PyMuPDF (pymupdf) не установлен — извлечение текста через pypdf; vision недоступен.")
        text_body = _extract_pdf_text_pypdf(path)
    except Exception as exc:
        logger.warning("PyMuPDF text extract failed, fallback pypdf: %s", exc)
        text_body = _extract_pdf_text_pypdf(path)

    if not text_body:
        text_body = "Текст со страниц PDF не извлечён (возможно, только изображения)."

    if not pdf_vision:
        return text_body

    try:
        page_pngs = render_pdf_pages_png(
            path,
            max_pages=llm_cfg.pdf_vision_max_pages,
            scale=llm_cfg.pdf_vision_render_scale,
        )
    except ImportError:
        logger.warning("PyMuPDF нужен для рендера страниц PDF в изображения. Установите: pip install pymupdf")
        return text_body
    except Exception as exc:
        logger.warning("PDF render skipped: %s", exc)
        return text_body

    if not page_pngs:
        return text_body

    try:
        visual = llm.describe_pdf_pages_for_requirements(
            page_pngs,
            pages_per_batch=max(1, llm_cfg.pdf_vision_pages_per_request),
            max_output_tokens=max(512, llm_cfg.pdf_vision_max_output_tokens),
        )
    except Exception as exc:
        logger.exception("PDF vision description failed: %s", exc)
        return (
            text_body
            + "\n\n---\n[PDF vision: не удалось распознать изображения страниц — "
            + str(exc)
            + "]\n"
        )

    if not (visual and visual.strip()):
        return text_body

    return (
        text_body
        + "\n\n---\n## Визуальное содержимое PDF (описание по скриншотам страниц, для тест-анализа)\n\n"
        + visual.strip()
    )
