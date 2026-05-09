import argparse
import sys
import logging
import os
import json
import glob
import re
import concurrent.futures
from pathlib import Path
from typing import List, Optional
import argcomplete
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.tree import Tree
from rich import print as rprint
from rich.theme import Theme

# Global console instance
custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red"
})
console = Console(theme=custom_theme)

from .paper import Paper
from .info_getter import Info, ApiGetter
from .pdf_parser import PdfExtractor
from .db import BiboxDB

class BiboxArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """Override default error method to provide rich help on missing arguments."""
        # Print the error message using rich
        console.print(f"[danger]Error:[/danger] {message}\n")
        
        # Try to determine which command caused the error
        argv = sys.argv[1:]
        cmd = None
        for arg in argv:
            if arg not in ('-h', '--help', '--debug') and not arg.startswith('-'):
                cmd = arg
                break
                
        if cmd:
            console.print(f"[dim]Auto-displaying help for '{cmd}':[/dim]")
            handle_help(argparse.Namespace(help_target=cmd))
        else:
            print_logo()
            
        sys.exit(2)

def setup_parser() -> argparse.ArgumentParser:
    """Sets up the main argument parser and sub-commands."""
    parser = BiboxArgumentParser(
        description="Bibox: A lightweight, stateless personal literature manager.",
        add_help=False  # We handle global help manually
    )
    
    # Global arguments
    parser.add_argument('-h', '--help', action='store_true', help='Show this help message and exit')
    parser.add_argument('-l', '--list-config', action='store_true', help='List full program state and configuration')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging (alias for --log-level=DEBUG)')
    parser.add_argument('--log-level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='WARNING', help='Set the logging level')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    subparsers.required = False
    
    # Dedicated help command
    help_parser = subparsers.add_parser('help', help='Show interactive, rich help manual', add_help=False)
    help_parser.add_argument('help_target', nargs='?', help='Specific command to get help on')
    
    helphelp_parser = subparsers.add_parser('helphelp', help=argparse.SUPPRESS)
    
    # Enable feature command
    enable_parser = subparsers.add_parser('enable', help='Enable a specific bibox feature')
    enable_parser.add_argument('feature', choices=['completion'], help='The feature to enable')

    # Disable feature command
    disable_parser = subparsers.add_parser('disable', help='Disable a specific bibox feature')
    disable_parser.add_argument('feature', choices=['completion'], help='The feature to disable')

    # Add a custom base formatter to ensure standard argparse help looks slightly cleaner if it falls back
    class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
        pass

    # 1. init
    init_parser = subparsers.add_parser('init', help='Initialize a Bibox library in the current directory', formatter_class=CustomFormatter)
    init_parser.add_argument('path', nargs='?', default='.', help='Path to initialize (default: current directory)')

    # 2. status
    status_parser = subparsers.add_parser('status', help='Show library status')
    status_parser.add_argument('-d', '--detailed', action='store_true', help='Show detailed statistics')
    status_parser.add_argument('-l', '--list', action='store_true', help='List all papers in the library (paginated)')
    status_parser.add_argument('-p', '--page', type=int, default=1, help='Page number to display when using -l')

    # 3. import
    import_parser = subparsers.add_parser('import', help='Import literature (PDF, BibTeX, or :Online)')
    import_parser.add_argument('targets_or_paths', nargs='+', help='File paths (.pdf, .bib) or staging indices (:1)').completer = target_completer
    import_parser.add_argument('-k', '--keep-keys', action='store_true', help='Keep original cite_keys when importing BibTeX')

    # 4. search
    search_parser = subparsers.add_parser('search', help='Search local literature and stage results')
    search_parser.add_argument('query', nargs='?', help='Global fuzzy search keyword')
    search_parser.add_argument('-a', '--append', action='store_true', help='Append to current staging area instead of overwriting')
    search_parser.add_argument('-t', '--temp', action='store_true', help='Temporary search (does not modify staging area)')
    search_parser.add_argument('--tag', help='Filter by tag (boolean logic supported)')
    search_parser.add_argument('--star', help='Filter by star collection (boolean logic supported)')
    search_parser.add_argument('--author', help='Filter by author (boolean logic supported)')
    search_parser.add_argument('--year', help='Filter by year (boolean logic supported)')
    search_parser.add_argument('--title', help='Filter by title specifically (boolean logic supported)')

    # 5. tag
    tag_parser = subparsers.add_parser('tag', help='Manage tags for papers')
    tag_subparsers = tag_parser.add_subparsers(dest='tag_action', help='Tag actions')
    tag_subparsers.required = True
    
    tag_add_parser = tag_subparsers.add_parser('add', help='Add tags to a paper or :all staged')
    tag_add_parser.add_argument('target', help='Cite key, staging index (:1), or :all').completer = target_completer
    tag_add_parser.add_argument('tags', nargs='+', help='Tags to add')

    tag_rm_parser = tag_subparsers.add_parser('remove', help='Remove tags from a paper or :all staged')
    tag_rm_parser.add_argument('target', help='Cite key, staging index (:1), or :all').completer = target_completer
    tag_rm_parser.add_argument('tags', nargs='+', help='Tags to remove')

    # 6. link
    link_parser = subparsers.add_parser('link', help='Link files to a paper')
    link_subparsers = link_parser.add_subparsers(dest='link_type', help='Type of file to link')
    link_subparsers.required = True
    
    link_pdf_parser = link_subparsers.add_parser('pdf', help='Link a PDF to a paper')
    link_pdf_parser.add_argument('target', help='Cite key or staging index (e.g., :1)')
    link_pdf_parser.add_argument('file_path', help='Path to the PDF file')

    # 7. comment
    comment_parser = subparsers.add_parser('comment', help='Add or clear a text comment for a paper')
    comment_parser.add_argument('target', help='Cite key or staging index (e.g., :1)')
    comment_parser.add_argument('text', nargs='?', help='The comment text')
    comment_parser.add_argument('-c', '--clear', action='store_true', help='Clear the existing comment')

    # 8. rm (Delete)
    rm_parser = subparsers.add_parser('rm', help='Permanently remove papers from the database')
    rm_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices (:1), :all, or :db')
    rm_parser.add_argument('--keep-pdf', action='store_true', help='Keep the physical PDF files on disk')
    rm_parser.add_argument('-y', '--yes', action='store_true', help='Bypass confirmation prompt')

    # 9. fetch (Online preview)
    fetch_parser = subparsers.add_parser('fetch', help='Fetch metadata online and stage results (lazy import)')
    fetch_parser.add_argument('query', help='DOI, arXiv ID, or Title')
    fetch_parser.add_argument('-a', '--append', action='store_true', help='Append to current staging area')
    fetch_parser.add_argument('-t', '--temp', action='store_true', help='Temporary fetch: print raw BibTeX instead of staging')

    # 10. update
    update_parser = subparsers.add_parser('update', help='Update metadata from online sources')
    update_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices (:1), or :all')
    update_parser.add_argument('--update-keys', action='store_true', help='Recalculate cite_keys based on lexicographically first title and synchronize')

    # 10. star (Collections)
    star_parser = subparsers.add_parser('star', help='Manage star collections')
    star_subparsers = star_parser.add_subparsers(dest='star_action', help='Star actions')
    star_subparsers.required = True

    star_add_parser = star_subparsers.add_parser('add', help='Add papers to a star')
    star_add_parser.add_argument('star_name', help='Name of the star collection (no spaces)').completer = star_completer
    star_add_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices, or :all').completer = target_completer

    star_rm_parser = star_subparsers.add_parser('remove', help='Remove papers from a star')
    star_rm_parser.add_argument('star_name', help='Name of the star collection').completer = star_completer
    star_rm_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices, or :all').completer = target_completer

    star_subparsers.add_parser('list', help='List all star collections')

    star_show_parser = star_subparsers.add_parser('show', help='Show contents of a star (stages results)')
    star_show_parser.add_argument('star_name', help='Name of the star collection').completer = star_completer

    # 12. stage (Staging management)
    stage_parser = subparsers.add_parser('stage', help='Manage the temporary staging area')
    stage_subparsers = stage_parser.add_subparsers(dest='stage_action', help='Stage actions')
    stage_subparsers.default = 'status'
    
    stage_subparsers.add_parser('status', help='Show current staging area')
    
    stage_add_parser = stage_subparsers.add_parser('add', help='Add specific papers to staging manually')
    stage_add_parser.add_argument('targets', nargs='+', help='Cite keys')

    stage_rm_parser = stage_subparsers.add_parser('remove', help='Remove items from staging by index')
    stage_rm_parser.add_argument('indices', nargs='+', help='Staging indices (e.g., :1 :2)')

    stage_subparsers.add_parser('clear', help='Clear the staging area')

    # 13. show
    show_parser = subparsers.add_parser('show', help='Show detailed info or BibTeX for papers')
    show_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices, or :all')
    show_parser.add_argument('--bibtex', nargs='?', const='__all__', help='Output raw BibTeX (optionally specify a version)')

    # 14. export
    export_parser = subparsers.add_parser('export', help='Export papers to BibTeX format')
    export_parser.add_argument('targets', nargs='+', help='Cite keys, staging indices (:1), :all, or :db')
    export_parser.add_argument('--no-arxiv', action='store_true', help='Exclude arxiv versions and skip if only arxiv is available')

    return parser

def print_logo():
    import importlib.metadata
    try:
        version = importlib.metadata.version('bibox')
        meta = importlib.metadata.metadata('bibox')
        license_str = meta.get('License', 'Unknown License')
        desc = meta.get('Summary', 'A Stateless CLI Literature Manager')
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
        license_str = "Unknown License"
        desc = "A Stateless CLI Literature Manager"
        
    logo = """
    ____  _  __               
   / __ )(_)/ /_   ____  _  __
  / __  // / __ \\ / __ \\| |/_/
 / /_/ // / /_/ // /_/ />  <  
/_____//_/_.___/ \\____/_/|_|  
    """
    console.print(f"[bold cyan]{logo}[/bold cyan]")
    console.print(f"v{version} | {license_str} | {desc}\n", justify="left")
    console.print("[dim]Run 'bibox -h' or 'bibox help' for usage instructions.[/dim]\n", justify="left")

def load_help_content():
    import importlib.resources
    import json
    try:
        if sys.version_info >= (3, 9):
            content = importlib.resources.files('bibox').joinpath('help_content.json').read_text(encoding='utf-8')
        else:
            content = importlib.resources.read_text('bibox', 'help_content.json', encoding='utf-8')
        return json.loads(content)
    except Exception as e:
        logging.error(f"Failed to load help content: {e}")
        return {}

def handle_help(args):
    """Rich interactive help manual."""
    
    if args.help_target:
        cmd = args.help_target.lower()
        content = load_help_content()
        commands_data = content.get("commands", {})
        
        if cmd in commands_data:
            cmd_data = commands_data[cmd]
            
            panel_content = f"[bold]Usage:[/bold] {cmd_data.get('usage', '')}\n\n"
            panel_content += f"{cmd_data.get('description', '')}\n\n"
            
            if cmd_data.get('options'):
                panel_content += "[bold]Options:[/bold]\n"
                for opt_k, opt_v in cmd_data['options'].items():
                    panel_content += f"  {opt_k:<15} {opt_v}\n"
                panel_content += "\n"
                
            if cmd_data.get('examples'):
                panel_content += "[bold]Examples:[/bold]\n"
                for ex in cmd_data['examples']:
                    panel_content += f"  {ex}\n"
                    
            console.print(Panel(panel_content.strip(), title=f"[cyan]Command: {cmd}[/cyan]", border_style="cyan"))
        else:
            console.print(f"[warning]No detailed interactive help available for '{cmd}'.[/warning] Use 'bibox help' for an overview.")
        return

    # Main help screen
    console.print()
    table = Table(show_header=False, box=None, padding=(0, 2))
    
    table.add_row("[bold]🚀 Getting Started[/bold]", "")
    table.add_row("  [cyan]init[/cyan]", "Initialize a Bibox library in the current directory")
    table.add_row("  [cyan]import[/cyan]", "Import PDFs, BibTeX files, or materialize :Online papers")
    table.add_row("  [cyan]search[/cyan]", "Search local literature and stage results")
    table.add_row("  [cyan]fetch[/cyan]", "Search the internet (CrossRef/arXiv) and lazy-stage results")
    
    table.add_row("", "")
    table.add_row("[bold]🏷️  Organization[/bold]", "")
    table.add_row("  [cyan]tag[/cyan]", "Manage semantic tags for papers")
    table.add_row("  [cyan]star[/cyan]", "Manage star collections (playlists)")
    table.add_row("  [cyan]stage[/cyan]", "Manage the temporary staging area directly")
    table.add_row("  [cyan]comment[/cyan]", "Add or clear a plain-text comment for a paper")
    
    table.add_row("", "")
    table.add_row("[bold]🛠️  Management[/bold]", "")
    table.add_row("  [cyan]show[/cyan]", "Show detailed info or export raw BibTeX")
    table.add_row("  [cyan]export[/cyan]", "Export papers to a clean BibTeX format")
    table.add_row("  [cyan]update[/cyan]", "Update local metadata from online sources")
    table.add_row("  [cyan]link[/cyan]", "Manually link a PDF to an existing paper")
    table.add_row("  [cyan]rm[/cyan]", "Permanently delete papers and their PDFs")
    table.add_row("  [cyan]status[/cyan]", "Show library health and statistics")

    console.print(table)
    
    tips = Panel(
        "Use [bold]:index[/bold] (e.g. [cyan]:1[/cyan]) to target papers from your last search.\n"
        "Use [bold]:all[/bold] to target the entire staging area, or [bold]:db[/bold] for the whole library.\n"
        "Search arguments accept [bold]Boolean Logic[/bold]: [cyan]--tag \"nlp & (vision | audio)\"[/cyan]",
        title="[bold yellow]💡 Targeting & Syntax[/bold yellow]", border_style="yellow"
    )
    console.print(tips)
    console.print("\nRun [bold cyan]bibox help <command>[/bold cyan] for specific examples, or [bold cyan]bibox -h[/bold cyan] for all raw arguments.\n", justify="center")

def get_db() -> BiboxDB:
    db = BiboxDB()
    if not db.is_initialized():
        console.print("[danger]Error:[/danger] Not a Bibox repository (or any of the parent directories).")
        console.print("Run [bold cyan]bibox init[/bold cyan] to initialize one.")
        sys.exit(1)
    return db

def handle_init(args):
    db = BiboxDB(args.path)
    db.initialize_workspace(args.path)
    console.print(f"[bold green]✓[/bold green] Initialized Bibox repository at [cyan]{db.root_dir}[/cyan]")

def handle_status(args):
    db = get_db()
    
    if getattr(args, 'list', False):
        all_papers = list(db.papers.values())
        if not all_papers:
            console.print("The library is currently empty.")
            return
            
        page = args.page
        per_page = 20
        total_pages = (len(all_papers) + per_page - 1) // per_page
        
        if page < 1 or page > total_pages:
            console.print(f"[danger]Error:[/danger] Invalid page number. Available pages: 1 to {total_pages}.")
            return
            
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, len(all_papers))
        
        page_papers = all_papers[start_idx:end_idx]
        
        for paper in page_papers:
            paper._temp_stars = db.get_stars_for_paper(paper.cite_key)
            
        table = create_papers_table(page_papers, start_idx=start_idx+1)
        console.print(table)
        
        if total_pages > 1:
            console.print(f"\n[dim italic]Page {page} of {total_pages}. Run 'bibox status -l -p {page+1}' for the next page.[/dim italic]")
        return

    total_papers = len(db.papers)
    missing_pdf_keys = []
    all_tags = []
    
    for p in db.papers.values():
        has_any_pdf = any(getattr(v, 'has_pdf', False) for v in p.versions.values())
        if not has_any_pdf:
            missing_pdf_keys.append(p.cite_key)
        all_tags.extend(p.tags)
            
    total_stars = len(db.stars)
    unique_tags = len(set(all_tags))
    
    grid = Table.grid(padding=(0, 2))
    grid.add_column("Metric", style="bold cyan", justify="right")
    grid.add_column("Value")
    
    grid.add_row("Library Root", str(db.root_dir))
    grid.add_row("Total Papers", str(total_papers))
    grid.add_row("Missing PDFs", f"[warning]{len(missing_pdf_keys)}[/warning]" if missing_pdf_keys else "[green]0[/green]")
    grid.add_row("Total Stars", str(total_stars))
    grid.add_row("Unique Tags", str(unique_tags))
    
    console.print(Panel(grid, title="[bold]Library Status[/bold]", border_style="cyan"))
    
    if getattr(args, 'detailed', False):
        console.print("")
        if all_tags:
            from collections import Counter
            tag_counts = Counter(all_tags)
            top_tags = tag_counts.most_common(5)
            
            tag_table = Table(title="[bold]Top Tags[/bold]", box=None, padding=(0, 2), show_header=False)
            tag_table.add_column("Tag", style="cyan")
            tag_table.add_column("Count", style="dim")
            for tag, count in top_tags:
                tag_table.add_row(tag, str(count))
            console.print(tag_table)
            
        if db.stars:
            star_table = Table(title="[bold]Star Collections[/bold]", box=None, padding=(0, 2), show_header=False)
            star_table.add_column("Star", style="yellow")
            star_table.add_column("Count", style="dim")
            for star_name, items in db.stars.items():
                star_table.add_row(star_name, str(len(items)))
            console.print(star_table)
            
        if missing_pdf_keys:
            console.print("\n[bold warning]Papers Missing PDFs:[/bold warning]")
            for k in missing_pdf_keys:
                console.print(f"  [dim]-[/dim] {k}")

