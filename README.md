# Prism

Prism is a PyQt6 research browser that combines persistent browsing with
AI-assisted tab distillation and editable research notes called **Spectrums**.

## Requirements

- Python 3.10 or newer
- PyQt6 and Qt WebEngine supported on your desktop operating system
- A Gemini API key for AI features (ordinary browsing works without one)

## Install and run

From the project root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python test.py
```

On Windows, create the environment with `py -m venv .venv`, activate it with
`.\.venv\Scripts\Activate.ps1`, then install and run using the same `python`
commands.

To enable Distill and Spectrum chat, create a `.env` file beside `test.py`:

```dotenv
GEMINI_API_KEY=your_key_here
```

Obtain a key from [Google AI Studio](https://aistudio.google.com/). Keep the
file private: `.env` is excluded by `.gitignore`. Never put API keys in source
code or share them in logs.

## Browser features

- Persistent browser profile and restored tabs
- Resizable vertical tabs with drag-to-reorder, pinning and bookmarks
- Light, dark and system themes with accent choices
- Keyboard shortcuts: Ctrl/Cmd+T (new tab), Ctrl/Cmd+W (close tab) and
  Ctrl/Cmd+L (focus address bar)
- Distill selected tabs together or compare them; results are saved in Library
- Distill and Spectrum dialogs accept an optional research question so the AI
  can filter irrelevant page content and compare the attributes that matter
- Create and reopen Spectrums from pages, or start an empty note
- Create a Spectrum by selecting one or more open tabs in the Spectrum dialog,
  or use its dedicated "Create empty" action; selected sources are curated into
  an editable, cited research note
- Edit and reorder note blocks, add images, draw annotations, and chat about
  the note with Gemini
- Optional Gemini browser tools for reading open tabs, adding sourced content,
  opening a URL, searching, or distilling tabs. Prism asks for confirmation
  before chat tools open or navigate tabs.

Gemini requests run asynchronously. Distillations, Spectrums, chat history,
settings and saved images use Prism's SQLite/app-data storage. Browser cookies
and site data use the persistent Qt WebEngine profile. Their location is
managed by Qt under the operating system's application-data directory.

Some sites may restrict embedded browsers or show CAPTCHAs; Prism does not
bypass or automatically solve them. AI features also depend on Gemini
availability and applicable API quotas.

## Project layout

```text
prism/
  assets/       Local HTML, CSS, JavaScript and image assets
  browser/      Web profile and browser helpers
  distill/      Web extraction, Markdown rendering and Gemini worker
  spectrum/     Spectrum editor bridge and asynchronous AI chat
  storage/      SQLite database and repository layer
  ui/           Dialogs and shared UI helpers
test.py         Browser application launcher and main-window integration
distiller.py    Compatibility entry point for distillation helpers
```

See [setup_to_do_list.txt](setup_to_do_list.txt) for the setup checklist.
