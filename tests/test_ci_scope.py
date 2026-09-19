import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("ci_scope", Path(__file__).parents[1] / "scripts/ci_scope.py")
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class ChangeScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "user.name", "Test")
        self.write("README.md", "base")
        self.write("main.tf", "base")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "fixture")

    def check(self, expected):
        self.commit()
        for kind, event in [("push", {"before": self.base}),
                            ("pull_request", {"pull_request": {"base": {"sha": self.base}}})]:
            self.assertEqual(scope.needs_tests(self.root, kind, event), expected)

    def test_nested_markdown_only(self):
        self.write("docs/nested/guide.md", "guide")
        self.write("README.md", "updated")
        self.check(False)

    def test_mixed_change(self):
        self.write("README.md", "updated")
        self.write("main.tf", "changed")
        self.check(True)

    def test_executable_example_under_docs(self):
        self.write("docs/example.yaml", "data")
        self.check(True)

    def test_renaming_code_to_markdown(self):
        (self.root / "main.tf").rename(self.root / "main.md")
        self.check(True)

    def test_deleted_markdown(self):
        (self.root / "README.md").unlink()
        self.check(False)

    def test_workflow_change(self):
        self.write(".github/workflows/ci.yml", "workflow")
        self.check(True)

    def test_unknown_range_and_manual_run(self):
        for kind, event in [("push", {"before": "0" * 40}), ("push", {"before": "a" * 40}),
                            ("push", {"before": self.base}), ("workflow_dispatch", {}),
                            ("pull_request", {})]:
            self.assertTrue(scope.needs_tests(self.root, kind, event))


if __name__ == "__main__":
    unittest.main()