def _process_import_worker(item, keep_keys=False):
    result = {'item': item, 'type': 'unknown', 'success': False, 'data': None, 'error': None}
    
    try:
        if item.startswith('__ONLINE__'):
            result['type'] = 'online'
            result['success'] = True
            result['data'] = item
            
        elif item.lower().endswith('.pdf'):
            result['type'] = 'pdf'
            if not os.path.exists(item):
                result['error'] = "File not found"
                return result
                
            # --- Hash Short-circuit Check ---
            from .db import BiboxDB
            from pathlib import Path
            db = get_db()
            src_hash = db.get_file_hash(Path(item))
            duplicate_info = db.find_paper_by_pdf_hash(src_hash)
            if duplicate_info:
                dup_paper, dup_v_name = duplicate_info
                result['type'] = 'pdf_duplicate'
                result['success'] = True
                result['data'] = {'paper': dup_paper, 'version_name': dup_v_name}
                return result
            # --------------------------------
                
            extractor = PdfExtractor()
            versions_dict = extractor.extract_info(item)
            if not versions_dict:
                result['error'] = "Auto-extraction failed. Try fetching it online and linking manually."
                return result
                
            # Determine the primary version to use for naming and base metadata
            pdf_self_claim = extractor.get_self_claim_v_name(item)
            non_arxiv_versions = [v for v in versions_dict.keys() if v != 'arxiv']
            
            if len(non_arxiv_versions) == 1:
                primary_v_name = non_arxiv_versions[0]
            elif len(non_arxiv_versions) > 1:
                if pdf_self_claim and pdf_self_claim in non_arxiv_versions:
                    primary_v_name = pdf_self_claim
                else:
                    primary_v_name = sorted(non_arxiv_versions)[0]
            else:
                primary_v_name = 'arxiv' if 'arxiv' in versions_dict else list(versions_dict.keys())[0]
                
            primary_info = versions_dict[primary_v_name]
            
            temp_paper = Paper(primary_info.fields.get('title', 'Unknown'), primary_info.fields.get('author'))
            for v_name, info in versions_dict.items():
                temp_paper.add_version(v_name, info)
                
            result['success'] = True
            result['data'] = {
                'paper': temp_paper, 
                'primary_v_name': primary_v_name, 
                'versions_dict': versions_dict,
                'title': primary_info.fields.get('title', 'Unknown'),
                'pdf_self_claim': pdf_self_claim
            }
            
        elif item.lower().endswith('.bib'):
            result['type'] = 'bibtex'
            if not os.path.exists(item):
                result['error'] = "File not found"
                return result
                
            try:
                with open(item, 'r', encoding='utf-8') as f:
                    bibs_str = f.read()
                infos = Info.from_bibtexes(bibs_str)
                result['success'] = True
                papers = []
                for info in infos:
                    temp_paper = Paper.from_info('imported_bib', info, keep_cite_key=keep_keys)
                    papers.append({'paper': temp_paper, 'info': info, 'title': info.fields.get('title', 'Unknown')})
                result['data'] = papers
            except Exception as e:
                result['error'] = str(e)
    except Exception as e:
        # Catch-all safety net for thread crashes (e.g. 3rd party lib failures)
        result['error'] = f"Internal worker error: {str(e)}"
        
    return result

