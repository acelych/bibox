import os
import sys
import tempfile
import unittest
import subprocess
import shutil
import json
from pathlib import Path

# Note: Ensure the 'bibox' package is installed in the current environment
# (e.g. `pip install -e .`) before running this test.

class BiboxE2ETests(unittest.TestCase):
    def setUp(self):
        """Create a temporary sandbox directory for each test."""
        self.test_dir = tempfile.mkdtemp(prefix="bibox_test_")
        self.original_cwd = os.getcwd()
        os.chdir(self.test_dir)
        
        # Initialize an empty repository
        self.run_cmd(["bibox", "init", "."])

    def tearDown(self):
        """Clean up the sandbox after the test completes."""
        os.chdir(self.original_cwd)
        if os.environ.get('BIBOX_KEEP_SANDBOX') == '1':
            print(f"\n[Debug] Sandbox preserved at: {self.test_dir}")
        else:
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def run_cmd(self, cmd_list, check=True):
        """Helper to run a CLI command and return its stdout."""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        result = subprocess.run(
            cmd_list, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            encoding="utf-8",
            env=env,
            cwd=self.test_dir
        )
        if check and result.returncode != 0:
            self.fail(f"Command '{' '.join(cmd_list)}' failed with code {result.returncode}.\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
        return result

    def test_01_initialization(self):
        """[Test 01] Verify workspace initialization and required folders creation."""
        self.assertTrue(os.path.isdir(".bibox"))
        self.assertTrue(os.path.isdir("pdfs"))
        self.assertTrue(os.path.isfile(".bibox/db.json"))
        self.assertTrue(os.path.isfile(".gitignore"))
        
        res = self.run_cmd(["bibox", "status"])
        self.assertIn("Total Papers  0", res.stdout)

    def test_02_manual_db_injection_and_boolean_search(self):
        """[Test 02] Verify the recursive boolean logic search engine (!, &, |)."""
        # Inject fake data directly into db.json
        fake_db = {
            "papers": {
                "Paper_A": {
                    "cite_key": "Paper_A",
                    "title": "Deep Learning for Vision",
                    "tags": ["deep-learning", "vision"],
                    "comment": "",
                    "versions": {
                        "published": {
                            "info": {"type": "article", "cite_key": "Paper_A", "fields": {"author": "LeCun", "year": "2015"}},
                            "pdf_path": None
                        }
                    }
                },
                "Paper_B": {
                    "cite_key": "Paper_B",
                    "title": "Natural Language Processing with Transformers",
                    "tags": ["nlp", "transformer", "deep-learning"],
                    "comment": "",
                    "versions": {
                        "arxiv": {
                            "info": {"type": "article", "cite_key": "Paper_B", "fields": {"author": "Vaswani", "year": "2017"}},
                            "pdf_path": None
                        }
                    }
                },
                "Paper_C": {
                    "cite_key": "Paper_C",
                    "title": "Audio Recognition",
                    "tags": ["audio"],
                    "comment": "",
                    "versions": {
                        "published": {
                            "info": {"type": "article", "cite_key": "Paper_C", "fields": {"author": "Hinton", "year": "2020"}},
                            "pdf_path": None
                        }
                    }
                }
            },
            "stars": {}
        }
        with open(".bibox/db.json", "w", encoding="utf-8") as f:
            json.dump(fake_db, f)

        res = self.run_cmd(["bibox", "search", "vision"])
        self.assertIn("Paper_A", res.stdout)
        self.assertNotIn("Paper_B", res.stdout)

        res = self.run_cmd(["bibox", "search", "--tag", "deep-learning & !vision"])
        self.assertIn("Paper_B", res.stdout)
        self.assertNotIn("Paper_A", res.stdout)
        self.assertNotIn("Paper_C", res.stdout)

        res = self.run_cmd(["bibox", "search", "(transformer | audio) & !language"])
        self.assertIn("Paper_C", res.stdout)
        self.assertNotIn("Paper_B", res.stdout)

    def test_03_export_no_arxiv_filter(self):
        """[Test 03] Verify export command strictly filters out arxiv versions (--no-arxiv)."""
        fake_db = {
            "papers": {
                "OnlyArxiv": {
                    "cite_key": "OnlyArxiv", "title": "A", "tags": [], "comment": "",
                    "versions": {
                        "arxiv": {"info": {"type": "article", "cite_key": "A", "fields": {"title": "A"}}, "pdf_path": None}
                    }
                },
                "Mixed": {
                    "cite_key": "Mixed", "title": "B", "tags": [], "comment": "",
                    "versions": {
                        "arxiv": {"info": {"type": "article", "cite_key": "B", "fields": {"title": "B"}}, "pdf_path": None},
                        "published": {"info": {"type": "article", "cite_key": "B", "fields": {"title": "B"}}, "pdf_path": None}
                    }
                }
            },
            "stars": {}
        }
        with open(".bibox/db.json", "w", encoding="utf-8") as f:
            json.dump(fake_db, f)

        res_all = self.run_cmd(["bibox", "export", ":db"])
        self.assertIn("OnlyArxiv", res_all.stdout)
        self.assertIn("Mixed", res_all.stdout)

        res_strict = self.run_cmd(["bibox", "export", ":db", "--no-arxiv"], check=False)
        self.assertNotIn("OnlyArxiv", res_strict.stdout)
        self.assertIn("Mixed", res_strict.stdout)

    def test_04_bibtex_import_and_keep_keys(self):
        """[Test 04] Verify BibTeX import preserves original cite_keys when -k is used."""
        bib_content = """
        @article{MyCustomKey2023,
          title={Testing BibTeX Import},
          author={Doe, John},
          year={2023}
        }
        """
        with open("test.bib", "w", encoding="utf-8") as f:
            f.write(bib_content)

        self.run_cmd(["bibox", "import", "test.bib", "-k"])
        
        with open(".bibox/db.json", "r", encoding="utf-8") as f:
            db = json.load(f)
            
        self.assertIn("MyCustomKey2023", db["papers"])
        self.assertEqual(db["papers"]["MyCustomKey2023"]["title"], "Testing BibTeX Import")

    def test_05_pdf_hash_conflict_resolution(self):
        """[Test 05] Verify PDF hash collisions are ignored and different PDFs append suffix."""
        with open("dummy1.pdf", "wb") as f:
            f.write(b"%PDF-1.4\nTest 1")
            
        # Create a dummy PDF 2 (different content)
        with open("dummy2.pdf", "wb") as f:
            f.write(b"%PDF-1.4\nTest 2")

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        # Create a Python script to test the DB logic directly
        script = f"""
import sys
import os
sys.path.append(r"{project_root}")
from bibox.db import BiboxDB
from bibox.paper import Paper
from bibox.info_getter import Info

db = BiboxDB(".")
info = Info("article", "test", {{"title": "Test Paper"}})
p = Paper.from_info("published", info)
db.add_paper(p)

# Import PDF 1
success1 = db.import_pdf_file("dummy1.pdf", p, "published")
print(f"Import 1: {{success1}}")

# Import PDF 1 AGAIN (Same hash)
success2 = db.import_pdf_file("dummy1.pdf", p, "published")
print(f"Import 2: {{success2}}")

# Import PDF 2 (Different hash, same version target)
success3 = db.import_pdf_file("dummy2.pdf", p, "published")
print(f"Import 3: {{success3}}")
"""
        with open("run_db_test.py", "w", encoding="utf-8") as f:
            f.write(script)
            
        res = subprocess.run([sys.executable, "run_db_test.py"], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            self.fail(f"run_db_test.py failed: {res.stderr}")
        
        files_in_pdfs = os.listdir("pdfs")
        self.assertEqual(len(files_in_pdfs), 2)
        
        has_suffix = any("_published_2.pdf" in f for f in files_in_pdfs)
        self.assertTrue(has_suffix, "The different PDF should have been saved with a version suffix to prevent overwriting.")

    def test_06_online_explicit_materialization_protection(self):
        """[Test 06] Verify [Online] staging items block modifications until imported."""
        staging_data = {
            "results": {
                "1": "__ONLINE__fake_published"
            },
            "online_data": {
                "__ONLINE__fake_published": {
                    "type": "article",
                    "cite_key": "fake",
                    "fields": {"title": "Online Fake Paper"}
                }
            }
        }
        with open(".bibox/staging.json", "w", encoding="utf-8") as f:
            json.dump(staging_data, f)
            
        res = self.run_cmd(["bibox", "tag", "add", ":1", "test"], check=False)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("online paper", res.stdout.lower() + res.stderr.lower())
        
        res_import = self.run_cmd(["bibox", "import", ":1"])
        self.assertEqual(res_import.returncode, 0)
        
        res_tag = self.run_cmd(["bibox", "tag", "add", ":1", "test"])
        self.assertEqual(res_tag.returncode, 0)

    def test_07_hash_short_circuit(self):
        """[Test 07] Verify duplicate PDFs are short-circuited by Hash."""
        script = f"""
import sys
import os
import json
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.db import BiboxDB
from bibox.info_getter import Info
from bibox.paper import Paper

db = BiboxDB(".")
info = Info("article", "test", {{"title": "Test Paper"}})
p = Paper.from_info("published", info)
with open("circuit1.pdf", "wb") as f:
    f.write(b"%PDF-1.4\\nShort Circuit Test")
db.import_pdf_file("circuit1.pdf", p, "published")
db.save()
"""
        with open("setup_db.py", "w") as f:
            f.write(script)
        subprocess.run([sys.executable, "setup_db.py"], check=True, cwd=self.test_dir)
        
        pdf2 = "circuit2.pdf"
        with open(os.path.join(self.test_dir, pdf2), "wb") as f:
            f.write(b"%PDF-1.4\nShort Circuit Test")
            
        res = self.run_cmd(["bibox", "import", pdf2])
        self.assertIn("Skipped", res.stdout)

    def test_08_bibox_update_self_healing(self):
        """[Test 08] Verify update command self-heals renamed PDF files."""
        script = f"""
import sys
import os
import json
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.db import BiboxDB
from bibox.info_getter import Info
from bibox.paper import Paper

db = BiboxDB(".")
info = Info("article", "test", {{"title": "Test Paper"}})
p = Paper.from_info("published", info)
with open("heal.pdf", "wb") as f:
    f.write(b"%PDF-1.4\\nHeal Test")
db.import_pdf_file("heal.pdf", p, "published")
db.save()
"""
        with open("setup_db2.py", "w") as f:
            f.write(script)
        subprocess.run([sys.executable, "setup_db2.py"], check=True, cwd=self.test_dir)
        
        with open(os.path.join(self.test_dir, ".bibox/db.json"), "r", encoding="utf-8") as f:
            db = json.load(f)
            
        papers = list(db["papers"].values())
        self.assertTrue(len(papers) > 0)
        p = papers[-1]
        cite_key = p["cite_key"]
        
        pdf_rel_path = list(p["versions"].values())[0]["pdf_path"]
        old_pdf_path = os.path.join(self.test_dir, pdf_rel_path)
        new_pdf_path = os.path.join(self.test_dir, "pdfs", "renamed_heal.pdf")
        os.rename(old_pdf_path, new_pdf_path)
        
        script2 = f"""
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from unittest.mock import patch
import bibox.cli

def mock_fetch(self, q): return {{}}
bibox.cli.ApiGetter.fetch = mock_fetch
sys.argv = ["bibox", "update", "{cite_key}"]
bibox.cli.main()
"""
        with open("test_heal.py", "w") as f:
            f.write(script2)
            
        res = subprocess.run([sys.executable, "test_heal.py"], capture_output=True, text=True, encoding="utf-8", cwd=self.test_dir)
        self.assertIn("Relinked", res.stdout)
        
        with open(os.path.join(self.test_dir, ".bibox/db.json"), "r", encoding="utf-8") as f:
            db = json.load(f)
        
        found_relinked = False
        for v in db["papers"][cite_key]["versions"].values():
            if v["pdf_path"] == "pdfs/renamed_heal.pdf":
                found_relinked = True
        self.assertTrue(found_relinked, "PDF path was not updated in database")

    def test_09_bibtex_citekey_preservation(self):
        """[Test 09] Verify BibTeX keep_keys forces synchronization on new updates."""
        script = f"""
import sys
import os
import json
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.db import BiboxDB
from bibox.info_getter import Info
from bibox.paper import Paper

db = BiboxDB(".")
info = Info("article", "CustomKey999", {{"title": "Deep learning", "author": "Smith"}})
p = Paper.from_info("imported_bib", info, keep_cite_key=True)
db.add_paper(p)
"""
        with open("setup_bib.py", "w") as f:
            f.write(script)
        subprocess.run([sys.executable, "setup_bib.py"], check=True, cwd=self.test_dir)
        
        script2 = f"""
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.info_getter import Info
import bibox.cli
def mock_fetch(self, q):
    return {{"arxiv": Info("article", "WrongKeyFromAPI", {{"title": "Deep learning", "author": "S."}})}}
bibox.cli.ApiGetter.fetch = mock_fetch
sys.argv = ["bibox", "update", "CustomKey999"]
bibox.cli.main()
"""
        with open("test_key.py", "w") as f:
            f.write(script2)
        subprocess.run([sys.executable, "test_key.py"], check=True, cwd=self.test_dir)
        
        with open(".bibox/db.json", "r", encoding="utf-8") as f:
            db = json.load(f)
            
        self.assertIn("CustomKey999", db["papers"])
        versions = db["papers"]["CustomKey999"]["versions"]
        self.assertIn("arxiv", versions)
        self.assertEqual(versions["arxiv"]["info"]["cite_key"], "CustomKey999")

    def test_10_update_keys_flag(self):
        """[Test 10] Verify --update-keys recalculates cite keys and cascades changes."""
        script = f"""
import sys
import os
import json
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.db import BiboxDB
from bibox.info_getter import Info
from bibox.paper import Paper

db = BiboxDB(".")
info = Info("article", "BadKey", {{"title": "Zebra", "author": "Smith"}})
p = Paper.from_info("arxiv", info, keep_cite_key=True)

with open("test_key.pdf", "wb") as f:
    f.write(b"%PDF-1.4\\nTest")
db.import_pdf_file("test_key.pdf", p, "arxiv")
db.add_to_star("test_star", p.cite_key)
db.save()
"""
        with open("setup_update_keys.py", "w") as f:
            f.write(script)
        subprocess.run([sys.executable, "setup_update_keys.py"], check=True, cwd=self.test_dir)
        
        script2 = f"""
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)
from bibox.info_getter import Info
import bibox.cli

def mock_fetch(self, q):
    return {{"cvpr": Info("article", "SomeAPIKey", {{"title": "Apple", "author": "Smith"}})}}
bibox.cli.ApiGetter.fetch = mock_fetch
sys.argv = ["bibox", "update", "--update-keys", "BadKey"]
bibox.cli.main()
"""
        with open("test_update_keys.py", "w") as f:
            f.write(script2)
        res = self.run_cmd(["python3", "test_update_keys.py"])
        
        self.assertIn("CiteKey Regenerated", res.stdout)
        
        with open(os.path.join(self.test_dir, ".bibox/db.json"), "r", encoding="utf-8") as f:
            db = json.load(f)
            
        self.assertNotIn("BadKey", db["papers"])
        
        # Determine expected key (Apple is lexicographically first)
        # Author: Smith, Title: Apple -> Smith_Apple_xxxx
        new_key = list(db["papers"].keys())[-1]
        self.assertTrue(new_key.startswith("Smith_Apple_"))
        
        # Verify cascades
        self.assertIn(new_key, db["stars"]["test_star"])
        self.assertEqual(db["papers"][new_key]["versions"]["arxiv"]["info"]["cite_key"], new_key)
        self.assertEqual(db["papers"][new_key]["versions"]["cvpr"]["info"]["cite_key"], new_key)
        self.assertEqual(db["papers"][new_key]["versions"]["arxiv"]["pdf_path"], f"pdfs/{new_key}_arxiv.pdf")

class HumanReadableTestResult(unittest.TextTestResult):
    def getDescription(self, test):
        # Override to only return the docstring, falling back to method name if missing
        doc = test.shortDescription()
        return doc if doc else str(test)

class HumanReadableTestRunner(unittest.TextTestRunner):
    resultclass = HumanReadableTestResult

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Run Bibox E2E Tests")
    parser.add_argument('--keep-sandbox', action='store_true', help="Do not delete the temp sandbox after running")
    args, unknown = parser.parse_known_args()
    
    if args.keep_sandbox:
        os.environ['BIBOX_KEEP_SANDBOX'] = '1'
        
    # Run tests using the custom runner to ensure clean, human-readable output
    suite = unittest.TestLoader().loadTestsFromTestCase(BiboxE2ETests)
    HumanReadableTestRunner(verbosity=2).run(suite)
