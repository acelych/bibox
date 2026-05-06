import re
import logging
from typing import Optional, Dict, Any
import fitz  # PyMuPDF

from .info_getter import Info, ApiGetter

class PdfExtractor:
    def __init__(self):
        self.api = ApiGetter()
        
        # Match DOI format, e.g. 10.1145/3317550.3321441
        self.doi_pattern = re.compile(r'(10.\d{4,9}/[-._;()/:a-zA-Z0-9]+)')
        # Match arXiv format, e.g. 1706.03762 or arXiv:1706.03762v1
        self.arxiv_pattern = re.compile(r'(?i)arxiv:?\s*(\d{4}\.\d{4,5}(?:v\d+)?)')

    def get_self_claim_v_name(self, pdf_path: str) -> Optional[str]:
        try:
            doc = fitz.open(pdf_path)
            text = doc[0].get_text()[:1000] if len(doc) > 0 else ""
            metadata = doc.metadata or {}
            combined = f"{metadata.get('creator', '')} {metadata.get('producer', '')} {metadata.get('subject', '')} {text}".lower()
            
            venue_mapping = {
                "iclr": "iclr", "international conference on learning representations": "iclr",
                "icml": "icml", "international conference on machine learning": "icml",
                "neurips": "neurips", "nips": "neurips", "neural information processing systems": "neurips",
                "cvpr": "cvpr", "computer vision and pattern recognition": "cvpr",
                "iccv": "iccv", "international conference on computer vision": "iccv",
                "eccv": "eccv", "european conference on computer vision": "eccv",
                "acl": "acl", "association for computational linguistics": "acl",
                "emnlp": "emnlp", "empirical methods in natural language processing": "emnlp",
                "naacl": "naacl", "north american chapter of the association for computational linguistics": "naacl",
                "aaai": "aaai", "association for the advancement of artificial intelligence": "aaai",
                "ijcai": "ijcai", "international joint conference on artificial intelligence": "ijcai",
                "kdd": "kdd", "knowledge discovery and data mining": "kdd",
                "sigir": "sigir", "special interest group on information retrieval": "sigir",
                "www": "www", "world wide web conference": "www",
                "chi": "chi", "conference on human factors in computing systems": "chi",
                "jmlr": "jmlr", "journal of machine learning research": "jmlr",
                "tpami": "tpami", "pattern analysis and machine intelligence": "tpami",
                "ijcv": "ijcv", "international journal of computer vision": "ijcv",
                "tog": "tog", "transactions on graphics": "tog",
                "siggraph": "siggraph",
                "icra": "icra", "international conference on robotics and automation": "icra",
                "iros": "iros", "intelligent robots and systems": "iros",
                "nature": "nature",
                "science": "science",
                "cell": "cell",
                "pnas": "pnas",
            }
            
            # Sort by length descending to match longest, most specific strings first
            sorted_venue_mapping = dict(sorted(venue_mapping.items(), key=lambda item: len(item[0]), reverse=True))
            
            for key, short_name in sorted_venue_mapping.items():
                if re.search(r'\b' + re.escape(key) + r'\b', combined):
                    return short_name
        except Exception:
            pass
        return None

    def extract_info(self, pdf_path: str) -> Optional[Dict[str, Info]]:
        """
        Main entry point for extracting Info from a PDF.
        Implements the 4-Tier fallback strategy.
        Returns a dictionary of versions (e.g. {'arxiv': Info, 'published': Info})
        """
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            logging.error(f"Failed to open PDF {pdf_path}: {e}")
            return None

        text_pages = []
        # We only look at the first two pages for identifiers and layout
        for i in range(min(2, len(doc))):
            text_pages.append(doc[i].get_text())

        # Tier 1: Explicit Identifiers (DOI / arXiv ID)
        versions = self._tier1_identifiers(text_pages)
        if versions:
            return versions

        # Tier 2: PDF Native Metadata
        versions = self._tier2_metadata(doc)
        if versions:
            return versions

        # Tier 3: Layout Heuristics (Largest text block on page 1)
        if len(doc) > 0:
            versions = self._tier3_heuristics(doc[0])
            if versions:
                return versions

        return None

    def _tier1_identifiers(self, text_pages: list[str]) -> Optional[Dict[str, Info]]:
        full_text = " ".join(text_pages)
        
        # Check arXiv
        arxiv_match = self.arxiv_pattern.search(full_text)
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)
            logging.info(f"Tier 1: Found arXiv ID: {arxiv_id}")
            versions = self.api.fetch(arxiv_id)
            if versions:
                return versions

        # Check DOI
        doi_match = self.doi_pattern.search(full_text)
        if doi_match:
            doi = doi_match.group(1)
            # Make sure it's a valid DOI format and not some trailing garbage
            doi = doi.rstrip('.,;)') 
            logging.info(f"Tier 1: Found DOI: {doi}")
            versions = self.api.fetch(doi)
            if versions:
                return versions

        return None

    def _tier2_metadata(self, doc: fitz.Document) -> Optional[Dict[str, Info]]:
        metadata = doc.metadata
        if not metadata:
            return None
            
        title = metadata.get('title', '').strip()
        if not title:
            return None
            
        # Basic validation: filter out junk like "Microsoft Word - xxx" or "Untitled"
        if len(title) < 5 or title.lower() in ['untitled', 'document']:
            return None
        if "microsoft word" in title.lower():
            return None
            
        logging.info(f"Tier 2: Found Metadata Title: {title}")
        versions = self.api.fetch(title)
        if versions:
            return versions
            
        return None

    def _tier3_heuristics(self, first_page: fitz.Page) -> Optional[Dict[str, Info]]:
        # Extract blocks as dictionaries to get font sizes
        blocks = first_page.get_text("dict")["blocks"]
        if not blocks:
            return None
            
        max_size = 0.0
        best_text = ""
        
        for b in blocks:
            if b['type'] != 0: # 0 means text block
                continue
            for l in b["lines"]:
                for s in l["spans"]:
                    text = s["text"].strip()
                    if not text:
                        continue
                        
                    # Filtering: Ignore margins/watermarks that contain 'arxiv', dates, or copyright
                    text_lower = text.lower()
                    if "arxiv" in text_lower or "@" in text_lower or "©" in text_lower or "copyright" in text_lower:
                        continue
                        
                    # Ignore blocks that are ridiculously short or suspiciously long
                    if len(text) < 10 or len(text) > 200:
                        continue
                        
                    # Check if it looks like a typical date string (e.g. 1 Dec 2023)
                    import re
                    if re.match(r'^[\d]{1,2}\s+[a-zA-Z]{3}\s+[\d]{4}$', text):
                        continue
                        
                    size = s["size"]
                    
                    # If we find a significantly larger font, it's the new primary title
                    if size > max_size + 2.0:
                        max_size = size
                        best_text = text
                    # If the font is within 3.0 pts of the max size, treat it as a subtitle or continuing title line
                    elif abs(size - max_size) < 3.0:
                        best_text += " " + text
                        
        best_text = best_text.strip()
        # Clean up multiple spaces that might result from concatenating spans
        best_text = re.sub(r'\s+', ' ', best_text)
        
        if not best_text or len(best_text) < 10:
            return None
            
        logging.info(f"Tier 3: Guessed Title from layout: {best_text}")
        versions = self.api.fetch(best_text)
        if versions:
            return versions
            
        return None