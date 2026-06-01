# DataLangSanitizer 🧹

A lightweight, zero-dependency Python CLI tool to detect, highlight, and filter out common language-mixing errors, homoglyphs, CJK character leaks, and LLM-typical generation bugs from your datasets.

## Features

- **Homoglyph & Mixed-Script Detection:** Finds Latin characters accidentally typed inside Cyrillic words (e.g., `aбсолютная` with Latin `a`, `санатoрно` with Latin `o`) and vice versa.
- **CJK Leak Detection:** Detects Chinese, Japanese, and Korean characters in Cyrillic/Latin text fields (often leaked during LLM translation or data scraping).
- **LLM Bug & Artifact Detection:**
  - Repetitive word loops (hallucination patterns).
  - Leaked Markdown code blocks (e.g., ````json`).
  - Unclosed markdown tags.
  - Placeholder markers (e.g. `[placeholder]`, `<insert text>`, `TODO`).
- **Single-Language Enforcement:** Ensure the input is Russian-only (`--lang ru`) or English-only (`--lang en`), highlighting any foreign characters.
- **Two Operational Modes:**
  - **Report Mode (default):** Highlights anomalies in the terminal with colored indicators and exact Unicode code point details.
  - **Clean Mode:** Removes contaminated lines/records and outputs a sanitized file.
- **Format Support:** Works with `.txt`, `.csv`, `.json`, and standard input (stdin) piping.

## Installation

Simply clone the repository and run the script:

```bash
git clone https://github.com/Prestapro/datalangsanitizer.git
cd datalangsanitizer
chmod +x sanitizer.py
```

No external dependencies are required. It runs on any standard Python 3.7+ installation.

## Usage

### 1. Report Mode (Highlighting anomalies)

Print a detailed report highlighting mixed scripts, CJK characters, and LLM artifacts:

```bash
python3 sanitizer.py input.txt
```

To specify the report mode explicitly:

```bash
python3 sanitizer.py --mode report input.csv
```

### 2. Clean Mode (Filtering out bad data)

Remove any lines or JSON objects containing contaminated text and write to a clean file:

```bash
python3 sanitizer.py input.json --mode clean --output clean_output.json
```

### Options

```
usage: sanitizer.py [-h] [-m {report,clean}] [-o OUTPUT] [-f {txt,csv,json}]
                    [-l {ru,en}] [--check-cjk] [--no-check-cjk]
                    [--check-mixed] [--no-check-mixed] [--check-llm]
                    [--no-check-llm]
                    [input]

DataLangSanitizer — Clean datasets from homoglyphs, CJK leaks, and LLM loops.

positional arguments:
  input                 Path to the input file (txt, csv, json) or stdin ('-')

options:
  -h, --help            show this help message and exit
  -m {report,clean}, --mode {report,clean}
                        Operation mode: 'report' to print highlights, 'clean'
                        to filter out bad rows/lines
  -o OUTPUT, --output OUTPUT
                        Output path for sanitized data (required for clean
                        mode, defaults to stdout)
  -f {txt,csv,json}, --format {txt,csv,json}
                        Explicit input format. Optional for files, highly
                        recommended for stdin ('-').
  -l {ru,en}, --lang {ru,en}
                        Enforce single-language mode: 'ru' for Russian-only,
                        'en' for English-only. Flags any foreign characters.
  --check-cjk           Enable CJK character checks (default: True)
  --no-check-cjk
  --check-mixed         Enable mixed script checks (default: True)
  --no-check-mixed
  --check-llm           Enable LLM generation artifact checks (default: True)
  --no-check-llm
```

## License

MIT License.

