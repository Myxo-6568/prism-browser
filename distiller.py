"""Backward-compatible imports for the Prism distillation package."""

from prism.distill.core import (
    build_summary_html,
    distill_html_to_page,
    extract_text_from_html,
    summarize_text_with_gemini,
)

__all__ = [
    "build_summary_html",
    "distill_html_to_page",
    "extract_text_from_html",
    "summarize_text_with_gemini",
]
