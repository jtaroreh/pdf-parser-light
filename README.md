<p align="center">
  <img src="icon.png" alt="PDF Parser Light Logo" width="128" height="128">
</p>

# PDF Parser Light

<p align="center">
  <a href="https://github.com/jtaroreh/pdf-parser-light/releases"><img src="https://img.shields.io/github/v/release/jtaroreh/pdf-parser-light?color=blue" alt="GitHub Release"></a>
  <a href="https://pypi.org/project/pdf-parser-light/"><img src="https://img.shields.io/pypi/v/pdf-parser-light.svg" alt="PyPI Package"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.9+"></a>
</p>

A lightweight desktop and CLI tool that converts PDFs into clean Markdown using the Google Gemini API. Formats math into LaTeX equations and preserves complex tables without requiring a paid subscription or third-party service.

<p align="center">
  <img src="hero.gif" alt="PDF Parser Light Demo" width="400">
</p>

---

## Why PDF Parser Light?

Most PDF extraction tools fall into two categories:

1. **Traditional OCR & PDF libraries** (like Tesseract, PyPDF, or pdfplumber): Fast and local, but often mangle multi-column layouts, tables, and mathematical formulas into broken plain text.
2. **Commercial OCR / Document AI APIs** (like Mathpix or AWS Textract): High accuracy, but lock you into monthly subscriptions, proprietary dashboards, or per-page billing.

**PDF Parser Light** takes a different approach:
- **Direct API access**: Calls Gemini's vision models directly using your own API key. No middlemen, no tracking, and no added subscription fees.
- **Works within Gemini's free tier**: Handles daily document conversion within Google's free quota (20 requests/day on Flash, falling back to Flash Lite for higher volume).
- **Multimodal extraction**: Gemini understands full page layouts in one shot, converting formulas into clean inline/block LaTeX (`$...$` / `$$...$$`) and multi-column data into Markdown/HTML tables.
- **Both GUI & CLI**: Use the drag-and-drop desktop app or automate large batches via terminal.

---

## Features

- **LaTeX math & table preservation**: Extracts formulas into LaTeX and structured data into Markdown/HTML tables without summarizing.
- **Desktop GUI & CLI**: CustomTkinter desktop interface with live progress, plus a CLI for batch processing directories.
- **Automatic page chunking**: Automatically splits documents larger than 20 pages into chunks to prevent timeouts and context overflows.
- **Quota tracking & model fallback**: Tracks daily free tier usage locally and automatically falls back to Lite models if primary quotas run low.
- **Resume support**: Resumes processing from partial output files if a job is interrupted mid-way.
- **Cross-platform**: Pre-built binaries available for macOS, Windows, and Linux.

---

## Installation

### Option 1: Standalone App (No Python required)

