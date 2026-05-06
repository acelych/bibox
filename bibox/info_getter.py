import re
import urllib.parse
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Optional, Any

def normalize_title(text: str) -> str:
    """
    Lowercases, removes all non-alphanumeric characters (keeps spaces), 
    and collapses spaces. Used for robust similarity checking and hashing.
    """
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

class Info:
    REQUIRED_FIELDS: dict = {
        'article': ['author', 'title', 'journal', 'year'],
        'inproceedings': ['author', 'title', 'booktitle', 'year'],
        'book': [('author', 'editor'), 'title', 'publisher', 'year'],
        'incollection': ['author', 'title', 'booktitle', 'publisher', 'year'],
        'inbook': [('author', 'editor'), 'title', ('chapter', 'pages'), 'publisher', 'year'],
        'phdthesis': ['author', 'title', 'school', 'year'],
        'mastersthesis': ['author', 'title', 'school', 'year'],
        'techreport': ['author', 'title', 'institution', 'year'],
        'manual': ['title'],
        'booklet': ['title'],
        'proceedings': ['title', 'year'],
        'conference': ['author', 'title', 'booktitle', 'year'],
        'unpublished': ['author', 'title', 'note'],
        'misc': []
    }
    
    FIELDS: list = [
        'author', 'title', 'year', 'journal', 'booktitle', 'volume',
        'number', 'pages', 'month', 'publisher', 'address', 'series',
        'edition', 'editor', 'school', 'institution', 'organization',
        'doi', 'url', 'eprint', 'archivePrefix', 'chapter',
        'howpublished', 'type', 'note', 'annote', 'key',
    ]

    def __init__(self, i_type: str, i_cite: str, i_fields: dict):
        i_type = i_type.lower()
        if i_type not in self.REQUIRED_FIELDS:
            self.type = 'misc'
            logging.debug(f"Unexpected bibtex type '{i_type}', use 'misc' instead.")
        else:
            self.type = i_type
            
        self.cite_key = i_cite
        
        self.fields = {
            k: str(v).strip() 
            for k, v in i_fields.items() 
            if k in self.FIELDS and v is not None
        }
        
        self.is_valid = self.validate_fields()

    def validate_fields(self) -> bool:
        required = self.REQUIRED_FIELDS.get(self.type, [])
        missing = []

        for req in required:
            if isinstance(req, tuple):
                if not any(self.fields.get(f) for f in req):
                    missing.append(f"({'/'.join(req)})")
            else:
                val = self.fields.get(req)
                if not val:
                    missing.append(req)

        if missing:
            logging.debug(f"[{self.cite_key}] Missing required fields for '{self.type}': {', '.join(missing)}")
            return False
        return True
        
    @classmethod
    def from_bibtex(cls, bib: str):
        """Parse a single BibTeX entry using a robust state machine."""
        import re
        bib = bib.strip()
        if not bib:
            return None
            
        # Find the first @ and the type
        header_match = re.search(r'@(\w+)\s*\{\s*([^,]+),', bib)
        if not header_match:
            logging.debug("Could not parse BibTeX header.")
            return None
            
        i_type = header_match.group(1).strip().lower()
        i_tag = header_match.group(2).strip()
        
        i_fields = {}
        
        # Start looking for fields after the header
        idx = header_match.end()
        key_pattern = re.compile(r'(\w+)\s*=\s*')
        
        while idx < len(bib):
            match = key_pattern.search(bib, idx)
            if not match:
                break
                
            key = match.group(1).lower()
            start_idx = match.end()
            
            # Find the starting character of the value
            while start_idx < len(bib) and bib[start_idx].isspace():
                start_idx += 1
                
            if start_idx >= len(bib):
                break
                
            char = bib[start_idx]
            value = ""
            
            if char == '{':
                # Brace-counting state machine
                brace_count = 1
                curr = start_idx + 1
                while curr < len(bib) and brace_count > 0:
                    if bib[curr] == '{': 
                        brace_count += 1
                    elif bib[curr] == '}': 
                        brace_count -= 1
                    curr += 1
                value = bib[start_idx+1:curr-1]
                idx = curr
                
            elif char == '"':
                curr = start_idx + 1
                while curr < len(bib) and bib[curr] != '"':
                    curr += 1
                value = bib[start_idx+1:curr]
                idx = curr + 1
                
            else:
                # Unquoted/unbraced value (like a year)
                curr = start_idx
                while curr < len(bib) and bib[curr] not in (',', '}'):
                    curr += 1
                value = bib[start_idx:curr].strip()
                idx = curr
                
            # Clean up the value
            clean_value = re.sub(r'\s+', ' ', value).strip()
            # If the entire value is wrapped in braces due to LaTeX parsing (e.g., {{BCN:} Batch Channel}), 
            # we should unwrap the outermost layer if it perfectly encapsulates it, but only if it was extracted that way.
            if clean_value.startswith('{') and clean_value.endswith('}'):
                # Check if stripping outer braces keeps balanced inner braces
                inner = clean_value[1:-1]
                b_count = 0
                balanced = True
                for c in inner:
                    if c == '{': b_count += 1
                    elif c == '}': b_count -= 1
                    if b_count < 0:
                        balanced = False
                        break
                if balanced and b_count == 0:
                    clean_value = inner.strip()
                    
            i_fields[key] = clean_value
            
        return cls(i_type, i_tag, i_fields)
    
    @classmethod
    def from_bibtexes(cls, bibs: str) -> list:
        """Parse multiple BibTeX entries."""
        import re
        
        # Split by @, but only when it's at the start of a line or after whitespace
        # to avoid splitting on emails or internal @ symbols.
        # A simpler way is to find all instances of @Type{...
        blocks = re.findall(r'(@\w+\s*\{.*?(?=\n\s*@\w+\s*\{|$))', bibs, re.DOTALL)
        
        if not blocks:
            # Fallback split
            raw_blocks = bibs.split('@')
            blocks = []
            for b in raw_blocks:
                b = b.strip()
                if b and '{' in b:
                    blocks.append('@' + b)

        results = []
        for block in blocks:
            obj = cls.from_bibtex(block)
            if obj:
                results.append(obj)
                
        return results

    def to_bibtex(self) -> str:
        bib = f"@{self.type}{{{self.cite_key},\n"
        for k, v in self.fields.items():
            bib += f"  {k:12} = {{{v}}},\n"
        bib += "}"
        return bib

    def to_dict(self) -> dict:
        return {
            'type': self.type,
            'cite_key': self.cite_key,
            'fields': self.fields
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            i_type=data.get('type', 'misc'),
            i_cite=data.get('cite_key', ''),
            i_fields=data.get('fields', {})
        )
    

