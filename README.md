# 📦 Bibox: A Stateless CLI Literature Manager

Bibox is a command-line-driven, stateless personal literature manager designed for developers and researchers. It operates on local files, uses a deterministic JSON database for seamless Git version control, and features a powerful staging area and boolean search engine.

This manual provides an exhaustive, command-by-command reference for every feature, argument, and flag in Bibox.

---

## 🚀 Installation & Quick Start

### Prerequisites
*   Python 3.8 or higher.
*   (Optional but recommended) `pipx` or standard `pip` for installation.
*   Bibox uses `rich` for its beautiful terminal UI and `argcomplete` for magical tab-completions. Both are installed automatically.

### Global Options
*   `--log-level <level>`: Sets the verbosity of internal logs. Defaults to `WARNING` to keep the UI clean.
*   `--debug`: Alias for `--log-level DEBUG`. Useful for seeing detailed network API calls and PDF extraction steps.

### Auto-Completion
Bibox supports native shell tab-completion! To enable it in your terminal, add the following to your `~/.bashrc` or `~/.zshrc`:
```bash
eval "$(register-python-argcomplete bibox)"
```
Now, you can press `Tab` to autocomplete commands, star names (e.g., `bibox star show <Tab>`), and targeting indices (`bibox tag add :<Tab>`).
Clone the repository and install it in editable mode (or standard mode) using `pip`:

```bash
git clone <your-repo>/bibox
cd bibox
pip install -e .
```
*(Note: Do not use `--user` if you are inside an Anaconda environment on Windows, as it may place the executable outside your active PATH).*

Once installed, the `bibox` command will be available globally in your terminal. You can verify the installation by running:
```bash
bibox -h
```

### The 30-Second Workflow
To get a feel for Bibox's Git-like workflow:

```bash
# 1. Initialize an empty library in your current directory
bibox init .

# 2. Fetch a paper online and stage it
bibox fetch "Attention Is All You Need"

# 3. Explicitly import the online paper from the staging area (:1)
bibox import :1

# 4. View it in the local database
bibox show :1

# 5. Add it to a star collection
bibox star add must_read :1
```

---

## 🧠 Core Concepts

Before diving into the commands, you must understand three core concepts that govern how Bibox operates.

### 1. The Workspace (`.bibox`)
Like Git, Bibox relies on a hidden `.bibox` directory to define the root of your library. Whenever you run a `bibox` command, it traverses up your directory tree until it finds this folder. It stores the `db.json` (database), `staging.json` (temporary staging area), and handles the physical paths for `pdfs/`.

### 2. The Targeting System (`<target>`)
Most commands in Bibox require a `<target>` to know which paper to act on. A target can be:
*   **A `cite_key`**: The unique identifier of a paper (e.g., `Vaswani_Attention_8afb`).
*   **A Staging Index (`:<num>`)**: A shortcut to a paper currently in your staging area (e.g., `:1`, `:5`). This is populated after running a `search`.
*   **The Bulk Selector (`:all`)**: Applies the command to *every* paper currently in the staging area.
*   **The Global Selector (`:db`)**: Applies the command to *every* paper in your entire local database.

### 3. Recursive Boolean Expressions
Several filter arguments in the `search` command accept full boolean logic to create highly specific queries. 
*   **Operators**: `|` (OR), `&` (AND), `!` (NOT).
*   **Grouping**: Parentheses `()` can be nested infinitely.
*   *Example*: `"(nlp | vision) & !archive"`

---

## 🗂️ 1. Workspace Management

### `bibox init [path]`
Initializes a new Bibox library.
*   **Positional Arguments:**
    *   `path` *(optional)*: The directory to initialize. Defaults to the current directory (`.`).
*   **Behavior:** Creates the `.bibox` tracking folder, the `pdfs/` directory, and generates a Git-friendly `.gitignore`.

### `bibox status`
Displays the health and statistics of the current library.
*   **Behavior:** Prints the absolute path to the library root, the total number of papers, and counts of papers missing PDFs or comments.

---

## 📥 2. Importing Literature

