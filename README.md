# PDF Compressor

A modern desktop application to compress PDF files using Ghostscript, built with PyQt6.

## Features

- 🗜️ Compress PDFs with 5 quality presets (Screen → Prepress)
- 🖱️ Drag-and-drop or file browser to select input
- 📊 Before/after file size stats and compression ratio
- ⚙️ Adjustable DPI (72–300)
- 📁 Custom output directory
- 🧵 Non-blocking background compression (UI stays responsive)
- 🌑 Dark-mode UI

## Requirements

- Python 3.10+
- Ghostscript installed on the system (`gs` must be in PATH)

### Install Ghostscript

**Ubuntu/Debian:**
```bash
sudo apt-get install ghostscript
```

**Fedora:**
```bash
sudo dnf install ghostscript
```

**macOS:**
```bash
brew install ghostscript
```

## Setup

```bash
# Clone or copy the project
cd "pdf compressor"

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

## Running

```bash
python app/main.py
```

## Project Structure

```
pdf-compressor/
│
├── app/
│   ├── main.py              # Entry point (GUI starts here)
│   ├── ui/
│   │   └── main_window.py   # UI layout and interactions
│   ├── core/
│   │   ├── compressor.py    # Main compression logic (Ghostscript)
│   │   ├── pipeline.py      # Step-by-step execution pipeline
│   │   └── utils.py         # Helpers (size calc, cleanup)
│   ├── services/
│   │   └── executor.py      # Runs shell commands safely
│   └── config/
│       └── settings.py      # Default DPI, quality presets
│
├── temp/                    # Temporary working directory (auto-cleaned)
├── output/                  # Final compressed PDFs
├── requirements.txt
└── README.md
```

## Compression Presets

| Preset   | Ghostscript Setting | Best For                    |
|----------|---------------------|-----------------------------|
| Screen   | `/screen`           | On-screen viewing (smallest)|
| Ebook    | `/ebook`            | E-readers and tablets        |
| Printer  | `/printer`          | Standard printing            |
| Prepress | `/prepress`         | High-quality print/archive   |
| Default  | `/default`          | Balanced (Ghostscript default)|

## License

MIT