class ApiGetter:
    def __init__(self, email: str = "your_email@example.com"):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        self.headers = {
            'User-Agent': f'PaperFetcherBot/1.0 (mailto:{email})',
            'Accept': 'application/x-bibtex'
        }
        self.session = requests.Session()
        
        # Add basic pool settings (retries are handled by our custom while-loop instead)
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def _is_doi(self, query: str) -> bool:
        """like 10.1145/3317550.3321441"""
        return bool(re.match(r'^10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+$', query))

    def _is_arxiv_id(self, query: str) -> bool:
        """like 1706.03762 or 1706.03762v1"""
        return bool(re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', query))
    
    def _determine_version_name(self, info_obj: 'Info') -> str:
        fields = info_obj.fields
        
        journal = fields.get('journal', '').lower()
        booktitle = fields.get('booktitle', '').lower()
        publisher = fields.get('publisher', '').lower()
        
        # 1. Check for arXiv
        if 'corr' in journal or 'corr' in booktitle or 'arxiv' in journal:
            return 'arxiv'
            
        archive_prefix = fields.get('archiveprefix', '').lower()
        eprint = fields.get('eprint', '').lower()
        if archive_prefix == 'arxiv' or 'arxiv' in eprint:
            return 'arxiv'
            
        howpublished = fields.get('howpublished', '').lower()
        if 'arxiv' in howpublished:
            return 'arxiv'
            
        if info_obj.type == 'unpublished':
            return 'arxiv'
            
        # 2. Smart Venue Extraction for published papers
        raw_venue_mapping = {
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
            "sigcomm": "sigcomm", 
            "jmlr": "jmlr", "journal of machine learning research": "jmlr",
            "tpami": "tpami", "pattern analysis and machine intelligence": "tpami", "tip": "tpami",
            "ijcv": "ijcv", "international journal of computer vision": "ijcv",
            "tog": "tog", "transactions on graphics": "tog",
            "siggraph": "siggraph",
            "icra": "icra", "international conference on robotics and automation": "icra",
            "iros": "iros", "intelligent robots and systems": "iros",
            # Broad journals
            "nature": "nature",
            "science": "science",
            "cell": "cell",
            "pnas": "pnas",
            # Broad publishers at the absolute bottom
            "ieee": "ieee",
            "acm": "acm",
            "springer": "springer",
            "elsevier": "elsevier",
        }
        
        # Sort by length descending to match longest, most specific strings first
        venue_mapping = dict(sorted(raw_venue_mapping.items(), key=lambda item: len(item[0]), reverse=True))
        
        combined_venue = f"{booktitle} {journal} {publisher}"
        if not combined_venue.strip():
            return 'published'
            
        # Try finding a known abbreviation/venue first
        for key, short_name in venue_mapping.items():
            # word boundary match to avoid false positives like "macmachine" -> acm
            if re.search(r'\b' + re.escape(key) + r'\b', combined_venue):
                return short_name
                
        # If no known mapping matches, extract the first capitalized word of the strongest field
        for field in [fields.get('booktitle'), fields.get('journal'), fields.get('publisher')]:
            if field:
                # Find first word containing letters
                match = re.search(r'([A-Za-z]+)', field)
                if match:
                    return match.group(1).lower()
                    
        return 'published'

    def fetch(self, query: str) -> Dict[str, 'Info']:
        versions = {}
        query = query.strip()
        
        is_doi = self._is_doi(query)
        is_arxiv = self._is_arxiv_id(query)

        # Baseline Title for fallback searches
        baseline_title = None

        # Strategy 1: CrossRef
        if is_doi:
            cr_info = self._fetch_crossref(query, is_doi=True)
            if cr_info:
                v_name = self._determine_version_name(cr_info)
                versions[v_name] = cr_info
                baseline_title = cr_info.fields.get('title')
        elif not is_arxiv:
            # It's a raw title search
            cr_info = self._fetch_crossref(query, is_doi=False)
            if cr_info:
                v_name = self._determine_version_name(cr_info)
                versions[v_name] = cr_info
                baseline_title = cr_info.fields.get('title')

        # Strategy 2: arXiv
        if is_arxiv:
            arx_info = self._fetch_arxiv(query, is_arxiv_id=True)
            if arx_info:
                versions['arxiv'] = arx_info
                baseline_title = arx_info.fields.get('title')
        elif not is_doi:
            # Raw title search
            arx_info = self._fetch_arxiv(query, is_arxiv_id=False)
            if arx_info:
                versions['arxiv'] = arx_info
                if not baseline_title:
                    baseline_title = arx_info.fields.get('title')

        # Strategy 3: DBLP (Good for both finding preprints and published if title is known)
        search_title = query if not (is_doi or is_arxiv) else baseline_title
        
        if search_title:
            dblp_infos = self._fetch_dblp(search_title, original_full_query=search_title)
            for dblp_info in dblp_infos:
                v_name = self._determine_version_name(dblp_info)
                if v_name not in versions:
                    versions[v_name] = dblp_info

        # The Pre-print Upgrade & "Find All Versions" Loop
        # If we only have an arxiv version (because we searched by arxiv ID), let's try to find the published version
        if len(versions) == 1 and 'arxiv' in versions and baseline_title:
            cr_upgrade = self._fetch_crossref(baseline_title, is_doi=False)
            if cr_upgrade:
                # Title Rescue: Don't let downstream APIs degrade our baseline title
                if not cr_upgrade.fields.get('title') or len(cr_upgrade.fields.get('title', '')) < 10:
                    cr_upgrade.fields['title'] = baseline_title
                v_name = self._determine_version_name(cr_upgrade)
                if v_name not in versions:
                    versions[v_name] = cr_upgrade
                
        # If we don't have arxiv, let's try to find the preprint
        if 'arxiv' not in versions and baseline_title:
            arx_upgrade = self._fetch_arxiv(baseline_title, is_arxiv_id=False)
            if arx_upgrade:
                if not arx_upgrade.fields.get('title') or len(arx_upgrade.fields.get('title', '')) < 10:
                    arx_upgrade.fields['title'] = baseline_title
                if 'arxiv' not in versions:
                    versions['arxiv'] = arx_upgrade

        return versions

    def _check_title_similarity(self, query: str, returned_title: str) -> bool:
        """
        Calculates similarity between the query title and the API returned title.
        Aggressively normalizes strings before comparison.
        Requires both high character sequence ratio (>= 0.90) AND high word Jaccard similarity (>= 0.70)
        to prevent false positives like 'Knowledge Distillation: A Survey' vs 'Knowledge Distillation on Graphs: A Survey'.
        """
        import difflib
        
        norm_query = normalize_title(query)
        norm_returned = normalize_title(returned_title)
        
        if not norm_query or not norm_returned:
            return False
            
        ratio = difflib.SequenceMatcher(None, norm_query, norm_returned).ratio()
        
        q_words = set(norm_query.split())
        t_words = set(norm_returned.split())
        union_len = len(q_words.union(t_words))
        jaccard = len(q_words.intersection(t_words)) / union_len if union_len > 0 else 0
        
        if ratio < 0.90 or jaccard < 0.70:
            logging.debug(f"API result rejected: Low similarity (Ratio: {ratio:.2f}, Jaccard: {jaccard:.2f}) between query '{norm_query}' and result '{norm_returned}'.")
            return False
        return True

    def _fetch_with_retry(self, url: str, is_json: bool = False, max_retries: int = 2) -> Optional[Any]:
        # max_retries is now ignored to support infinite retry, but kept in signature for compatibility
        import requests
        import time
        import random
        
        attempt = 0
        while True:
            try:
                # Add polite jitter to avoid hammering the API
                if attempt > 0:
                    time.sleep(1.5 + random.uniform(0.5, 1.5))
                else:
                    # Base delay for all requests to ensure we stay under strict limits
                    time.sleep(0.5)
                    
                resp = self.session.get(url, headers=self.headers, timeout=(3.0, 10.0))
                if resp.status_code == 200:
                    return resp.json() if is_json else resp.text
                elif resp.status_code == 404:
                    return None
                elif resp.status_code in [429, 503, 504]: # Rate limit or server error
                    logging.debug(f"API Rate limit/Server error (Code {resp.status_code}). Retrying...")
                    attempt += 1
                    continue
                else:
                    return None
            except requests.exceptions.Timeout:
                logging.debug(f"API Timeout on attempt {attempt+1}. Retrying...")
                attempt += 1
            except (requests.exceptions.ConnectionError, requests.exceptions.SSLError) as e:
                # Silently catch DBLP abrupt closure errors and just retry or fail gracefully without a massive stack trace
                logging.debug(f"API Connection/SSL Error: {e}. Retrying...")
                attempt += 1
            except Exception as e:
                logging.error(f"API Request Error: {e}")
                return None

    def _fetch_crossref(self, query: str, is_doi: bool) -> Optional['Info']:
        import urllib.parse
        
        if is_doi:
            url = f"https://doi.org/{query}"
            text = self._fetch_with_retry(url)
            if text:
                return Info.from_bibtex(text)
        else:
            safe_query = urllib.parse.quote(query)
            search_url = f"https://api.crossref.org/works?query.title={safe_query}&rows=1"
            data = self._fetch_with_retry(search_url, is_json=True)
            
            if data:
                items = data.get('message', {}).get('items', [])
                if items:
                    best_match = items[0]
                    returned_title = best_match.get('title', [''])[0]
                    
                    if not is_doi and returned_title:
                        if not self._check_title_similarity(query, returned_title):
                            return None
                            
                    best_match_doi = best_match.get('DOI')
                    if best_match_doi:
                        return self._fetch_crossref(best_match_doi, is_doi=True)
        return None

    def _fetch_dblp(self, query: str, original_full_query: str = "") -> list['Info']:
        import urllib.parse
        import re
        
        # Extract first 5 words to prevent strict DBLP matching from failing on hyphens/minor changes
        words = re.findall(r'\w+', query)
        truncated_query = ' '.join(words[:5]) if len(words) >= 5 else query
        
        safe_query = urllib.parse.quote(truncated_query)
        search_url = f"https://dblp.org/search/publ/api?q={safe_query}&format=json&h=20"
        data = self._fetch_with_retry(search_url, is_json=True)
        
        results = []
        if data:
            hits = data.get('result', {}).get('hits', {}).get('hit', [])
            for match in hits:
                returned_title = match.get('info', {}).get('title', '')
                
                # Check similarity against the full original query (or the provided query)
                compare_query = original_full_query if original_full_query else query
                if returned_title and self._check_title_similarity(compare_query, returned_title):
                    dblp_key = match['info']['key']
                    bib_url = f"https://dblp.org/rec/{dblp_key}.bib"
                    text = self._fetch_with_retry(bib_url)
                    if text:
                        parsed_info = Info.from_bibtex(text)
                        if parsed_info:
                            results.append(parsed_info)
        return results

    def _fetch_arxiv(self, query: str, is_arxiv_id: bool) -> Optional['Info']:
        import urllib.parse
        import xml.etree.ElementTree as ET
        
        if is_arxiv_id:
            search_url = f"http://export.arxiv.org/api/query?id_list={query}"
        else:
            safe_query = urllib.parse.quote(f'ti:"{query}"')
            search_url = f"http://export.arxiv.org/api/query?search_query={safe_query}&max_results=1"

        text = self._fetch_with_retry(search_url)
        if not text:
            return None

        try:
            # parse arXiv Atom XML
            root = ET.fromstring(text)
            # Atom XML namespace
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'arxiv': 'http://arxiv.org/schemas/atom'}
            
            entry = root.find('atom:entry', ns)
            if entry is None:
                return None

            # get fields
            title = entry.find('atom:title', ns).text.replace('\n', ' ').strip()
            
            # If searching by title, validate similarity
            if not is_arxiv_id and title:
                if not self._check_title_similarity(query, title):
                    return None
                    
            authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
            year = entry.find('atom:published', ns).text[:4]
            url_el = entry.find("atom:id", ns).text
            # get eprint id (如 http://arxiv.org/abs/1706.03762v1 -> 1706.03762v1)
            eprint = url_el.split('/')[-1]

            # assemble Info
            fields = {
                'title': title,
                'author': ' and '.join(authors),
                'year': year,
                'journal': 'arXiv preprint',
                'eprint': eprint,
                'archivePrefix': 'arXiv',
                'url': url_el
            }
            
            # 生成一个临时 tag，格式：第一作者姓氏+年份
            first_author_last_name = authors[0].split()[-1]
            temp_tag = f"{first_author_last_name}{year}"

            return Info('article', temp_tag, fields)
            
        except Exception as e:
            logging.error(f"arXiv XML Parsing Error: {e}")
        return None