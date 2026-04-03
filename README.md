# PDF Compressor 0.1

A modern, high-performance desktop application for PDF manipulation and adaptive compression. Built with **PySide6** and designed with a premium, SaaS-inspired aesthetic.

---

## 🛠️ Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **UI Framework** | [PySide6](https://pyside.org/) | Cross-platform Qt for Python (LGPL) |
| **PDF Core** | [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | Fast parsing, extraction, and rendering |
| **Rasterization** | `pdftoppm` (Poppler) | High-fidelity page-to-image conversion |
| **Processing** | `mogrify` (ImageMagick) | Lossy JPEG quality optimization |
| **Assembly** | [img2pdf](https://gitlab.mister-muffin.de/josch/img2pdf) | Direct JPEG-to-PDF embedding (no transcoding) |
| **Typography** | Inter, Noto Sans | Modern, readable UI fonts |

---

## 🏗️ Core Compression Logic

Unlike standard compressors that apply a single filter, this application uses a **Heuristic Adaptive Loop**:

1.  **Iterative Stepping**: The engine tries multiple combinations of **DPI** (Dots Per Inch) and **JPEG Quality** (0-100).
2.  **Best-Result Tracking**: It stores every attempt and compares them against your target file size (e.g., 1 MB).
3.  **Adaptive Steering**: If the file is still too large, it dynamically drops quality. If quality hits a floor, it steps down the DPI and resets the quality baseline.
4.  **Early Exit**: Once the target is hit (within a 90% margin), the process terminates to save time, ensuring the highest possible quality for that specific size.

---

## ✨ Key Features

*   🗜️ **Adaptive Compression**: Target specific file sizes (500KB, 1MB, etc.) with iterative quality stepping.
*   📑 **Split PDFs**: Define multiple page ranges with **live previews** and merge them or split them into separate files.
*   🔗 **Merge PDFs**: Fast, lossless merging of multiple documents.
*   🔄 **Rearrange Pages**: Visual drag-and-drop or manual reordering of document pages.
*   👁️ **High-Performance Viewer**: Threaded pre-rendering with hardware-accelerated zoom (Ctrl+Wheel).
*   🎨 **Dynamic Theme Engine**: Switch between *Elegant, Playful, Neo, Retro, and Paper* themes with full Light/Dark mode support via a global palette-to-QSS injector.

---

## 🚀 Getting Started

### 1. System Dependencies
Ensure the following tools are in your system `PATH`:
*   `poppler-utils` (for `pdftoppm`)
*   `imagemagick` (for `mogrify`)

```bash
# Ubuntu/Debian
sudo apt install poppler-utils imagemagick
```

### 2. Python Setup
```bash
# Clone the repository
git clone https://github.com/swatantra-cloud/pdf-compressor---Stable-Version.git
cd pdf-compressor

# Recommended: Use a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## 📂 Project Architecture

*   `app/main.py`: Entry point and Application lifecycle.
*   `app/ui/`: Contains the dynamic `ThemeManager` and per-tab UI logic.
*   `app/core/`: The "Engine Room"—contains the adaptive compressor, pipeline orchestration, and PDF utilities.
*   `app/config/settings.py`: Centralized presets, color palettes, and user preferences.

---

## 📜 License

MIT License. Designed with ❤️ by the Google DeepMind team.
