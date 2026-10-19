# Hawkes Companion

A local Windows math tutor powered by Ollama. Ask questions, attach a problem,
and get explanations with properly rendered mathematics.

**Current version: v0.7**

## Features

- Compact chat window or optional Hawk view.
- Local text and image models, with model discovery and refresh.
- Socratic, Feynman-inspired, and traditional teaching styles.
- Screen-region capture, image attachments, and a graphing tool.
- Optional offline narration with voice on/off and playback controls.
- PDF Studio with document settings, live preview, and professional LaTeX output.
- Save a complete `.tex` document for editing in Overleaf, with its graph when selected.

## Run on Windows

1. Install **64-bit Python 3.12 or newer** with Tcl/Tk, and [Ollama](https://ollama.com/).
2. Start Ollama and install the models:

   ```powershell
   ollama pull qwen3:8b
   ollama pull qwen3-vl:8b
   ```

3. Run `Setup_Hawkes_AI.bat` once. It installs the Python dependencies, the local
   browser renderer, and the LaTeX engine/fonts. This step needs internet access.
4. Open `Launch_Compact.bat` or `Launch_Hawk.bat`.

Keep Ollama running. If the model list is empty, start Ollama and click Refresh.

### Optional voice

After setup, run:

```powershell
.venv\Scripts\python.exe scripts\setup_assets.py --voice
```

This downloads the local voice model. Voice starts off and can be enabled in the app.

## Export your work

After a tutor answer, open **PDF Studio**. Choose document details and appearance,
preview the finished pages, and select **Save PDF** or **Save LaTeX**.

Exports go to **Desktop / Hawkes Companion PDFs**, created automatically.
LaTeX exports contain `main.tex`, a short README, and `graph.pdf` when needed.
Upload the source and graph to Overleaf to edit; use XeLaTeX for matching output.
Existing exports are never overwritten.

## Development

The application modules and tests are in the repository root. Run `Run_Tests.bat`
after setup for the full local test suite. Some tests briefly show windows.
Older versions are preserved as downloadable backups on the [archive release](https://github.com/SquareRoot169/hawkes-companion/releases/tag/legacy-versions).

Large runtime files, models, generated documents, and personal preferences are
excluded from Git. Setup prepares the external resources locally. Once prepared,
chat rendering, narration, and document export run locally; tutoring uses local Ollama.

The tutor can make mathematical mistakes. A well-formatted answer is not a proof
of correctness. This is an independent project, not an official Hawkes Learning product.

## Third-party notices

MathJax notices are in `vendor/`; voice notices are in `voice/`; Tectonic notices
are in `tex/`. Artwork provenance is recorded in `assets/`.
No project-wide redistribution license has been selected yet.
