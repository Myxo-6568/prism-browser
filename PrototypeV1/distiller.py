import html
import os
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv

load_dotenv()


def extract_text_from_html(raw_html: str, max_chars: int = 25000) -> str:
    """Extract readable text from HTML using BeautifulSoup."""
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "noscript", "svg", "footer", "nav", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse blank lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = "\n".join(lines)
    return cleaned[:max_chars]


def summarize_text_with_gemini(text: str, page_title: str = "", source_url: str = "") -> str:
    """Send extracted webpage text to Gemini and return a summary."""
    if not text.strip():
        return "No readable text could be extracted from this page."

    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key) if api_key else genai.Client()

    prompt = (
        "Summarize the following webpage content clearly and concisely. "
        "Include a short overview and key bullet points.\n\n"
        f"Title: {page_title}\n"
        f"URL: {source_url}\n\n"
        f"Content:\n{text}"
    )

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
    )
    return response.text or "Gemini returned an empty response."


def build_summary_html(summary_text: str, page_title: str, source_url: str) -> str:
    """Wrap the summary into a clean HTML document for display in a tab."""
    safe_title = html.escape(page_title or "Distilled Summary")
    safe_url = html.escape(source_url or "")
    safe_summary = html.escape(summary_text)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Distilled: {safe_title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 780px;
      margin: 40px auto;
      padding: 0 20px;
      line-height: 1.6;
      color: #1f2937;
      background: #fafafa;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      padding: 28px 32px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    }}
    h1 {{
      margin-top: 0;
      font-size: 1.5rem;
      color: #111827;
    }}
    .source {{
      font-size: 0.875rem;
      color: #6b7280;
      word-break: break-all;
      margin-bottom: 20px;
    }}
    pre.summary {{
      white-space: pre-wrap;
      font-family: inherit;
      font-size: 1rem;
      margin: 0;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Summary: {safe_title}</h1>
    <div class="source">Source: {safe_url}</div>
    <pre class="summary">{safe_summary}</pre>
  </div>
</body>
</html>"""


def distill_html_to_page(raw_html: str, page_title: str = "", source_url: str = "") -> str:
    """Orchestrate extraction, Gemini summarization, and HTML generation."""
    try:
        extracted = extract_text_from_html(raw_html)
        summary = summarize_text_with_gemini(extracted, page_title=page_title, source_url=source_url)
    except Exception as exc:
        summary = f"Error while distilling page:\n{exc}"

    return build_summary_html(summary, page_title=page_title, source_url=source_url)