def handle_import(args):
    db = get_db()
    
    # 1. Flatten and resolve shell globbing
    expanded_raw_targets = []
    for item in args.targets_or_paths:
        if ('*' in item or '?' in item) and not item.startswith(':'):
            matched_files = glob.glob(item)
            if not matched_files:
                console.print(f"[warning]Warning: No files matched pattern '{item}'.[/warning]")
            expanded_raw_targets.extend(matched_files)
        else:
            expanded_raw_targets.append(item)

    if not expanded_raw_targets:
        return
    
    # 2. Resolve targets
    try:
        resolved_items = db.resolve_targets(expanded_raw_targets, allow_online=True)
    except ValueError as e:
        console.print(f"[danger]Error resolving targets:[/danger] {e}")
        return

    # 3. Concurrent Processing
    console.print("")
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=False
        ) as progress:
            task = progress.add_task("[cyan]Importing literature...", total=len(resolved_items))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(_process_import_worker, item, args.keep_keys): item for item in resolved_items}
                
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    item = res['item']
                    
                    # Render tree and write to DB sequentially in main thread
                    if res['type'] == 'online':
                        if res['success']:
                            try:
                                real_key = db.materialize_online_paper(res['data'])
                                tree = Tree(f"[bold green]\\[Online][/bold green] Successfully materialized")
                                tree.add(f"Saved As: [cyan]{real_key}[/cyan]")
                                console.print(tree)
                            except ValueError as e:
                                console.print(f"[bold green]\\[Online][/bold green] [danger]Error: {e}[/danger]")
                    
                    elif res['type'] == 'pdf_duplicate':
                        dup_paper = res['data']['paper']
                        dup_v_name = res['data']['version_name']
                        tree = Tree(f"[bold cyan]\\[PDF][/bold cyan] {item}")
                        tree.add(f"Action:   [yellow]Skipped[/yellow] (Already exists in '{dup_paper.cite_key}' as version '{dup_v_name}')")
                        console.print(tree)
                        
                    elif res['type'] == 'pdf':
                        if not res['success']:
                            console.print(f"[bold cyan]\\[PDF][/bold cyan] {item}")
                            console.print(f"  └── [warning]{res['error']}[/warning]")
                        else:
                            data = res['data']
                            temp_paper = data['paper']
                            primary_v_name = data['primary_v_name']
                            versions_dict = data['versions_dict']
                            cite_key = temp_paper.cite_key
                            
                            tree = Tree(f"[bold cyan]\\[PDF][/bold cyan] {item}")
                            tree.add(f"Title:    [white]{data['title']}[/white]")
                            versions_str = ", ".join(versions_dict.keys())
                            tree.add(f"Versions: [magenta]{versions_str}[/magenta]")
                            
                            existing_paper = db.get_paper(cite_key)
                            if existing_paper:
                                tree.add(f"Action:   [yellow]Merged[/yellow] into existing '{cite_key}'")
                                for v_name, info in versions_dict.items():
                                    existing_paper.add_version(v_name, info)
                                db.import_pdf_file(item, existing_paper, primary_v_name, data.get('pdf_self_claim'))
                            else:
                                tree.add(f"Action:   [green]Created[/green] new paper '{cite_key}'")
                                db.import_pdf_file(item, temp_paper, primary_v_name, data.get('pdf_self_claim'))
                                
                            console.print(tree)
                            
                    elif res['type'] == 'bibtex':
                        if not res['success']:
                            console.print(f"[bold yellow]\\[BibTeX][/bold yellow] {item}")
                            console.print(f"  └── [danger]{res['error']}[/danger]")
                        else:
                            papers_data = res['data']
                            tree = Tree(f"[bold yellow]\\[BibTeX][/bold yellow] {item}")
                            tree.add(f"Parsed [cyan]{len(papers_data)}[/cyan] valid entries")
                            
                            for p_data in papers_data:
                                temp_paper = p_data['paper']
                                cite_key = temp_paper.cite_key
                                existing_paper = db.get_paper(cite_key)
                                
                                if existing_paper:
                                    existing_paper.add_version('imported_bib', p_data['info'], keep_cite_key=args.keep_keys)
                                    db.add_paper(existing_paper)
                                else:
                                    db.add_paper(temp_paper)
                                    
                            console.print(tree)
                    
                    else:
                        console.print(f"[warning]\\[Warning][/warning] Unrecognized target: {item}")
                    
                    progress.advance(task)
                    
        console.print("\n[bold green]Import complete.[/bold green]")
    except KeyboardInterrupt:
        console.show_cursor(True)
        console.print("\n[bold red]Aborted by user.[/bold red]")
        import os
        os._exit(130)