### `bibox import <targets_or_paths>... [-k]`
Intelligently imports literature. Bibox will automatically detect what you are trying to import based on the argument:
*   **A PDF file (`.pdf`)**: Triggers the 4-tier PDF extraction pipeline, resolves metadata online, copies the PDF to `pdfs/`, and saves it to the database. **Duplicate PDFs are instantly skipped via MD5 hash checks**, preventing redundant API calls and saving time.
*   **A BibTeX file (`.bib`)**: Bulk imports metadata. Pass `-k` or `--keep-keys` to preserve the original citation keys from the `.bib` file instead of auto-generating them.
*   **An `:index` or `:all`**: If you previously used `bibox fetch` to stage `[Online]` papers, passing their index to `import` will permanently materialize them into your local database.
*   **Conflict Handling**: If the imported paper already exists in your local library, Bibox safely appends the new information as a new *Version* (e.g., `imported_bib`) to prevent any data loss.

### `bibox export <targets>... [--no-arxiv]`
Exports papers to raw, copy-pasteable BibTeX format.
*   **Arguments:** `cite_key`s, staging indices (`:1`), `:all`, or the global `:db` selector.
*   **Behavior**: By default, Bibox tries to export the "best" version of a paper (preferring published versions over arXiv).
*   **Options**: 
    *   `--no-arxiv`: Strictly filters out any version named `arxiv`. If a paper *only* has an arXiv version, it will be skipped entirely. Perfect for generating clean bibliographies for official publications.

---

## 🔍 3. Search & The Staging Area

The staging area (`.bibox/staging.json`) is where search results are temporarily held, allowing you to chain commands.

### `bibox search [query] [options]`
Searches the database and replaces (or appends to) the staging area.
*   **Positional Arguments:**
    *   `query` *(optional)*: A global fuzzy search string. Matches against Titles, Authors, DOIs, and abstracts across all versions of a paper. Supports boolean logic.
*   **Options:**
    *   `-a`, `--append`: Appends the search results to the *existing* staging area instead of clearing it. Indices will continue counting up.
    *   `-t`, `--temp`: Performs the search and prints results, but does **not** overwrite the staging area.
    *   `--tag <expr>`: Filter by tag using boolean logic (e.g., `--tag "machine-learning & !draft"`).
    *   `--star <expr>`: Filter by star collection using boolean logic.
    *   `--author <expr>`: Filter by author name using boolean logic.
    *   `--year <expr>`: Filter by publication year using boolean logic.
    *   `--title <expr>`: Filter specifically against the paper title.

### `bibox stage <action>`
Directly manages the temporary staging list.
*   **Actions:**
    *   `status` *(default)*: Prints the current contents and indices of the staging area.
    *   `add <targets>...`: Manually adds specific `cite_key`s to the end of the staging area.
    *   `remove <indices>...`: Removes specific items from the staging area by their index (e.g., `bibox stage remove :2 :5`).
    *   `clear`: Empties the staging area completely.

---

## 🏷️ 4. Organization (Tags & Stars)

### `bibox tag <action> <target> <tags>...`
Manages semantic tags for papers.
*   **Actions:**
    *   `add`: Attaches the provided tags.
    *   `remove`: Detaches the provided tags.
*   **Arguments:**
    *   `target`: A `cite_key`, `@index`, or `@all`.
    *   `tags`: One or more tag strings (space-separated).

### `bibox star <action>`
Manages "Stars" (named collections or playlists of papers). *Star names must be ASCII and contain no spaces.*
*   **Actions:**
    *   `add <star_name> <targets>...`: Adds papers to the specified star collection.
    *   `remove <star_name> <targets>...`: Removes papers from the star.
    *   `list`: Prints all existing star collections and their paper counts.
    *   `show <star_name>`: Loads all papers from the specified star into the staging area, making them ready for bulk operations (like `bibox update :all`).

---

## 📝 5. Paper Interaction & Management

### `bibox show <targets>... [--bibtex [version]]`
Displays detailed information about papers.
*   **Arguments:**
    *   `targets`: One or more `cite_key`s, `:index`es, `:all`, or `:db`.
*   **Options:**
    *   `--bibtex [version]`: Instead of human-readable text, outputs raw, copy-pasteable BibTeX. If no version is provided, it outputs BibTeX for *all* versions of the paper. Optionally, specify a version name (e.g., `--bibtex published`) to only print that specific entry.

### `bibox comment <target> [text] [-c]`
Adds or clears a lightweight, plain-text comment directly in the database.
*   **Arguments:**
    *   `target`: A `cite_key` or `:index`.
    *   `text` *(optional)*: The comment string (wrap in quotes).