Download the pre-built binary for your OS from the [Releases](https://github.com/jtaroreh/pdf-parser-light/releases) page:

- **macOS**: Download `pdf-parser-light-macos.zip`, extract, and move `PDF Parser Light.app` to `/Applications`.
- **Windows**: Download `pdf-parser-light-windows.zip`, extract, and run `PDF Parser Light.exe`.
- **Linux**: Download `pdf-parser-light-linux.tar.gz`, extract, and run `PDF Parser Light`. *(Requires Tk: `sudo apt install python3-tk`)*.

#### Opening Unsigned Binaries (First-Time Setup)

Because these builds are open-source releases built via GitHub Actions without commercial developer certificates, your OS will block them by default on first launch:

- **macOS (Gatekeeper)**:
  - **Finder / System Settings**: **Right-click (or Control-click)** `PDF Parser Light.app` in Finder, click **Open**, and confirm **Open**. On macOS Sequoia (15+), if it doesn't open, go to **System Settings → Privacy & Security**, scroll down to the *Security* section, and click **Open Anyway**.
  - **Terminal**: Alternatively, remove the quarantine attribute directly:
    ```bash
    xattr -d com.apple.quarantine "/Applications/PDF Parser Light.app"
    ```
- **Windows (SmartScreen)**:
  - Click **More info** on the popup, then click **Run anyway**.

---
### Option 2: Install via pip

```bash
pip install pdf-parser-light
```

Launch the GUI or CLI:
```bash
pdf-parser-light-gui   # Launches Desktop GUI
pdf-parser-light       # Runs CLI
```

---

## Usage

### Desktop Application

<p align="center">
  <img src="tutorial.gif" alt="PDF Parser Light Tutorial" width="750">
</p>

1. Launch the app and enter your [Gemini API Key](https://aistudio.google.com/api-keys) (check *Remember API Key* to save locally).
2. Drag and drop a PDF file (or click **Browse**).
3. Click **Process**.
4. Copy the result or save it directly as `.md` or `.txt`.

### Command Line (CLI)

Set your Gemini API key:
```bash
export GEMINI_API_KEY="your_api_key_here"
```

#### Examples

```bash
# Convert a single PDF
pdf-parser-light document.pdf --output output.md

# Batch process an entire directory of PDFs
pdf-parser-light ./pdf_folder/ --output ./markdown_output/

# Process a specific page range (e.g. pages 1 to 50)
pdf-parser-light document.pdf --pages 1-50

# Resume an interrupted parsing job
pdf-parser-light document.pdf --resume

# Check remaining free requests for today
pdf-parser-light --usage

# Reset local quota counter
pdf-parser-light --reset-quota

# Custom transcription prompt
pdf-parser-light document.pdf --prompt "Transcribe equations only into LaTeX."
```

#### Options

| Option | Description |
| :--- | :--- |
| `input_path` | Path to a `.pdf` file or a directory containing PDFs. |
| `--output`, `-o` | Output file (single PDF) or output directory (batch mode). |
| `--pages`, `-p` | Page range to parse (e.g. `1-50`, `40-120`, or `10`). |
| `--resume`, `-r` | Resume parsing from existing partial output. |
| `--prompt` | Custom instructions for the model. |
| `--api-key` | Pass API key explicitly (overrides `GEMINI_API_KEY`). |
| `--usage` | Print remaining daily free requests and exit. |
| `--reset-quota` | Reset local request counter to 0. |
| `--force` | Bypass local quota check and run anyway. |

---

## Daily Quota & Rate Limits

- **Free Tier Limits**: By default, the app tracks 20 free requests/day locally for primary Flash models (configurable via `GEMINI_FREE_LIMIT`).
- **Model Fallbacks**: When your primary quota runs out, requests cascade to Flash Lite models (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`), which offer significantly higher capacity (up to 500 free requests/day per model on Google AI Studio).
- **Retries**: Automatically retries with exponential backoff on HTTP 429 rate limits or transient errors.

---

## Privacy & Security

- **Direct Connections**: All requests and file uploads go directly to Google's Gemini API endpoints using the official `google-genai` SDK. No third-party servers, analytics, or telemetry proxies are involved.
- **Data Sensitivity Notice**: Do not upload confidential, sensitive, or restricted documents. Files are processed remotely on Google's servers in accordance with Google Gemini API terms.
- **File Retention & Cleanup**: Files are uploaded temporarily to Gemini API storage for transcription and deleted immediately upon completion. If a process terminates unexpectedly, files remain until Google's temporary storage retention limit expires.
- **Key Storage**: Saved API keys are stored locally on your machine in standard user configuration directories (`~/Library/Application Support/pdf_parser_light/` on macOS, `%LOCALAPPDATA%\pdf_parser_light\` on Windows, `~/.config/pdf_parser_light/` on Linux).

---

## Development

```bash
git clone https://github.com/jtaroreh/pdf-parser-light.git
cd pdf-parser-light

python3 -m venv venv
source venv/bin/activate
pip install -e ".[test]"

pytest -v
```

### Build App Bundle (macOS)

```bash
./build.sh
```

Output is created in `dist/PDF Parser Light.app`.