def star_completer(prefix, parsed_args, **kwargs):
    """Dynamically read db.json for star names to provide completion."""
    try:
        # We need to find the db.json manually since this runs during tab completion
        from pathlib import Path
        import json
        
        current = Path.cwd()
        db_path = None
        while True:
            candidate = current / '.bibox' / 'db.json'
            if candidate.exists():
                db_path = candidate
                break
            if current.parent == current:
                break
            current = current.parent
            
        if not db_path:
            return []
            
        with open(db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            stars = data.get('stars', {})
            return [s for s in stars.keys() if s.startswith(prefix)]
    except:
        return []

def target_completer(prefix, parsed_args, **kwargs):
    """Provides completion for indices :1, :all and cite_keys."""
    try:
        from pathlib import Path
        import json
        
        current = Path.cwd()
        bibox_dir = None
        while True:
            candidate = current / '.bibox'
            if candidate.exists():
                bibox_dir = candidate
                break
            if current.parent == current:
                break
            current = current.parent
            
        if not bibox_dir:
            return []
            
        suggestions = [':all', ':db']
        
        # Add staging indices
        try:
            with open(bibox_dir / 'staging.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                results = data.get('results', {})
                for idx in results.keys():
                    suggestions.append(f":{idx}")
        except:
            pass
            
        # Add cite_keys
        try:
            with open(bibox_dir / 'db.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                papers = data.get('papers', {})
                suggestions.extend(papers.keys())
        except:
            pass
            
        return [s for s in suggestions if s.startswith(prefix)]
    except:
        return []
def create_papers_table(papers: list, start_idx: int, is_online: bool = False, append_mode: bool = False) -> Table:
    table = Table(show_header=True, header_style="bold magenta", border_style="dim")
    table.add_column("Index", style="cyan", justify="right", width=6)
    table.add_column("Key / Source", style="dim", width=25)
    table.add_column("Title", style="bold")
    table.add_column("Tags & Meta", justify="right")
    
    db = get_db()
    
    for i, paper in enumerate(papers, start_idx):
        idx_str = f":{i}"
        
        is_temp_online = paper.cite_key.startswith("__ONLINE__")
        
        if is_temp_online:
            display_key = "[cyan][Online][/cyan]"
            tags_str = "🌐"
            versions = [f"{v_name}" for v_name in paper.versions.keys()]
        else:
            display_key = paper.cite_key
            tags_str = f"🏷️  {', '.join(paper.tags)}" if paper.tags else ""
            
            # Highlight if it has a comment
            if paper.comment:
                tags_str += " 💬"
                
            # Add star indicators
            if hasattr(paper, '_temp_stars') and paper._temp_stars:
                tags_str += " ⭐ " + ", ".join(paper._temp_stars)
                
            versions = []
            for v_name, state in paper.versions.items():
                if getattr(state, 'has_pdf', False) and getattr(state, 'pdf_path', None) and db.root_dir:
                    abs_pdf_path = (db.root_dir / state.pdf_path).resolve()
                    pdf_uri = abs_pdf_path.as_uri()
                    versions.append(f"{v_name}([link={pdf_uri}]PDF[/link])")
                else:
                    versions.append(f"{v_name}")
        
        meta_str = tags_str + f"\n[dim]{', '.join(versions)}[/dim]"
        
        table.add_row(idx_str, display_key, paper.title, meta_str)
        
    return table

def handle_search(args):
    db = get_db()
    
    results = db.search_papers(
        query=args.query, 
        tag=args.tag, 
        star=args.star,
        author=args.author, 
        year=args.year, 
        title=args.title
    )
    
    if not results:
        print("No matches found.")
        if not args.temp and not args.append:
            db.clear_staging()
        return
        
        print(f"Found {len(results)} matches:\n")
    cite_keys = []
    
    # Calculate starting index for display
    start_idx = 1
    if args.append and not args.temp:
        data = db.read_staging()
        existing_indices = [int(k) for k in data["results"].keys() if k.isdigit()]
        if existing_indices:
            start_idx = max(existing_indices) + 1

    for paper in results:
        cite_keys.append(paper.cite_key)
        # Pre-fetch stars for display
        stars = db.get_stars_for_paper(paper.cite_key)
        paper._temp_stars = stars
        
    table = create_papers_table(results, start_idx)
    console.print(table)
        
    if not args.temp:
        db.save_staging(cite_keys, append=args.append)
        console.print("[dim italic]Tip: Use ':index' (e.g., ':1') in subsequent commands to manipulate these papers.[/dim italic]")
    else:
        console.print("[dim](Temporary search: staging area unchanged)[/dim]")

def handle_tag(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets([args.target])
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        sys.exit(1)
        
    if not cite_keys:
        console.print("No papers matched the target.")
        return
        
    for cite_key in cite_keys:
        paper = db.get_paper(cite_key)
        if not paper:
            console.print(f"[warning]Warning:[/warning] Target '{cite_key}' not found in database, ignored.")
            continue
            
        if args.tag_action == 'add':
            paper.add_tags(*args.tags)
            db.add_paper(paper)
            console.print(f"Added tags {args.tags} to {cite_key}.")
        elif args.tag_action == 'remove':
            for t in args.tags:
                t = t.lower().strip()
                if t in paper.tags:
                    paper.tags.remove(t)
            db.add_paper(paper)
            console.print(f"Removed tags {args.tags} from {cite_key}.")

def handle_star(args):
    db = get_db()
    
    if args.star_action == 'list':
        if not db.stars:
            print("No star collections found.")
            return
        for star_name, items in db.stars.items():
            print(f"- {star_name} ({len(items)} papers)")
        return
        
    if args.star_action == 'show':
        if args.star_name not in db.stars:
            print(f"Star collection '{args.star_name}' not found.")
            return
            
        cite_keys = db.stars[args.star_name]
        if not cite_keys:
            print(f"Star collection '{args.star_name}' is empty.")
            return
            
        db.save_staging(cite_keys)
        
        print(f"Showing {len(cite_keys)} papers from star '{args.star_name}':\n")
        for i, cite_key in enumerate(cite_keys, 1):
            paper = db.get_paper(cite_key)
            if paper:
                print(f"[{i}] {paper.cite_key}: {paper.title}")
            else:
                print(f"[{i}] {cite_key} (Paper not found in DB)")
        return

    try:
        cite_keys = db.resolve_targets(args.targets)
    except ValueError as e:
        print(f"Error: {e}")
        return
        
    if not cite_keys:
        print("No papers matched the targets.")
        return

    if args.star_action == 'add':
        for cite_key in cite_keys:
            if not db.get_paper(cite_key):
                console.print(f"[warning]Warning:[/warning] Target '{cite_key}' not found in database, ignored.")
                continue
            try:
                db.add_to_star(args.star_name, cite_key)
                console.print(f"Added '{cite_key}' to star '{args.star_name}'.")
            except ValueError as e:
                console.print(f"[danger]Error:[/danger] {e}")
                return
    elif args.star_action == 'remove':
        for cite_key in cite_keys:
            db.remove_from_star(args.star_name, cite_key)
            console.print(f"Removed '{cite_key}' from star '{args.star_name}'.")

def handle_stage(args):
    db = get_db()
    
    if args.stage_action == 'status':
        data = db.read_staging()
        results = data.get("results", {})
        if not results:
            console.print("[dim]Staging area is empty.[/dim]")
            return
            
        console.print(f"Staging area contains [bold]{len(results)}[/bold] items:\n")
        
        # Build dummy paper list for table rendering
        sorted_indices = sorted(results.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        display_papers = []
        
        for idx in sorted_indices:
            key = results[idx]
            if key.startswith('__ONLINE__'):
                info_dict = data.get("online_data", {}).get(key, {})
                dummy = Paper(info_dict.get('fields', {}).get('title', 'Unknown Online Paper'))
                dummy.cite_key = key
                dummy.add_version('online', Info.from_dict(info_dict))
                display_papers.append(dummy)
            else:
                paper = db.get_paper(key)
                if paper:
                    paper._temp_stars = db.get_stars_for_paper(paper.cite_key)
                    display_papers.append(paper)
                else:
                    dummy = Paper(f"<{key} NOT FOUND IN DB>")
                    dummy.cite_key = key
                    display_papers.append(dummy)
                    
        # Find minimum starting index
        start_idx = int(sorted_indices[0]) if sorted_indices and sorted_indices[0].isdigit() else 1
        
        table = create_papers_table(display_papers, start_idx)
        console.print(table)
                    
    elif args.stage_action == 'clear':
        db.clear_staging()
        print("Staging area cleared.")
        
    elif args.stage_action == 'add':
        try:
            raw_keys = db.resolve_targets(args.targets)
            valid_keys = []
            for k in raw_keys:
                if db.get_paper(k):
                    valid_keys.append(k)
                else:
                    console.print(f"[warning]Warning:[/warning] Target '{k}' not found in database, ignored.")
                    
            if valid_keys:
                db.save_staging(valid_keys, append=True)
                console.print(f"Appended {len(valid_keys)} valid items to staging.")
            else:
                console.print("No valid papers to stage.")
        except Exception as e:
            console.print(f"[danger]Error:[/danger] {e}")
            
    elif args.stage_action == 'remove':
        data = db.read_staging()
        results = data.get("results", {})
        removed = 0
        for idx_str in args.indices:
            idx = idx_str.lstrip(':')
            if idx in results:
                del results[idx]
                removed += 1
        with open(db.staging_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        console.print(f"Removed {removed} items from staging.")

def handle_link(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets([args.target])
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        return
        
    if not cite_keys:
        return
    cite_key = cite_keys[0] # Usually link 1 file to 1 paper
        
    paper = db.get_paper(cite_key)
    if not paper:
        console.print(f"[danger]Error:[/danger] Target '{cite_key}' not found in database.")
        return
        
    if args.link_type == 'pdf':
        non_arxiv = [v for v in paper.versions if v != 'arxiv']
        if non_arxiv:
            v_name = non_arxiv[0]
        elif paper.versions:
            v_name = list(paper.versions.keys())[0]
        else:
            console.print(f"[warning]Warning: No versions exist for this paper. Cannot link PDF without info.[/warning]")
            console.print("Run 'bibox update' or import info first.")
            return
            
        success = db.import_pdf_file(args.file_path, paper, v_name)
        if success:
            console.print(f"Successfully linked PDF to {cite_key} (version: {v_name})")

def handle_comment(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets([args.target])
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        return
        
    if not cite_keys:
        return
    cite_key = cite_keys[0]
        
    paper = db.get_paper(cite_key)
    if not paper:
        console.print(f"[danger]Error:[/danger] Target '{cite_key}' not found in database.")
        return
        
    if not cite_keys:
        return
    cite_key = cite_keys[0]
        
    paper = db.get_paper(cite_key)
    if not paper:
        console.print(f"[danger]Error:[/danger] Target '{cite_key}' not found in database.")
        return
        
    if args.clear:
        paper.comment = ""
        db.add_paper(paper)
        console.print(f"Cleared comment for '{cite_key}'.")
    elif args.text:
        paper.comment = args.text
        db.add_paper(paper)
        console.print(f"Updated comment for '{cite_key}'.")
    else:
        console.print("[warning]Please provide comment text or use -c to clear.[/warning]")

def handle_rm(args):
    db = get_db()
    try:
        raw_keys = db.resolve_targets(args.targets)
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        return
        
    if not raw_keys:
        console.print("No papers matched the targets.")
        return
        
    valid_keys = []
    for k in raw_keys:
        if db.get_paper(k):
            valid_keys.append(k)
        else:
            console.print(f"[warning]Warning:[/warning] Target '{k}' not found in database, ignored.")
            
    if not valid_keys:
        console.print("No valid papers to delete.")
        return
        
    console.print(f"[bold red]WARNING:[/bold red] You are about to permanently delete {len(valid_keys)} paper(s) from your database.")
    if not args.keep_pdf:
        console.print("This will ALSO delete their associated PDF files from the disk.")
        
    if not getattr(args, 'yes', False):
        confirm = input("Are you sure you want to proceed? [y/N]: ").strip().lower()
        if confirm != 'y':
            console.print("Aborted.")
            return
        
    deleted = 0
    for cite_key in valid_keys:
        db.remove_paper(cite_key, keep_pdf=args.keep_pdf)
        deleted += 1
            
    console.print(f"Successfully deleted {deleted} paper(s).")

def handle_show(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets(args.targets, allow_online=True)
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        return
        
    if not cite_keys:
        console.print("No papers matched the targets.")
        return
        
    for i, cite_key in enumerate(cite_keys):
        if cite_key.startswith('__ONLINE__'):
            data = db.read_staging()
            info_dict = data.get("online_data", {}).get(cite_key)
            if not info_dict:
                console.print(f"[warning]Warning: Online data for {cite_key} not found or expired.[/warning]")
                continue
                
            info = Info.from_dict(info_dict)
            from .info_getter import ApiGetter
            v_name = ApiGetter()._determine_version_name(info)
            paper = Paper(info.fields.get('title', 'Unknown'), info.fields.get('author'))
            paper.cite_key = cite_key
            paper.add_version(v_name, info)
        else:
            paper = db.get_paper(cite_key)
            if not paper:
                console.print(f"[danger]Error:[/danger] Paper '{cite_key}' not found.")
                continue
            
        if i > 0:
            console.print("\n" + "="*50 + "\n")
            
        if args.bibtex:
            if args.bibtex == '__all__':
                for v_name, v_state in paper.versions.items():
                    console.print(f"%% Version: {v_name} %%")
                    syntax = Syntax(v_state.info.to_bibtex(), "bibtex", theme="ansi_dark", word_wrap=True)
                    console.print(syntax)
                    console.print("")
            else:
                v_name = args.bibtex.lower()
                if v_name in paper.versions:
                    syntax = Syntax(paper.versions[v_name].info.to_bibtex(), "bibtex", theme="ansi_dark", word_wrap=True)
                    console.print(syntax)
                else:
                    console.print(f"[danger]Error:[/danger] Version '{v_name}' not found for paper '{cite_key}'. Available versions: {list(paper.versions.keys())}")
        else:
            # Print detailed readable info
            grid = Table.grid(padding=(0, 2))
            grid.add_column("Key", style="bold cyan", justify="right")
            grid.add_column("Value")
            
            if cite_key.startswith('__ONLINE__'):
                grid.add_row("Status", "[bold green][Online Preview][/bold green] (Not imported)")
            else:
                grid.add_row("Cite Key", paper.cite_key)
            
            tags_str = ", ".join(paper.tags) if paper.tags else "[dim]None[/dim]"
            grid.add_row("Tags", tags_str)
            
            stars = db.get_stars_for_paper(cite_key)
            stars_str = ", ".join(stars) if stars else "[dim]None[/dim]"
            grid.add_row("Stars", stars_str)
            
            if paper.comment:
                grid.add_row("Comment", f"[italic]{paper.comment}[/italic]")
                
            # Version tree
            versions_content = ""
            for v_name, v_state in paper.versions.items():
                versions_content += f"[bold magenta]- \\[{v_name}][/bold magenta]\n"
                fields = v_state.info.fields
                
                author = fields.get('author', 'Unknown')
                if len(author) > 60:
                    author = author[:57] + "..."
                versions_content += f"  Author:  {author}\n"
                versions_content += f"  Year:    {fields.get('year', 'Unknown')}\n"
                
                venue = fields.get('journal') or fields.get('booktitle') or fields.get('publisher') or 'Unknown'
                versions_content += f"  Venue:   {venue}\n"
                
                if fields.get('doi'):
                    versions_content += f"  DOI:     {fields.get('doi')}\n"
                if fields.get('eprint') and fields.get('archiveprefix', '').lower() == 'arxiv':
                    versions_content += f"  arXiv:   {fields.get('eprint')}\n"
                    
                if getattr(v_state, 'pdf_path', None) and db.root_dir:
                    abs_pdf_path = (db.root_dir / v_state.pdf_path).resolve()
                    pdf_uri = abs_pdf_path.as_uri()
                    pdf_str = f"[link={pdf_uri}]{v_state.pdf_path}[/link]"
                else:
                    pdf_str = "[dim]None[/dim]"
                    
                versions_content += f"  PDF:     {pdf_str}\n\n"
            
            panel_content = Table.grid(padding=1)
            panel_content.add_row(grid)
            panel_content.add_row("\n[bold]Versions[/bold]")
            panel_content.add_row(versions_content.strip())
            
            panel = Panel(panel_content, title=f"[bold]{paper.title}[/bold]", title_align="left", border_style="cyan")
            console.print(panel)

def handle_export(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets(args.targets)
    except ValueError as e:
        console.print(f"[danger]Error:[/danger] {e}")
        return
        
    if not cite_keys:
        console.print("No papers matched the targets.")
        return
        
    exported = 0
    for cite_key in cite_keys:
        paper = db.get_paper(cite_key)
        if not paper:
            continue
            
        versions_avail = list(paper.versions.keys())
        if not versions_avail:
            continue
            
        target_v_name = None
        
        if args.no_arxiv:
            # Filter out arxiv completely
            non_arxiv = [v for v in versions_avail if v != 'arxiv']
            if not non_arxiv:
                logging.debug(f"Skipping {cite_key} because it only has 'arxiv' version and --no-arxiv is set.")
                continue
            target_v_name = non_arxiv[0]
        else:
            # Prefer any non-arxiv > 'arxiv'
            non_arxiv = [v for v in versions_avail if v != 'arxiv']
            if non_arxiv:
                target_v_name = non_arxiv[0]
            else:
                target_v_name = 'arxiv'
                
        if target_v_name and target_v_name in paper.versions:
            print(f"%% Exported from {cite_key} ({target_v_name}) %%")
            print(paper.versions[target_v_name].info.to_bibtex())
            print("")
            exported += 1
            
    if exported == 0:
        console.print("[warning]Warning: No papers were exported based on the criteria.[/warning]")

from rich.spinner import Spinner

def handle_fetch(args):
    api = ApiGetter()
    console.print(f"Fetching metadata online for query: [cyan]'{args.query}'[/cyan]...")
    
    with console.status("[bold green]Querying CrossRef/arXiv APIs...[/bold green]", spinner="dots"):
        versions = api.fetch(args.query)
    
    if not versions:
        console.print("[warning]No results found.[/warning]")
        return
        
    if args.temp:
        for v_name, info in versions.items():
            print(f"\n--- Version: {v_name} ---")
            print(info.to_bibtex())
        print("\n(Temporary fetch: staging area unchanged)")
        return
        
    # Standard behavior: stage the online results for lazy import
    db = get_db()
    online_infos = {}
    cite_keys = []
    
    start_idx = 1
    if args.append:
        data = db.read_staging()
        existing_indices = [int(k) for k in data["results"].keys() if k.isdigit()]
        if existing_indices:
            start_idx = max(existing_indices) + 1

    console.print(f"Found [bold]{len(versions)}[/bold] online matches:\n")
    
    for i, (v_name, info) in enumerate(versions.items(), start_idx):
        temp_key = f"__ONLINE__{info.cite_key}_{v_name}"
        online_infos[temp_key] = info
        cite_keys.append(temp_key)
        
        console.print(f"[[cyan]{i}[/cyan]] [cyan][Online][/cyan] {info.cite_key}: {info.fields.get('title', 'Unknown')}")
        console.print(f"     [dim]Versions: {v_name}[/dim]")
        console.print("")
        
    db.save_staging(cite_keys, append=args.append, online_infos=online_infos)
    console.print("[dim italic]Tip: These papers are temporary. Use 'bibox import :index' to permanently add them to your library.[/dim italic]")

def handle_update(args):
    db = get_db()
    try:
        cite_keys = db.resolve_targets(args.targets)
    except ValueError as e:
        print(f"Error: {e}")
        return
        
    if not cite_keys:
        print("No papers matched the targets.")
        return
        
    api = ApiGetter()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False
    ) as progress:
        task = progress.add_task("[cyan]Updating literature...", total=len(cite_keys))
        
        for cite_key in cite_keys:
            paper = db.get_paper(cite_key)
            if not paper:
                console.print(f"[danger]Error:[/danger] Paper '{cite_key}' not found.")
                progress.advance(task)
                continue
                
            tree = Tree(f"[bold cyan]\\[Update][/bold cyan] {cite_key}")
            tree.add(f"Title: [white]{paper.title}[/white]")
                
            # --- PDF Integrity Check & Self-Healing ---
            for v_name, v_state in paper.versions.items():
                if getattr(v_state, 'pdf_path', None):
                    abs_path = db.root_dir / v_state.pdf_path
                    if abs_path.exists():
                        if not getattr(v_state, 'pdf_hash', None):
                            v_state.pdf_hash = db.get_file_hash(abs_path)
                            tree.add(f"Action: [dim]Computed missing PDF hash for version '{v_name}'[/dim]")
                    else:
                        known_hash = getattr(v_state, 'pdf_hash', None)
                        found_new_path = None
                        if known_hash:
                            found_new_path = db.find_pdf_file_by_hash(known_hash)
                        
                        if found_new_path:
                            v_state.pdf_path = found_new_path
                            tree.add(f"Action: [bold yellow]Relinked[/bold yellow] missing PDF for '{v_name}' to: {found_new_path}")
                        else:
                            v_state.pdf_path = None
                            v_state.pdf_hash = None
                            tree.add(f"Action: [bold red]Warning:[/bold red] Physical PDF for '{v_name}' is missing and could not be recovered.")
            db.add_paper(paper) # Save hash/relink changes immediately
            # ------------------------------------------
                
            # --- Stable Query Selection ---
            # Prioritize: 1. Real Publisher DOI, 2. ArXiv ID, 3. Title
            # This prevents oscillating queries if APIs return pseudo-DOIs for preprints
            best_doi = None
            best_arxiv = None
            
            for v_state in paper.versions.values():
                fields = v_state.info.fields
                candidate_doi = fields.get('doi', '').lower()
                
                # Check for real DOI (exclude arXiv pseudo-DOIs)
                if candidate_doi and 'arxiv' not in candidate_doi:
                    best_doi = candidate_doi
                    
                # Check for explicit arXiv eprint
                if fields.get('eprint') and fields.get('archiveprefix', '').lower() == 'arxiv':
                    best_arxiv = fields.get('eprint')
            
            query = best_doi or best_arxiv or paper.title
            # ------------------------------
                
            tree.add(f"Query: [dim]{query}[/dim]")
            versions = api.fetch(query)
            
            if not versions:
                tree.add("Result: [dim]No new information found online.[/dim]")
            else:
                added = 0
                updated_versions = []
                for v_name, info in versions.items():
                    if v_name not in paper.versions:
                        paper.add_version(v_name, info)
                        added += 1
                        updated_versions.append(f"[green]Added {v_name}[/green]")
                    else:
                        # Deep compare to check if there's actual change
                        import json
                        old_fields_json = json.dumps(paper.versions[v_name].info.fields, sort_keys=True)
                        new_fields_json = json.dumps(info.fields, sort_keys=True)
                        
                        if old_fields_json != new_fields_json:
                            paper.add_version(v_name, info)
                            updated_versions.append(f"[cyan]Updated {v_name}[/cyan]")
                
                # --- Cascading Key Update (if requested) ---
                key_updated_str = ""
                if getattr(args, 'update_keys', False):
                    # Gather all titles from all versions
                    all_titles = []
                    all_authors = []
                    for v in paper.versions.values():
                        if v.info.fields.get('title'):
                            all_titles.append(v.info.fields.get('title'))
                            all_authors.append(v.info.fields.get('author'))
                            
                    if all_titles:
                        # Sort lexicographically and pick the first one
                        sorted_idx = min(range(len(all_titles)), key=lambda i: all_titles[i].lower())
                        best_title = all_titles[sorted_idx]
                        best_author = all_authors[sorted_idx]
                        
                        new_cite_key = paper._generate_cite_key(best_author, title_override=best_title)
                        
                        if new_cite_key != paper.cite_key:
                            old_cite_key = paper.cite_key
                            db.rename_paper_key(paper, new_cite_key) # This will cascade to stars, versions, and pdf files
                            key_updated_str = f"\n  ├── Action: [magenta]CiteKey Regenerated[/magenta] ({old_cite_key} -> {new_cite_key})"
                            paper.cite_key = new_cite_key
                # -------------------------------------------
                
                db.add_paper(paper)
                versions_str = ", ".join(updated_versions)
                if added > 0 or updated_versions:
                    tree.add(f"Result: Successfully updated{key_updated_str}\n  └── Changes: {versions_str}")
                else:
                    tree.add(f"Result: [dim]Everything is up-to-date. No new changes found.[/dim]{key_updated_str}")
                    
            console.print(tree)
            progress.advance(task)
            
    console.print("\n[bold green]Update complete.[/bold green]")

def handle_helphelp(args):
    # This is handled mostly in main's interception, but just in case it reaches here
    print("no help for you")

def get_shell_profiles() -> List[tuple]:
    """Detect shell and return the appropriate profile path and shell name."""
    profiles = []
    
    # Windows PowerShell
    if os.name == 'nt':
        user_profile = os.environ.get('USERPROFILE', '')
        if user_profile:
            # PowerShell Core / PowerShell 7+
            pwsh_profile = Path(user_profile) / 'Documents' / 'PowerShell' / 'Microsoft.PowerShell_profile.ps1'
            # Windows PowerShell 5.1
            winps_profile = Path(user_profile) / 'Documents' / 'WindowsPowerShell' / 'Microsoft.PowerShell_profile.ps1'
            
            profiles.append(('powershell', pwsh_profile))
            profiles.append(('powershell', winps_profile))
            
    # Unix-like (Linux/macOS)
    else:
        home = Path.home()
        shell_env = os.environ.get('SHELL', '').lower()
        
        if 'zsh' in shell_env:
            profiles.append(('zsh', home / '.zshrc'))
        elif 'bash' in shell_env:
            profiles.append(('bash', home / '.bashrc'))
            
        # Fallback if SHELL is not reliable
        if not profiles:
            if (home / '.zshrc').exists():
                profiles.append(('zsh', home / '.zshrc'))
            if (home / '.bashrc').exists():
                profiles.append(('bash', home / '.bashrc'))
                
    return profiles

MARKER_START = "# >>> BIBOX COMPLETION START >>>"
MARKER_END = "# <<< BIBOX COMPLETION END <<<"

def handle_enable(args):
    if args.feature == 'completion':
        profiles = get_shell_profiles()
        if not profiles:
            console.print("[red]Could not detect a supported shell (bash, zsh, powershell).[/red]")
            return
            
        try:
            import argcomplete.shell_integration as asi
        except ImportError:
            console.print("[red]argcomplete is not installed.[/red]")
            return
            
        success_profiles = []
        for shell_name, profile_path in profiles:
            try:
                code = asi.shellcode(['bibox'], use_defaults=True, shell=shell_name, complete_arguments=None)
            except Exception:
                if shell_name == 'bash' or shell_name == 'zsh':
                     code = f'eval "$(register-python-argcomplete bibox)"\n'
                elif shell_name == 'powershell':
                     code = f'Invoke-Expression (register-python-argcomplete --shell powershell bibox)\n'
                else:
                     continue
                     
            if not profile_path.parent.exists():
                try:
                    profile_path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    continue
                    
            content = ""
            if profile_path.exists():
                try:
                    with open(profile_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(profile_path, 'r') as f:
                        content = f.read()
                        
            if MARKER_START in content:
                console.print(f"[yellow]Completion already enabled in {profile_path}[/yellow]")
                success_profiles.append(profile_path)
                continue
                
            block = f"\n{MARKER_START}\n{code}\n{MARKER_END}\n"
            try:
                with open(profile_path, 'a', encoding='utf-8') as f:
                    f.write(block)
                success_profiles.append(profile_path)
            except Exception as e:
                console.print(f"[red]Failed to write to {profile_path}: {e}[/red]")
                
        if success_profiles:
            console.print("[green]✔ Tab completion successfully injected into:[/green]")
            for p in success_profiles:
                console.print(f"  [dim]- {p}[/dim]")
            console.print("\n[bold]Please restart your terminal[/bold] or run `source <profile_path>` to apply changes.")

def handle_disable(args):
    if args.feature == 'completion':
        profiles = get_shell_profiles()
        if not profiles:
            console.print("[red]Could not detect a supported shell profile to clean.[/red]")
            return
            
        success_profiles = []
        for shell_name, profile_path in profiles:
            if not profile_path.exists():
                continue
                
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(profile_path, 'r') as f:
                    content = f.read()
                    
            if MARKER_START not in content:
                continue
                
            pattern = re.compile(rf'\n?{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}\n?', re.DOTALL)
            new_content = pattern.sub('\n', content)
            
            try:
                with open(profile_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                success_profiles.append(profile_path)
            except Exception as e:
                console.print(f"[red]Failed to write cleaned profile to {profile_path}: {e}[/red]")
                
        if success_profiles:
            console.print("[green]✔ Tab completion successfully removed from:[/green]")
            for p in success_profiles:
                console.print(f"  [dim]- {p}[/dim]")
        else:
            console.print("[yellow]No completion block found to disable.[/yellow]")

def handle_list_config():
    """Show the overall configuration and state of Bibox."""
    import platform
    import importlib.metadata
    
    # 1. Print header
    try:
        version = importlib.metadata.version('bibox')
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    console.print(f"[bold cyan]Bibox Configuration[/bold cyan] (v{version})\n")
    
    # 2. System and Environment
    sys_table = Table(show_header=False, box=None, padding=(0, 2))
    sys_table.add_column("Key", style="bold")
    sys_table.add_column("Value")
    sys_table.add_row("Python", f"{platform.python_version()}")
    sys_table.add_row("OS Platform", f"{platform.system()} {platform.release()}")
    
    current_db_path = None
    try:
        from .db import BiboxDB
        db = BiboxDB()
        if db.is_initialized():
            current_db_path = str(db.root_dir)
            
            paper_count = len(db.papers)
            pdf_count = len(glob.glob(str(db.root_dir / "pdfs" / "*.pdf")))
            sys_table.add_row("Current Library", f"[green]{current_db_path}[/green]")
            sys_table.add_row("Library Stats", f"{paper_count} entries, {pdf_count} PDFs attached")
        else:
            sys_table.add_row("Current Library", "[dim italic]Not initialized in current path tree[/dim italic]")
    except Exception as e:
        sys_table.add_row("Current Library", f"[red]Error accessing database: {e}[/red]")

    console.print("[bold cyan]Environment Information[/bold cyan]")
    console.print(sys_table)
    console.print()
    
    # 3. Features
    feat_table = Table(title=None, box=None, padding=(0, 2), show_header=True)
    feat_table.add_column("Feature", style="bold")
    feat_table.add_column("Status")
    feat_table.add_column("Location / Detail", style="dim")
    
    # Check Completion Status
    profiles = get_shell_profiles()
    completion_found_any = False
    
    for shell_name, profile_path in profiles:
        status = "[red]Disabled[/red]"
        if profile_path.exists():
            try:
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if MARKER_START in content:
                    status = "[green]Enabled[/green]"
                    completion_found_any = True
            except Exception:
                status = "[yellow]Error Reading[/yellow]"
                
        display_shell_name = shell_name
        if shell_name == 'powershell':
            if 'WindowsPowerShell' in str(profile_path):
                display_shell_name = 'powershell (v5.1)'
            else:
                display_shell_name = 'pwsh (v7+)'
                
        feat_table.add_row(f"Tab Completion ({display_shell_name})", status, str(profile_path))
        
    console.print("[bold cyan]Registered Features[/bold cyan]")
    console.print(feat_table)

def main(argv: Optional[List[str]] = None):
    # Intercept -h or --help for subcommands to route them to our rich handle_help
    if argv is None:
        argv = sys.argv[1:]
        
    if 'helphelp' in argv:
        if '-h' in argv or '--help' in argv:
            console.print(Panel("[bold red]NO HELP FOR YOU[/bold red]", border_style="red", padding=(2, 4)))
            sys.exit(0)
        else:
            print("no help for you")
            sys.exit(0)
        
    if '-h' in argv or '--help' in argv:
        # Check if they asked for help on a specific subcommand (e.g. bibox search -h)
        subcommand = None
        for arg in argv:
            if arg not in ('-h', '--help', '--debug'):
                subcommand = arg
                break
        
        handle_help(argparse.Namespace(help_target=subcommand))
        sys.exit(0)

    parser = setup_parser()
    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)

    if args.list_config:
        handle_list_config()
        sys.exit(0)

    if args.help:
        handle_help(argparse.Namespace(help_target=None))
        sys.exit(0)
    
    if not hasattr(args, 'command') or not args.command:
        print_logo()
        sys.exit(0)

    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = getattr(logging, args.log_level.upper())

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, markup=True, rich_tracebacks=True)]
    )

    # Route to handlers
    try:
        if args.command == 'help':
            handle_help(args)
        elif args.command == 'init':
            handle_init(args)
        elif args.command == 'status':
            handle_status(args)
        elif args.command == 'import':
            handle_import(args)
        elif args.command == 'search':
            handle_search(args)
        elif args.command == 'tag':
            handle_tag(args)
        elif args.command == 'link':
            handle_link(args)
        elif args.command == 'comment':
            handle_comment(args)
        elif args.command == 'rm':
            handle_rm(args)
        elif args.command == 'fetch':
            handle_fetch(args)
        elif args.command == 'update':
            handle_update(args)
        elif args.command == 'star':
            handle_star(args)
        elif args.command == 'stage':
            handle_stage(args)
        elif args.command == 'show':
            handle_show(args)
        elif args.command == 'export':
            handle_export(args)
        elif args.command == 'enable':
            handle_enable(args)
        elif args.command == 'disable':
            handle_disable(args)
        elif args.command == 'helphelp':
            handle_helphelp(args)
        else:
            handle_help(argparse.Namespace(help_target=args.command))
    except KeyboardInterrupt:
        console.show_cursor(True)
        console.print("\n[bold red]Aborted by user.[/bold red]")
        import os
        os._exit(130)
    except Exception as e:
        logging.error(f"Error executing command '{args.command}': {e}")
        if args.debug:
            raise
        sys.exit(1)

if __name__ == "__main__":
    main()
