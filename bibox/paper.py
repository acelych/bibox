import re
import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Set, Optional, Any

from .info_getter import Info, normalize_title

@dataclass
class VersionState:
    info: 'Info'
    pdf_path: Optional[str] = None
    pdf_hash: Optional[str] = None
    
    @property
    def has_pdf(self) -> bool:
        return self.pdf_path is not None
        
    def to_dict(self) -> dict:
        return {
            'info': self.info.to_dict(),
            'pdf_path': self.pdf_path,
            'pdf_hash': self.pdf_hash
        }
        
    @classmethod
    def from_dict(cls, data: dict) -> 'VersionState':
        return cls(
            info=Info.from_dict(data.get('info', {})),
            pdf_path=data.get('pdf_path'),
            pdf_hash=data.get('pdf_hash')
        )


class Paper:
    
    STOP_WORDS = {'a', 'an', 'the', 'in', 'on', 'of', 'and', 'to', 'with', 'for', 'by', 'at', 'is', 'are'}

    def __init__(self, title: str, author: Optional[str] = None):
        self.title: str = title.strip()
        self.cite_key: str = self._generate_cite_key(author)
        
        self.versions: Dict[str, VersionState] = {}
        
        self.tags: Set[str] = set()
        self.comment: str = ""
        
    @classmethod
    def from_info(cls, version_name: str, info_obj: 'Info', keep_cite_key: bool = False):
        assert info_obj.fields.get('title') is not None, "Require title at least."
        
        author = info_obj.fields.get('author')
        instance = cls(info_obj.fields.get('title'), author)
        
        if keep_cite_key and info_obj.cite_key:
            instance.cite_key = info_obj.cite_key
        instance.add_version(version_name, info_obj, keep_cite_key)
        return instance

    def _generate_cite_key(self, author_str: Optional[str], title_override: Optional[str] = None) -> str:
        # 1. Process Title (First non-stop word)
        target_title = title_override if title_override else self.title
        clean_title = re.sub(r'[^\w\s-]', '', target_title.lower())
        words = clean_title.split()
        key_words = [w.capitalize() for w in words if w not in self.STOP_WORDS]
        
        first_title_word = key_words[0] if key_words else "Unknown"
        
        # 2. Process Author (First Author's Last Name)
        author_part = ""
        if author_str:
            first_author = author_str.split(' and ')[0].strip()
            if ',' in first_author:
                last_name = first_author.split(',')[0].strip()
            else:
                last_name = first_author.split()[-1].strip()
            
            clean_last_name = re.sub(r'[^\w-]', '', last_name).capitalize()
            if clean_last_name:
                author_part = f"{clean_last_name}_"
                
        # 3. Hash (using deeply normalized title to prevent brace drifting)
        norm_title = normalize_title(target_title)
        title_hash = hashlib.md5(norm_title.encode('utf-8')).hexdigest()[:4]
        
        return f"{author_part}{first_title_word}_{title_hash}"

    def add_version(self, version_name: str, info_obj: 'Info', keep_cite_key: bool = False) -> None:
        if not keep_cite_key:
            info_obj.cite_key = self.cite_key
        version_name = version_name.lower()
        if version_name not in self.versions:
            self.versions[version_name] = VersionState(info=info_obj)
        else:
            self.versions[version_name].info = info_obj
            logging.info(f"[{self.cite_key}] Updated info for version '{version_name}'.")

    def link_file(self, version_name: str, file_type: str, path: str, file_hash: Optional[str] = None) -> None:
        version_name = version_name.lower()
        if version_name not in self.versions:
            logging.error(f"[{self.cite_key}] Version '{version_name}' does not exist. Add info first.")
            return

        if file_type == 'pdf':
            self.versions[version_name].pdf_path = path
            if file_hash:
                self.versions[version_name].pdf_hash = file_hash
        else:
            logging.warning(f"[{self.cite_key}] Unsupported file type '{file_type}' for version. Use 'pdf'.")

    def add_tags(self, *tags: str) -> None:
        for tag in tags:
            self.tags.add(tag.lower().strip())

    def status_report(self) -> dict:
        report = {
            "title": self.title,
            "cite_key": self.cite_key,
            "tags": list(self.tags),
            "has_comment": bool(self.comment),
            "versions": {}
        }
        for v_name, state in self.versions.items():
            report["versions"][v_name] = {
                "has_pdf": state.has_pdf,
                "bib_type": getattr(state.info, 'type', 'unknown')
            }
        return report

    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'cite_key': self.cite_key,
            'tags': sorted(list(self.tags)),
            'comment': self.comment,
            'versions': {k: v.to_dict() for k, v in self.versions.items()}
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Paper':
        p = cls(data.get('title', 'Untitled'))
        p.cite_key = data.get('cite_key', p.cite_key)
        p.tags = set(data.get('tags', []))
        p.comment = data.get('comment', "")
        
        versions_data = data.get('versions', {})
        for v_name, v_data in versions_data.items():
            p.versions[v_name] = VersionState.from_dict(v_data)
            
        return p
