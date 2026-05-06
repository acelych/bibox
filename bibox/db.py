import os
import json
import logging
import shutil
import glob
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from .paper import Paper

class BiboxDB:
    def __init__(self, start_path: Optional[str] = None):
        """
        Initialize the DB manager. If start_path is provided, it will traverse up
        to find the `.bibox` root.
        """
        self.root_dir: Optional[Path] = None
        self.bibox_dir: Optional[Path] = None
        self.db_path: Optional[Path] = None
        
        self.papers: Dict[str, Paper] = {}
        self.stars: Dict[str, List[str]] = {}  # star_name -> list of cite_keys
        
        # Try to find root upon initialization
        self._find_root(Path(start_path).resolve() if start_path else Path.cwd())
        
        if self.bibox_dir and self.db_path and self.db_path.exists():
            self.load()

    def _find_root(self, current_path: Path):
        """Traverse upwards to find the `.bibox` directory."""
        while True:
            bibox_dir = current_path / '.bibox'
            if bibox_dir.is_dir():
                self.root_dir = current_path
                self.bibox_dir = bibox_dir
                self.db_path = bibox_dir / 'db.json'
                return
            
            parent = current_path.parent
            if parent == current_path:
                # Reached filesystem root
                break
            current_path = parent
            
    def is_initialized(self) -> bool:
        return self.root_dir is not None

    def initialize_workspace(self, target_path: str):
        """Create `.bibox`, `pdfs/`, and `notes/` directories, and an empty db."""
        root = Path(target_path).resolve()
        bibox_dir = root / '.bibox'
        
        if bibox_dir.exists():
            logging.warning(f"Bibox workspace already exists at {root}")
            return
            
        # Create directories
        bibox_dir.mkdir(parents=True, exist_ok=True)
        (root / 'pdfs').mkdir(exist_ok=True)
        
        self.root_dir = root
        self.bibox_dir = bibox_dir
        self.db_path = bibox_dir / 'db.json'
        
        # Generate default .gitignore
        gitignore_path = root / '.gitignore'
        if not gitignore_path.exists():
            with open(gitignore_path, 'w', encoding='utf-8') as f:
                f.write("# Bibox generated gitignore\n")
                f.write(".bibox/staging\n")
                f.write("# Uncomment the line below to ignore all downloaded PDFs\n")
                f.write("# pdfs/\n")

        # Save empty database
        self.save()
        logging.info(f"Initialized empty Bibox repository in {root}")

    def load(self):
        """Load papers and stars from db.json."""
        if not self.db_path or not self.db_path.exists():
            return
            
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            papers_data = data.get('papers', {})
            self.papers = {k: Paper.from_dict(v) for k, v in papers_data.items()}
            self.stars = data.get('stars', {})
        except Exception as e:
            logging.error(f"Failed to load database from {self.db_path}: {e}")

    def save(self):
        """Save papers and stars to db.json deterministically for Git compatibility."""
        if not self.db_path:
            raise ValueError("Database path is not set. Cannot save.")
            
        # Ensure stars have sorted unique cite_keys to prevent duplicates and keep diff clean
        for star_name in self.stars:
            self.stars[star_name] = sorted(list(set(self.stars[star_name])))
            
        data = {
            "papers": {k: v.to_dict() for k, v in self.papers.items()},
            "stars": self.stars
        }
        
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)
        except Exception as e:
            logging.error(f"Failed to save database to {self.db_path}: {e}")

    def add_paper(self, paper: Paper):
        """Add a paper to the database and save."""
        self.papers[paper.cite_key] = paper
        self.save()

    def get_paper(self, cite_key: str) -> Optional[Paper]:
        return self.papers.get(cite_key)
        
    def add_to_star(self, star_name: str, cite_key: str):
        import re
        if not re.match(r'^[\w-]+$', star_name):
            raise ValueError("Star name must be ASCII and contain no spaces (e.g. 'my-list').")
        if star_name not in self.stars:
            self.stars[star_name] = []
        if cite_key not in self.stars[star_name]:
            self.stars[star_name].append(cite_key)
            self.save()

    def get_stars_for_paper(self, cite_key: str) -> List[str]:
        """Return a list of star collection names that contain this paper."""
        matched_stars = []
        for star_name, items in self.stars.items():
            if cite_key in items:
                matched_stars.append(star_name)
        return matched_stars
        
    def _evaluate_expression(self, expr: str, match_func) -> bool:
        """
        Evaluate a boolean expression like 'vaswani | (devlin & !hinton)'.
        Supported operators: | (OR), & (AND), ! (NOT), (, )
        """
        import re
        if not expr or not expr.strip():
            return True
            
        tokens = re.split(r'([()|&!])', expr)
        py_expr_parts = []
        for t in tokens:
            t = t.strip()
            if not t:
                continue
            if t == '|':
                py_expr_parts.append(' or ')
            elif t == '&':
                py_expr_parts.append(' and ')
            elif t == '!':
                py_expr_parts.append(' not ')
            elif t == '(':
                py_expr_parts.append('(')
            elif t == ')':
                py_expr_parts.append(')')
            else:
                is_match = match_func(t.lower())
                py_expr_parts.append(str(is_match))
                
        py_expr = "".join(py_expr_parts)
        if not py_expr.strip():
            return True
            
        try:
            return eval(py_expr)
        except Exception as e:
            logging.error(f"Malformed expression '{expr}': {e}")
            return False

    def search_papers(self, query: Optional[str] = None, **kwargs) -> List[Paper]:
        """
        Enhanced search system. Supports global fuzzy search and specific field targeting
        with full recursive boolean logic (!, &, |, ()).
        kwargs can include: tag, star, author, year, title
        """
        # If query is purely whitespace, ignore it
        if query is not None and not query.strip():
            query = None
            
        results = []
        for paper in self.papers.values():
            match = True
            
            # 1. Filter by tags
            if kwargs.get('tag') and kwargs['tag'].strip():
                tag_match = lambda t: t in paper.tags
                if not self._evaluate_expression(kwargs['tag'], tag_match):
                    continue
                    
            # 2. Filter by stars
            if kwargs.get('star') and kwargs['star'].strip():
                star_match = lambda s: paper.cite_key in self.stars.get(s, [])
                if not self._evaluate_expression(kwargs['star'], star_match):
                    continue
                    
            # 3. Filter by specific fields
            def make_field_matcher(field_name):
                def matcher(t):
                    if field_name == 'title' and t in paper.title.lower():
                        return True
                    for v_state in paper.versions.values():
                        if t in str(v_state.info.fields.get(field_name, '')).lower():
                            return True
                    return False
                return matcher
                
            for field_name in ['author', 'year', 'title']:
                if kwargs.get(field_name) and kwargs[field_name].strip():
                    if not self._evaluate_expression(kwargs[field_name], make_field_matcher(field_name)):
                        match = False
                        break
                        
            if not match:
                continue

            # 3. Global fuzzy search
            if query:
                def global_matcher(t):
                    if t in paper.title.lower() or t in paper.cite_key.lower():
                        return True
                    for v_state in paper.versions.values():
                        if any(t in str(val).lower() for val in v_state.info.fields.values()):
                            return True
                    return False
                    
                if not self._evaluate_expression(query, global_matcher):
                    continue
                    
            results.append(paper)
            
        return results

    # --- Staging System (Search Results Context) ---
    
    @property
    def staging_file(self) -> Path:
        if not self.bibox_dir:
            raise ValueError("Workspace not initialized.")
        return self.bibox_dir / 'staging.json'

    def read_staging(self) -> dict:
        if not self.staging_file.exists():
            return {"results": {}, "online_data": {}}
        try:
            with open(self.staging_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "results" not in data:
                    data["results"] = {}
                if "online_data" not in data:
                    data["online_data"] = {}
                return data
        except Exception:
            return {"results": {}, "online_data": {}}

    def save_staging(self, cite_keys: List[str], append: bool = False, online_infos: Optional[Dict[str, 'Info']] = None):
        """
        Save or append search results to the staging area.
        online_infos is a dict of temporary_cite_key -> Info object.
        """
        data = self.read_staging()
        
        if not append:
            data["results"] = {}
            # We don't clear online_data completely immediately, just in case, but it's safe to clear if not appending
            data["online_data"] = {}
            start_index = 1
        else:
            existing_indices = [int(k) for k in data["results"].keys() if k.isdigit()]
            start_index = max(existing_indices) + 1 if existing_indices else 1
            
        existing_values = set(data["results"].values())
            
        for key in cite_keys:
            if key in existing_values:
                continue
            data["results"][str(start_index)] = key
            existing_values.add(key)
            start_index += 1
            
        if online_infos:
            for temp_key, info_obj in online_infos.items():
                data["online_data"][temp_key] = info_obj.to_dict()
                
        with open(self.staging_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def clear_staging(self):
        with open(self.staging_file, "w", encoding="utf-8") as f:
            json.dump({"results": {}, "online_data": {}}, f, indent=2)

    def materialize_online_paper(self, temp_key: str) -> str:
        """Converts an online staging item into a real local Paper object and returns its real cite_key."""
        from .info_getter import Info
        from .paper import Paper
        
        data = self.read_staging()
        online_info_dict = data["online_data"].get(temp_key)
        if not online_info_dict:
            raise ValueError(f"Online data for {temp_key} not found or expired.")
            
        info_obj = Info.from_dict(online_info_dict)
        from .info_getter import ApiGetter
        v_name = ApiGetter()._determine_version_name(info_obj)
        
        temp_paper = Paper.from_info(v_name, info_obj)
        real_cite_key = temp_paper.cite_key
        
        existing_paper = self.get_paper(real_cite_key)
        if existing_paper:
            logging.info(f"Online item already exists locally as {real_cite_key}. Merging info.")
            existing_paper.add_version(v_name, info_obj)
            self.add_paper(existing_paper)
        else:
            logging.info(f"Importing online item to local DB as {real_cite_key}.")
            self.add_paper(temp_paper)
            
        # Update staging map so the index now points to the real key
        for idx, k in data["results"].items():
            if k == temp_key:
                data["results"][idx] = real_cite_key
        with open(self.staging_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        return real_cite_key

    def resolve_targets(self, targets: List[str], allow_online: bool = False) -> List[str]:
        """
        Resolve a list of target strings.
        Supports specific cite_keys, :index, :all, and :db.
        If allow_online is False, raises an error if an online item is targeted.
        """
        data = self.read_staging()
        results_map = data.get("results", {})
        
        resolved_keys = set()
        
        for target in targets:
            if target == ':db':
                resolved_keys.update(self.papers.keys())
            elif target == ':all':
                if not results_map:
                    logging.warning("Staging area is empty. :all matched nothing.")
                    continue
                for index, key in results_map.items():
                    if key.startswith('__ONLINE__') and not allow_online:
                        raise ValueError(f"Target :{index} is an online paper. Run 'bibox import :{index}' first.")
                    resolved_keys.add(key)
            elif target.startswith(':'):
                index = target[1:]
                if index not in results_map:
                    raise ValueError(f"Index :{index} not found in staging.")
                key = results_map[index]
                if key.startswith('__ONLINE__') and not allow_online:
                    raise ValueError(f"Target :{index} is an online paper. Run 'bibox import {target}' first.")
                resolved_keys.add(key)
            else:
                # Treat as literal cite_key
                if target.startswith('__ONLINE__') and not allow_online:
                    raise ValueError(f"Target {target} is an online paper. Run 'bibox import {target}' first.")
                resolved_keys.add(target)
                
        return list(resolved_keys)

    @staticmethod
    def get_file_hash(p: Path) -> str:
        import hashlib
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    def find_paper_by_pdf_hash(self, file_hash: str) -> Optional[Tuple[Paper, str]]:
        """
        Returns (Paper, version_name) if a paper in the library already holds this PDF hash.
        """
        for paper in self.papers.values():
            for v_name, v_state in paper.versions.items():
                if getattr(v_state, 'pdf_hash', None) == file_hash:
                    return paper, v_name
        return None
        
    def find_pdf_file_by_hash(self, target_hash: str) -> Optional[str]:
        """
        Scans the 'pdfs' directory to find a file matching the hash. 
        Returns its relative path as string, or None.
        """
        if not self.root_dir:
            return None
        pdfs_dir = self.root_dir / 'pdfs'
        if not pdfs_dir.exists():
            return None
            
        for path in pdfs_dir.rglob('*.pdf'):
            if path.is_file():
                if self.get_file_hash(path) == target_hash:
                    return path.relative_to(self.root_dir).as_posix()
        return None

    def import_pdf_file(self, source_path: str, paper: Paper, version_name: str, pdf_self_claim: Optional[str] = None) -> bool:
        """
        Copy a PDF into the centralized pdfs directory, rename it, 
        link it to the paper, and save.
        Resolves conflicts by hashing.
        """
        if not self.root_dir:
            raise ValueError("Workspace not initialized.")
            
        src = Path(source_path)
        if not src.exists() or not src.is_file():
            logging.error(f"Source PDF does not exist: {source_path}")
            return False
            
        src_hash = self.get_file_hash(src)

        # Check for existing version and handle conflict
        final_v_name = version_name
        if final_v_name in paper.versions and paper.versions[final_v_name].pdf_path:
            existing_pdf_abs = self.root_dir / paper.versions[final_v_name].pdf_path
            if existing_pdf_abs.exists():
                exist_hash = self.get_file_hash(existing_pdf_abs)
                if src_hash == exist_hash:
                    logging.info(f"PDF identical to existing {final_v_name} version. Ignoring.")
                    # Still update the hash in DB if it was missing
                    if not getattr(paper.versions[final_v_name], 'pdf_hash', None):
                        paper.versions[final_v_name].pdf_hash = src_hash
                        self.save()
                    return True
                else:
                    if pdf_self_claim and pdf_self_claim == final_v_name:
                        # Evict existing PDF because the new one explicitly claims this slot
                        suffix = 2
                        while f"{final_v_name}_{suffix}" in paper.versions:
                            suffix += 1
                        evicted_v_name = f"{final_v_name}_{suffix}"
                        
                        from .paper import VersionState
                        evicted_state = VersionState(
                            info=paper.versions[final_v_name].info,
                            pdf_path=paper.versions[final_v_name].pdf_path,
                            pdf_hash=getattr(paper.versions[final_v_name], 'pdf_hash', exist_hash)
                        )
                        paper.versions[evicted_v_name] = evicted_state
                        paper.versions[final_v_name].pdf_path = None
                        paper.versions[final_v_name].pdf_hash = None
                        
                        # Rename old file on disk to make room
                        old_target_filename = f"{paper.cite_key}_{evicted_v_name}.pdf"
                        old_target_rel_path = Path("pdfs") / old_target_filename
                        existing_pdf_abs.rename(self.root_dir / old_target_rel_path)
                        paper.versions[evicted_v_name].pdf_path = str(old_target_rel_path)
                        
                        logging.info(f"Evicted existing PDF to {evicted_v_name} as new PDF claims {final_v_name}")
                        # final_v_name remains unchanged for the new PDF to take
                    else:
                        # Different content, append suffix
                        suffix = 2
                        while f"{version_name}_{suffix}" in paper.versions:
                            suffix += 1
                        final_v_name = f"{version_name}_{suffix}"
                        logging.info(f"Conflict found. Saving as new version: {final_v_name}")
                        # We duplicate the info from the original version for the new version
                        import copy
                        paper.add_version(final_v_name, copy.deepcopy(paper.versions[version_name].info))

        # Target path: pdfs/{cite_key}_{version}.pdf
        target_filename = f"{paper.cite_key}_{final_v_name}.pdf"
        target_rel_path = Path("pdfs") / target_filename
        target_abs_path = self.root_dir / target_rel_path
        
        try:
            shutil.copy2(src, target_abs_path)
            # Link using relative path!
            paper.link_file(final_v_name, 'pdf', target_rel_path.as_posix(), file_hash=src_hash)
            self.add_paper(paper) # Will trigger save()
            return True
        except Exception as e:
            logging.error(f"Failed to import PDF {source_path}: {e}")
            return False

    def rename_paper_key(self, paper: Paper, new_key: str):
        """
        Cascade updates a cite_key across the database, stars, and physical PDF files.
        Also updates the internal cite_key within the Paper and its Info objects.
        """
        import os
        old_key = paper.cite_key
        if old_key not in self.papers:
            return
            
        # 1. Update stars
        stars_to_update = self.get_stars_for_paper(old_key)
        for star in stars_to_update:
            idx = self.stars[star].index(old_key)
            self.stars[star][idx] = new_key
            
        # 2. Update physical PDF files and internal paths
        if self.root_dir:
            for v_name, v_state in paper.versions.items():
                if v_state.pdf_path:
                    old_pdf_abs = self.root_dir / v_state.pdf_path
                    if old_pdf_abs.exists():
                        new_target_filename = f"{new_key}_{v_name}.pdf"
                        new_target_rel = Path("pdfs") / new_target_filename
                        new_pdf_abs = self.root_dir / new_target_rel
                        old_pdf_abs.rename(new_pdf_abs)
                        v_state.pdf_path = str(new_target_rel)
                        
                # Update Info cite_key
                v_state.info.cite_key = new_key
                
        # 3. Update dictionary key
        del self.papers[old_key]
        self.papers[new_key] = paper
        
    def remove_paper(self, cite_key: str, keep_pdf: bool = False):
        """
        Permanently remove a paper from the database.
        Also removes it from all stars, and deletes its physical PDFs unless keep_pdf=True.
        """
        import os
        if cite_key not in self.papers:
            return

        paper = self.papers[cite_key]

        # 1. Clean up from stars
        stars_to_update = self.get_stars_for_paper(cite_key)
        for star in stars_to_update:
            self.stars[star].remove(cite_key)
            if not self.stars[star]:
                del self.stars[star]

        # 2. Delete physical PDFs if requested
        if not keep_pdf and self.root_dir:
            for v_state in paper.versions.values():
                if v_state.pdf_path:
                    pdf_abs_path = self.root_dir / v_state.pdf_path
                    if pdf_abs_path.exists():
                        try:
                            os.remove(pdf_abs_path)
                            logging.info(f"Deleted physical PDF: {pdf_abs_path}")
                        except Exception as e:
                            logging.error(f"Failed to delete PDF {pdf_abs_path}: {e}")

        # 3. Remove from database
        del self.papers[cite_key]
        self.save()
