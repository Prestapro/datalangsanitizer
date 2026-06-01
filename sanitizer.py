#!/usr/bin/env python3
"""DataLangSanitizer — Detect and filter character and text anomalies.

Supports:
1. Mixed script word detection (Latin in Cyrillic, and vice versa).
2. CJK (Chinese, Japanese, Korean) character detection.
3. LLM-typical generation bugs (text loops, codeblocks, placeholders).
4. Language enforcement (Russian-only, English-only).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from typing import Any
from pathlib import Path

# ANSI color codes for report mode
COLOR_RED = "\033[91m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_GREEN = "\033[92m"
COLOR_BOLD = "\033[1m"
COLOR_RESET = "\033[0m"

# Regular expressions for script classification
RE_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")
RE_LATIN = re.compile(r"[a-zA-Z]")
RE_CJK = re.compile(
    r"[\u4e00-\u9fff"      # CJK Unified Ideographs
    r"\u3400-\u4dbf"      # CJK Unified Ideographs Extension A
    r"\u3040-\u309f"      # Hiragana
    r"\u30a0-\u30ff"      # Katakana
    r"\uac00-\ud7af"      # Hangul Syllables
    r"\u1100-\u11ff"      # Hangul Jamo
    r"\u3130-\u318f"      # Hangul Compatibility Jamo
    r"\u3000-\u303f"      # CJK Symbols and Punctuation
    r"\uff00-\uffef]"     # Halfwidth and Fullwidth Forms
)

# LLM-typical artifacts
RE_CODEBLOCK = re.compile(r"```[a-zA-Z]*")
RE_PLACEHOLDER = re.compile(
    r"\[(?:insert|placeholder|todo|name|date|x)\]|"
    r"<(?:insert|placeholder|todo|name|date|x)>|"
    r"\b(?:todo|placeholder|tbd)\b",
    re.IGNORECASE
)
RE_LOOP = re.compile(r"\b(\w+)(?:\s+\1){2,}\b", re.IGNORECASE)  # word repeated 3+ times


def check_word_mixed(word: str) -> bool:
    """Return True if word has both Cyrillic and Latin characters."""
    # Filter out pure alphanumeric or compounds that are meant to be mixed
    # We only check words containing alphabetic characters
    has_cyr = bool(RE_CYRILLIC.search(word))
    has_lat = bool(RE_LATIN.search(word))
    return has_cyr and has_lat


LATIN_TO_CYRILLIC_HOMOGLYPHS = {
    'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у',
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
    'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У'
}
CYRILLIC_TO_LATIN_HOMOGLYPHS = {v: k for k, v in LATIN_TO_CYRILLIC_HOMOGLYPHS.items()}


def fix_word_homoglyphs(word: str) -> str:
    """Fix mixed script homoglyphs in a single word if a dominant script exists."""
    cyr_count = len(RE_CYRILLIC.findall(word))
    lat_count = len(RE_LATIN.findall(word))
    
    if cyr_count == 0 or lat_count == 0:
        return word
        
    if cyr_count > lat_count:
        # Dominant script is Cyrillic, replace Latin homoglyphs with Cyrillic
        fixed_chars = []
        for char in word:
            if char in LATIN_TO_CYRILLIC_HOMOGLYPHS:
                fixed_chars.append(LATIN_TO_CYRILLIC_HOMOGLYPHS[char])
            else:
                fixed_chars.append(char)
        return "".join(fixed_chars)
    elif lat_count > cyr_count:
        # Dominant script is Latin, replace Cyrillic homoglyphs with Latin
        fixed_chars = []
        for char in word:
            if char in CYRILLIC_TO_LATIN_HOMOGLYPHS:
                fixed_chars.append(CYRILLIC_TO_LATIN_HOMOGLYPHS[char])
            else:
                fixed_chars.append(char)
        return "".join(fixed_chars)
        
    return word


def fix_text_homoglyphs(text: str) -> str:
    """Find and fix mixed-script words containing homoglyphs in the given text."""
    def repl(match):
        word = match.group(0)
        return fix_word_homoglyphs(word)
    return re.sub(r"[a-zA-Zа-яА-ЯёЁ]+", repl, text)


def analyze_text(
    text: str,
    check_mixed: bool = True,
    check_cjk: bool = True,
    check_llm: bool = True,
    lang: str | None = None
) -> list[dict]:
    """Analyze text and return a list of violations with their categories and details."""
    violations = []
    if not text:
        return violations

    # 1. Check CJK characters
    if check_cjk:
        cjk_found = RE_CJK.findall(text)
        if cjk_found:
            violations.append({
                "type": "cjk",
                "message": f"Found CJK character(s): '{''.join(cjk_found)}'",
                "chars": set(cjk_found)
            })

    # 2. Check Mixed Script (Latin inside Cyrillic words, and vice versa)
    if check_mixed and not lang:
        # Split by alphabetic sequences to analyze individual words
        words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]+", text)
        mixed_words = [w for w in words if check_word_mixed(w)]
        if mixed_words:
            violations.append({
                "type": "mixed_script",
                "message": f"Mixed script word(s): {', '.join(repr(w) for w in mixed_words)}",
                "words": mixed_words
            })

    # 3. Check LLM-typical artifacts
    if check_llm:
        # Check codeblock leaks
        cb_matches = RE_CODEBLOCK.findall(text)
        if cb_matches:
            violations.append({
                "type": "llm_artifact",
                "message": "Leaked Markdown codeblock markers (e.g. ```json)",
                "match": cb_matches
            })
            
        # Check placeholders
        ph_matches = RE_PLACEHOLDER.findall(text)
        if ph_matches:
            violations.append({
                "type": "llm_artifact",
                "message": "Detected template placeholder (e.g. [insert], TODO)",
                "match": ph_matches
            })

        # Check repetition loops
        loop_matches_full = [m.group(0) for m in RE_LOOP.finditer(text)]
        if loop_matches_full:
            repeated_word = RE_LOOP.search(text).group(1)
            violations.append({
                "type": "llm_loop",
                "message": f"Repetitive word loops detected (e.g. repeating '{repeated_word}')",
                "match": loop_matches_full
            })

    # 4. Check Language constraints (Russian-only / English-only)
    if lang == "ru":
        lat_found = RE_LATIN.findall(text)
        if lat_found:
            violations.append({
                "type": "foreign_script",
                "message": f"Found Latin character(s) in Russian-only mode: '{''.join(sorted(set(lat_found)))}'",
                "chars": set(lat_found)
            })
    elif lang == "en":
        cyr_found = RE_CYRILLIC.findall(text)
        if cyr_found:
            violations.append({
                "type": "foreign_script",
                "message": f"Found Cyrillic character(s) in English-only mode: '{''.join(sorted(set(cyr_found)))}'",
                "chars": set(cyr_found)
            })

    return violations


def format_highlighted(text: str, violations: list[dict]) -> str:
    """Return a string with ANSI colored highlights showing where errors are located."""
    cjk_chars = set()
    mixed_words = set()
    foreign_chars = set()
    
    for v in violations:
        if v["type"] == "cjk":
            cjk_chars.update(v["chars"])
        elif v["type"] == "mixed_script":
            mixed_words.update(v["words"])
        elif v["type"] == "foreign_script":
            foreign_chars.update(v["chars"])

    # First, highlight CJK and foreign characters
    highlighted = ""
    for char in text:
        if char in cjk_chars:
            highlighted += f"{COLOR_YELLOW}{COLOR_BOLD}{char}{COLOR_RESET}"
        elif char in foreign_chars:
            highlighted += f"{COLOR_RED}{COLOR_BOLD}{char}{COLOR_RESET}"
        else:
            highlighted += char

    # Next, highlight mixed script words
    if mixed_words:
        # We find each mixed word and highlight its Latin/Cyrillic characters selectively
        for word in mixed_words:
            # selectively color characters in the word
            colored_word = ""
            for c in word:
                if RE_LATIN.match(c):
                    # Color Latin characters red inside mixed word
                    colored_word += f"{COLOR_RED}{COLOR_BOLD}{c}{COLOR_RESET}"
                else:
                    colored_word += c
            # Replace the word in the highlighted text (use lambda to avoid backslash escaping issues)
            highlighted = re.sub(r"\b" + re.escape(word) + r"\b", lambda m: colored_word, highlighted)

    # Highlight LLM loop or code blocks if present
    for v in violations:
        if v["type"] in ("llm_artifact", "llm_loop"):
            for match_str in v["match"]:
                if isinstance(match_str, tuple):
                    match_str = next((s for s in match_str if s), "")
                if match_str:
                    colored_match = f"{COLOR_BLUE}{COLOR_BOLD}{match_str}{COLOR_RESET}"
                    highlighted = re.sub(re.escape(match_str), lambda m: colored_match, highlighted, flags=re.IGNORECASE)

    return highlighted


def process_txt(
    input_data: str,
    mode: str,
    check_mixed: bool,
    check_cjk: bool,
    check_llm: bool,
    lang: str | None = None,
    auto_fix: bool = False
) -> list[str] | None:
    lines = input_data.splitlines()
    clean_lines = []
    has_violations_any = False

    for idx, line in enumerate(lines, 1):
        processed_line = line
        if auto_fix:
            processed_line = fix_text_homoglyphs(line)

        violations = analyze_text(processed_line, check_mixed, check_cjk, check_llm, lang)
        if violations:
            has_violations_any = True
            if mode == "report":
                hl = format_highlighted(processed_line, violations)
                print(f"{COLOR_BOLD}Line {idx:4d}:{COLOR_RESET} {hl}")
                for v in violations:
                    print(f"            - {v['message']}")
        else:
            if mode == "clean":
                clean_lines.append(processed_line)
            elif mode == "report" and auto_fix and processed_line != line:
                print(f"{COLOR_GREEN}Line {idx:4d} corrected:{COLOR_RESET} {line} -> {processed_line}")

    if mode == "report":
        if not has_violations_any:
            print(f"{COLOR_GREEN}✔ No anomalies detected in text file.{COLOR_RESET}")
        return None
    return clean_lines


def process_csv(
    input_data: str,
    mode: str,
    check_mixed: bool,
    check_cjk: bool,
    check_llm: bool,
    lang: str | None = None,
    auto_fix: bool = False
) -> list[list[str]] | None:
    reader = csv.reader(io.StringIO(input_data))
    clean_rows = []
    has_violations_any = False

    for idx, row in enumerate(reader, 1):
        row_has_violation = False
        highlighted_row = []
        row_violations = []
        processed_row = []

        for cell in row:
            processed_cell = cell
            if auto_fix:
                processed_cell = fix_text_homoglyphs(cell)
            processed_row.append(processed_cell)

            violations = analyze_text(processed_cell, check_mixed, check_cjk, check_llm, lang)
            if violations:
                row_has_violation = True
                has_violations_any = True
                hl = format_highlighted(processed_cell, violations)
                highlighted_row.append(hl)
                row_violations.extend(violations)
            else:
                highlighted_row.append(processed_cell)

        if row_has_violation:
            if mode == "report":
                print(f"{COLOR_BOLD}Row {idx:4d}:{COLOR_RESET} {', '.join(highlighted_row)}")
                for v in row_violations:
                    print(f"           - {v['message']}")
        else:
            if mode == "clean":
                clean_rows.append(processed_row)
            elif mode == "report" and auto_fix and processed_row != row:
                print(f"{COLOR_GREEN}Row {idx:4d} corrected:{COLOR_RESET} {', '.join(row)} -> {', '.join(processed_row)}")

    if mode == "report":
        if not has_violations_any:
            print(f"{COLOR_GREEN}✔ No anomalies detected in CSV.{COLOR_RESET}")
        return None
    return clean_rows


def process_json(
    input_data: str,
    mode: str,
    check_mixed: bool,
    check_cjk: bool,
    check_llm: bool,
    lang: str | None = None,
    auto_fix: bool = False
) -> Any | None:
    try:
        obj = json.loads(input_data)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON structure: {e}", file=sys.stderr)
        return None

    has_violations_any = False

    def clean_node(node: Any, path: str = "") -> tuple[Any, bool]:
        nonlocal has_violations_any
        
        if isinstance(node, str):
            processed_node = node
            if auto_fix:
                processed_node = fix_text_homoglyphs(node)

            violations = analyze_text(processed_node, check_mixed, check_cjk, check_llm, lang)
            if violations:
                has_violations_any = True
                if mode == "report":
                    hl = format_highlighted(processed_node, violations)
                    print(f"{COLOR_BOLD}JSON Node [{path}]:{COLOR_RESET} {hl}")
                    for v in violations:
                        print(f"            - {v['message']}")
                return None, True  # Filter out in clean mode
            
            if mode == "report" and auto_fix and processed_node != node:
                print(f"{COLOR_GREEN}JSON Node [{path}] corrected:{COLOR_RESET} {repr(node)} -> {repr(processed_node)}")
            return processed_node, False

        elif isinstance(node, list):
            cleaned_list = []
            for i, val in enumerate(node):
                sub_path = f"{path}[{i}]"
                sub_val, is_bad = clean_node(val, sub_path)
                if not is_bad:
                    cleaned_list.append(sub_val)
            return cleaned_list, False

        elif isinstance(node, dict):
            cleaned_dict = {}
            for k, val in node.items():
                sub_path = f"{path}.{k}" if path else k
                processed_k = k
                if auto_fix:
                    processed_k = fix_text_homoglyphs(k)

                # Check key itself for mixed-script anomalies
                key_violations = analyze_text(processed_k, check_mixed, check_cjk, check_llm, lang)
                if key_violations:
                    has_violations_any = True
                    if mode == "report":
                        hl = format_highlighted(processed_k, key_violations)
                        print(f"{COLOR_BOLD}JSON Key [{sub_path}]:{COLOR_RESET} {hl}")
                        for v in key_violations:
                            print(f"            - {v['message']}")
                    continue # Skip this key in clean mode
                
                if mode == "report" and auto_fix and processed_k != k:
                    print(f"{COLOR_GREEN}JSON Key [{sub_path}] corrected:{COLOR_RESET} {repr(k)} -> {repr(processed_k)}")

                sub_val, is_bad = clean_node(val, sub_path)
                if not is_bad:
                    cleaned_dict[processed_k] = sub_val
            return cleaned_dict, False

        return node, False

    cleaned_obj, _ = clean_node(obj)

    if mode == "report":
        if not has_violations_any:
            print(f"{COLOR_GREEN}✔ No anomalies detected in JSON object.{COLOR_RESET}")
        return None
    return cleaned_obj


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DataLangSanitizer — Clean datasets from homoglyphs, CJK leaks, and LLM loops."
    )
    parser.add_argument(
        "input", nargs="?", default="-",
        help="Path to the input file (txt, csv, json) or stdin ('-')"
    )
    parser.add_argument(
        "-m", "--mode", choices=["report", "clean"], default="report",
        help="Operation mode: 'report' to print highlights, 'clean' to filter out bad rows/lines"
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Output path for sanitized data (required for clean mode, defaults to stdout)"
    )
    parser.add_argument(
        "-f", "--format", choices=["txt", "csv", "json"], default=None,
        help="Explicit input format. Optional for files, highly recommended for stdin ('-')."
    )
    parser.add_argument(
        "-l", "--lang", choices=["ru", "en"], default=None,
        help="Enforce single-language mode: 'ru' for Russian-only, 'en' for English-only. Flags any foreign characters."
    )
    parser.add_argument(
        "--auto-fix", action="store_true", default=False,
        help="Automatically fix mixed-script homoglyphs to the dominant script of the word."
    )
    parser.add_argument(
        "--check-cjk", action="store_true", default=True,
        help="Enable CJK character checks (default: True)"
    )
    parser.add_argument(
        "--no-check-cjk", dest="check_cjk", action="store_false"
    )
    parser.add_argument(
        "--check-mixed", action="store_true", default=True,
        help="Enable mixed script checks (default: True)"
    )
    parser.add_argument(
        "--no-check-mixed", dest="check_mixed", action="store_false"
    )
    parser.add_argument(
        "--check-llm", action="store_true", default=True,
        help="Enable LLM generation artifact checks (default: True)"
    )
    parser.add_argument(
        "--no-check-llm", dest="check_llm", action="store_false"
    )

    args = parser.parse_args()

    # Read input data
    if args.input == "-":
        if sys.stdin.isatty():
            parser.print_help()
            return 0
        input_data = sys.stdin.read()
        file_ext = "." + (args.format or "txt")
    else:
        path = Path(args.input)
        if not path.exists():
            print(f"ERROR: Input file not found: {path}", file=sys.stderr)
            return 2
        with path.open("r", encoding="utf-8") as f:
            input_data = f.read()
        file_ext = args.format or path.suffix.lower()

    if args.mode == "clean" and not args.output:
        print("ERROR: --output path is required when running in 'clean' mode.", file=sys.stderr)
        return 2

    # Process data according to extension
    if file_ext == ".json":
        result = process_json(input_data, args.mode, args.check_mixed, args.check_cjk, args.check_llm, args.lang, args.auto_fix)
        if args.mode == "clean" and result is not None:
            with open(args.output, "w", encoding="utf-8") as out:
                json.dump(result, out, ensure_ascii=False, indent=2)
            print(f"{COLOR_GREEN}✔ Sanitized JSON written to {args.output}{COLOR_RESET}")

    elif file_ext == ".csv":
        result = process_csv(input_data, args.mode, args.check_mixed, args.check_cjk, args.check_llm, args.lang, args.auto_fix)
        if args.mode == "clean" and result is not None:
            with open(args.output, "w", encoding="utf-8", newline="") as out:
                writer = csv.writer(out)
                writer.writerows(result)
            print(f"{COLOR_GREEN}✔ Sanitized CSV written to {args.output}{COLOR_RESET}")

    else:  # defaults to text processing
        result = process_txt(input_data, args.mode, args.check_mixed, args.check_cjk, args.check_llm, args.lang, args.auto_fix)
        if args.mode == "clean" and result is not None:
            with open(args.output, "w", encoding="utf-8") as out:
                out.write("\n".join(result) + "\n")
            print(f"{COLOR_GREEN}✔ Sanitized text written to {args.output}{COLOR_RESET}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
