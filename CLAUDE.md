# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Ultimate Audiobooks** is a Python CLI tool that takes raw audiobook input files and produces a finished, organized output ready for publication on personal library platforms (e.g. Audiobookshelf). It automates metadata fetching (Audible/Goodreads), ID3/MP4 tag writing, audio conversion to `.m4b`, sidecar file generation, and folder organization.

## Running the Project

**Python 3.13** with a local venv. No `requirements.txt` — dependencies are frozen in the venv.

```bash
# Activate venv and run
source venv/bin/activate
cd Main
python Main.py --input <input_folder> [OPTIONS]
```

**CLI flags:**

| Flag | Short | Description |
|------|-------|-------------|
| `--input <path>` | `-I` | **Required.** Input folder |
| `--output <path>` | `-O` | Output folder (default: `<input>/Ultimate Output`) |
| `--move` | `-M` | Move files instead of copying |
| `--fetch [audible\|goodreads\|both]` | `-FM` | Interactive metadata fetch via browser + clipboard |
| `--clean` | `-CL` | Write fetched metadata to file tags |
| `--create [INFOTEXT\|OPF]` | `-CR` | Generate sidecar metadata files |
| `--force` | `-FO` | Overwrite existing sidecar files |
| `--convert` | `-CV` | Convert to `.m4b` via FFmpeg |
| `--recurseFetch` | `-RF` | Process every file in all subfolders as individual books |
| `--recurseCombine` | `-RC` | Combine chapter files per subfolder into complete books |
| `--recursePreserve` | `-RP` | Treat subfolder files as chapters without combining |
| `--batch N` | `-B` | Max books per run (default: 10) |
| `--workers N` | `-W` | FFmpeg worker count (default: auto from CPU/RAM) |
| `--quick` | `-Q` | Skip settings confirmation (useful for scripting) |
| `--logLevel` | `-LL` | Verbosity: `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` (default: INFO) |
| `--save` / `--load` / `--default` | `-S`/`-L`/`-D` | Save/load/reset settings |
| `--rename <template>` | `-RN` | Rename files using a template |

Only one recursive mode (`--recurseFetch`, `--recurseCombine`, `--recursePreserve`) may be active at a time.

**System dependencies:** `ffmpeg`, `xclip` or `xsel` (Linux clipboard)

**VSCode debug configs** in [.vscode/launch.json](.vscode/launch.json) cover common test scenarios against `/ultimateTestEnvironment/`.

## Architecture

All source files live in [Main/](Main/).

### Module Responsibilities

| File | Role |
|------|------|
| [Main/Main.py](Main/Main.py) | Entry point: argparse, logging setup, top-level dispatch |
| [Main/Settings.py](Main/Settings.py) | CLI args → `Settings` dataclass; path validation; save/load JSON |
| [Main/Processing.py](Main/Processing.py) | Batch processing modes; `ProcessPoolExecutor` for FFmpeg jobs |
| [Main/Util.py](Main/Util.py) | Core logic: metadata classes, Audible/Goodreads parsing, clipboard monitoring, FFmpeg conversion, file ops |
| [Main/FileMerger.py](Main/FileMerger.py) | Merge multi-chapter folders into single files; chapter ordering by track number or filename |
| [Main/BookStatus.py](Main/BookStatus.py) | Skip/fail tracking; moves problem books to dedicated folders; prints run summary |
| [Main/template.opf](Main/template.opf) | OPF sidecar template |

### Data Flow

```
CLI Args → Settings (validation) → Processing mode selected
  ↓
For each audio file:
  1. Extract existing ID3/MP4 tags
  2. [--fetch] Open browser search → monitor clipboard for Audible/Goodreads URL
       → call Audible API or scrape Goodreads HTML (BeautifulSoup)
  3. Create output dir: Author/Title (if fetch) or filename-based
  4. [--convert] Queue FFmpeg conversion (ProcessPoolExecutor, worker count from CPU/RAM)
  5. [--clean] Write metadata to file tags (mutagen: ID3 for MP3, EasyMP4 for m4a/m4b)
  6. [--create] Write .opf or .infotext sidecar
  7. Copy or move to output path
  ↓
Skip/fail summary report
```

### Processing Modes

- **Single-level batch** — processes audio files directly in the input root
- **Recursive fetch** (`--recurseFetch`) — treats each nested file as an independent book
- **Recursive combine** (`--recurseCombine`) — merges chapter files per subfolder into one file, then processes as single-level
- **Recursive preserve** — stub, not implemented

### Metadata Sources

- **Audible**: REST API at `https://api.audible.com/1.0/catalog/products/{ASIN}` — ASIN extracted from clipboard URL
- **Goodreads**: HTML scraping with BeautifulSoup — book ID extracted from clipboard URL

### Key Implementation Details

- `Util.py:fetchMetadata()` polls the clipboard every second waiting for the user to paste a URL after the browser opens
- Chapter ordering tries track numbers first (ID3/MP4), falls back to numeric extraction from filenames; handles multi-disk
- FFmpeg conversion sanitizes filenames before processing (`Util.py:sanitizeFile()`)
- Skip/fail books are moved to `Ultimate Audiobook skips/` and `Ultimate Audiobook fails/` sibling folders
- Worker count for parallel conversions is computed from `psutil` CPU/memory info