*   **Options:**
    *   `-c`, `--clear`: Wipes the existing comment.

### `bibox update <targets>... [--update-keys]`
Refreshes paper metadata from online sources and self-heals broken links.
*   **Arguments:**
    *   `targets`: One or more `cite_key`s, `:index`es, `:all`, or `:db`.
*   **Options:**
    *   `--update-keys`: Analyzes all gathered titles for a paper, picks the lexicographically first one, recalculates a fresh `cite_key`, and cascades the rename across your entire database, star collections, and physical PDF filenames.
*   **Behavior:** Uses the paper's best known identifier (DOI > arXiv > Title) to query CrossRef, arXiv, and DBLP. It performs a deep dictionary comparison and only updates if actual changes are detected. Before querying, it also performs **Physical PDF Self-Healing**: if a linked PDF is missing but its MD5 hash is known, Bibox will scan the `pdfs/` directory to track down the renamed or moved file and automatically relink it!

### `bibox link pdf <target> <file_path>`
Manually links an external physical PDF to an existing local paper.
*   **Arguments:**
    *   `target`: A `cite_key` or `:index`.
    *   `file_path`: Path to the external PDF file.
*   **Behavior:** Copies the PDF into the central `pdfs/` directory, renames it properly, and links it to the `published` version of the paper.

### `bibox rm <targets>... [--keep-pdf]`
Permanently deletes papers from the database and cleans up associated files.
*   **Arguments:**
    *   `targets`: One or more `cite_key`s, `:index`es, `:all`, or `:db`.
*   **Behavior:** Prompts for confirmation. By default, it removes the database entry, clears it from all Star collections, and **deletes the associated PDF files from the disk** to save space.
*   **Options:**
    *   `--keep-pdf`: Only removes the database entry, leaving the physical PDF files intact in the `pdfs/` folder.

### `bibox fetch <query> [options]`
Queries online APIs (CrossRef/arXiv/DBLP) and lazy-stages the results.
*   **Arguments:**
    *   `query`: A DOI, arXiv ID, or Title string.
*   **Options:**
    *   `-a`, `--append`: Appends the fetched results to the existing staging area.
    *   `-t`, `--temp`: Skips staging entirely and instead prints the raw, copy-pasteable BibTeX directly to your terminal. Useful for quick metadata verification.
*   **Behavior (Explicit Import):** Normal fetched items are placed in the staging area marked as `[Online]`. These are temporary and cannot be tagged or starred. To permanently save them to your local database, you must explicitly run `bibox import :<index>`.

## 💡 Cookbook: Practical Workflows

Bibox's atomic commands are designed to be composable. Here are a few ways to combine them to solve real-world academic problems.

### Workflow 1: The "BibTeX Washer" (Upgrade & Clean an old .bib)
Got an old `.bib` file full of arXiv preprints? Let Bibox automatically find their officially published versions and generate a clean bibliography.

```bash
# 1. Import the old file, preserving your original \cite{} keys so your LaTeX doesn't break
bibox import old_refs.bib -k

# 2. Tell Bibox to query CrossRef/arXiv for every paper in your library
bibox update :db

# 3. Export the library. Bibox inherently prefers 'published' versions over 'arxiv'. 
# Use --no-arxiv if you want to strictly drop papers that were NEVER published.
bibox export :db --no-arxiv > clean_refs.bib
```

### Workflow 2: The Literature Review Funnel
Discover, curate, and review papers without ever leaving the terminal.

```bash
# 1. Fetch recent papers from online APIs (lazy-stages them as [Online])
bibox fetch "Retrieval Augmented Generation"

# 2. Materialize the ones that look interesting (e.g., index 2 and 4) into your local DB
bibox import :2 :4

# 3. Add them to a specific star collection for your current project
bibox star add rag_project :2 :4

# 4. Add a quick thought or review note to paper #2
bibox comment :2 "Great methodology, should adapt this for chapter 3."
```

### Workflow 3: Generating a Targeted Bibliography
Need to generate a `.bib` file containing only the papers relevant to a specific chapter of your thesis?

```bash
# 1. Use boolean logic to find exactly what you need
bibox search --tag "(vision | audio) & !draft"

# 2. Export ONLY the papers currently in the staging area
bibox export :all > chapter_3.bib
```
