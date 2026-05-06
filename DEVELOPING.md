# Architecture & Developer Guide

Welcome to the Bibox codebase! This document explains the internal architecture, design philosophy, and data flow of the project. It is intended for maintainers and contributors.

---

## 1. Design Philosophy

Bibox is built on two core principles:
1.  **Stateless Execution**: The CLI commands run and exit immediately. There is no background daemon or interactive session holding locks.
2.  **The Staging Area**: To allow users to string commands together without copying long IDs, Bibox uses a temporary `.bibox/staging.json` file to map 1-based integers (`:1`, `:2`) to persistent `cite_key`s.

---

## 2. The `.bibox` Workspace

Bibox does not use a global database by default. It mimics Git.
When a user runs a command, the `BiboxDB._find_root()` method traverses up the directory tree looking for a `.bibox` folder. 

Inside this folder:
*   `db.json`: The source of truth. It stores `papers` and `stars` (collections). It is written with `indent=2, sort_keys=True` to minimize Git merge conflicts if the user puts their library under version control.
*   `staging.json`: The volatile file that powers the `:index` targeting system. It contains two dictionaries:
    *   `results`: Maps string indices (`"1"`) to `cite_key`s.
    *   `online_data`: Temporarily holds raw metadata fetched from online APIs until the user explicitly imports them.

---

## 3. Core Modules

### `bibox/db.py` (The State Manager)
The `BiboxDB` class handles all persistence.
*   **Search Engine**: `search_papers` implements a recursive boolean evaluator (`_evaluate_expression`). It allows complex queries like `(nlp | vision) & !archive`.
*   **Target Resolution**: `resolve_targets()` converts user inputs like `:1`, `:all`, or `:db` into actual `cite_key` lists. It also acts as a guard, throwing explicit errors if a user tries to modify an `__ONLINE__` item before materializing it.
*   **Conflict Resolution & Hashing**: When `import_pdf_file` runs, it computes the MD5 hash of the PDF. This hash allows `bibox import` to instantly short-circuit duplicate files, and enables `bibox update` to reverse-search the `pdfs/` directory to self-heal broken physical links (`find_pdf_file_by_hash`). If differing hashes are found for the same version slot, a new version suffix is appended (e.g., `published_2`).

### `bibox/paper.py` (The Domain Model)
*   **`Paper`**: The core entity. A Paper has `tags`, a plain-text `comment`, and a dictionary of `versions`.
*   **`VersionState`**: Represents a specific release of a paper (e.g., `arxiv` vs `cvpr`). It holds an `Info` object (the raw metadata), an optional `pdf_path`, and its `pdf_hash`.
*   **`cite_key` Generation**: Uses `[AuthorLastname]_[FirstTitleWord]_[TitleMD5Hash]`.

### `bibox/pdf_parser.py` (The 4-Tier Extractor)
When users run `bibox import a.pdf`, the `PdfExtractor` attempts to guess the metadata:
1.  **Regex**: Scans pages 1-2 for DOI/arXiv ID strings.
2.  **Metadata**: Reads embedded PDF metadata.
3.  **Heuristics**: Finds the text block with the largest font size on page 1.
4.  **Self-Claim Extraction**: `get_self_claim_v_name()` scans the PDF metadata and first 1000 characters to map keywords (like "CVPR" or "IJCV") directly to our internal venue taxonomy. This breaks the tie when resolving conflicting metadata fetched online.

### `bibox/cli.py` (The UI Layer)
*   **`rich` Integration**: All visual output (tables, panels, spinners, syntax highlighting) is handled via a global `rich.console.Console`. We strictly avoid `print()` for layout.
*   **Dynamic Help**: The `bibox help [cmd]` intercepts the `-h` flag and uses `bibox/help_content.json` to render beautiful, data-driven help panels.
*   **Tab Completion**: Powered by `argcomplete`. Custom completers (`star_completer`, `target_completer`) dynamically read the JSON files to provide instant suggestions for star names and staging indices.

---

## 4. Running Tests

Bibox uses an End-to-End (E2E) testing strategy rather than unit tests. The script spins up a temporary `.bibox` sandbox and executes raw CLI commands via `subprocess`.

```bash
# From the project root:
python3 tests/test_e2e.py
```

The tests cover:
1. Initialization & Scaffolding
2. The Boolean Search Engine
3. PDF Hashing and Version Suffixing
4. Explicit Materialization Protections (`[Online]` items)
5. Export filtering (`--no-arxiv`)