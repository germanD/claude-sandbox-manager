import os
import sys
import tempfile
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

import capture  # noqa: E402
import common   # noqa: E402


class TestScopePaths(unittest.TestCase):
    def setUp(self):
        self._home = os.path.expanduser("~")
        self._claude_home = os.path.join(self._home, ".claude")

    def _global_triple(self):
        return (common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH)

    def test_none_cwd_returns_global(self):
        self.assertEqual(common.scope_paths(None), self._global_triple())

    def test_empty_string_returns_global(self):
        self.assertEqual(common.scope_paths(""), self._global_triple())

    def test_home_dir_is_global(self):
        self.assertEqual(common.scope_paths(self._home), self._global_triple())

    def test_claude_home_is_global(self):
        self.assertEqual(common.scope_paths(self._claude_home), self._global_triple())

    def test_project_cwd_returns_scoped(self):
        project = "/home/user/code/myrepo"
        data_dir, failures, archive = common.scope_paths(project)
        slug = os.path.normpath(os.path.abspath(project)).replace(os.sep, "-")
        expected_data = os.path.join(common.DATA_DIR, "projects", slug)
        self.assertEqual(data_dir, expected_data)
        self.assertEqual(failures, os.path.join(expected_data, "failures.jsonl"))
        self.assertEqual(archive, os.path.join(expected_data, "failures.archive.jsonl"))

    def test_scoped_paths_differ_from_global(self):
        data_dir, failures, archive = common.scope_paths("/some/project")
        self.assertNotEqual(failures, common.FAILURES_PATH)
        self.assertNotEqual(archive, common.ARCHIVE_PATH)

    def test_different_projects_get_different_paths(self):
        _, f1, _ = common.scope_paths("/home/user/repo-a")
        _, f2, _ = common.scope_paths("/home/user/repo-b")
        self.assertNotEqual(f1, f2)

    def test_same_project_same_paths(self):
        self.assertEqual(common.scope_paths("/some/project"),
                         common.scope_paths("/some/project"))

    def test_trailing_slash_normalised(self):
        self.assertEqual(common.scope_paths("/some/project"),
                         common.scope_paths("/some/project/"))


class TestEnsureDataDir(unittest.TestCase):
    def test_explicit_path_is_created(self):
        with tempfile.TemporaryDirectory() as base:
            target = os.path.join(base, "nested", "dir")
            self.assertFalse(os.path.exists(target))
            result = common.ensure_data_dir(target)
            self.assertTrue(os.path.isdir(target))
            self.assertEqual(result, target)

    def test_no_arg_creates_data_dir(self):
        # DATA_DIR already exists on a dev machine; just check idempotency.
        result = common.ensure_data_dir()
        self.assertEqual(result, common.DATA_DIR)
        self.assertTrue(os.path.isdir(common.DATA_DIR))

    def test_slug_used_by_scope_paths(self):
        project = "/home/user/code/myrepo"
        cwd_abs = os.path.normpath(os.path.abspath(project))
        self.assertEqual(common._slug(cwd_abs), cwd_abs.replace(os.sep, "-"))


class TestScopedAppendIntegration(unittest.TestCase):
    """Integration tests: scoped paths work end-to-end with capture.append_records.

    These tests pass explicit failures_path/archive_path in a temp dir so they
    are isolated from the global DATA_DIR and work in read-only CI environments.
    This mirrors the real scoped usage: scope_paths() computes paths, then
    append_records/archive_stale receive them as kwargs.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._failures = os.path.join(self._tmp, "failures.jsonl")
        self._archive = os.path.join(self._tmp, "failures.archive.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_record(self, session_id, tool_use_id):
        return {
            "ts": "2024-01-01T00:00:00Z",
            "session_id": session_id,
            "tool_use_id": tool_use_id,
            "project": "test-project",
            "cwd": self._tmp,
            "tool": "Bash",
            "kind": "runtime_failure",
            "signature": f"Bash:test error:{tool_use_id}",
            "command": "ls /nonexistent",
            "snippet": "No such file or directory",
        }

    def test_append_records_writes_to_scoped_path(self):
        """Records written to explicit scoped path end up there and are readable."""
        import json
        record = self._make_record("sess-integration-001", "tu-integration-001")

        added = capture.append_records(
            [record],
            failures_path=self._failures,
            archive_path=self._archive,
        )
        self.assertEqual(added, 1)
        self.assertTrue(os.path.exists(self._failures))

        # Read back and verify content
        with open(self._failures, "r", encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh if l.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["session_id"], "sess-integration-001")

    def test_dedup_across_active_and_archive(self):
        """P5: append_records never re-adds a record already in the archive."""
        import json
        record = self._make_record("sess-dedup-002", "tu-dedup-002")

        # First write — goes to active log
        added = capture.append_records(
            [record],
            failures_path=self._failures,
            archive_path=self._archive,
        )
        self.assertEqual(added, 1)

        # Manually move it to the archive (simulating archive_stale)
        with open(self._archive, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        os.remove(self._failures)

        # Second write — should be deduped against the archive (P5)
        added2 = capture.append_records(
            [record],
            failures_path=self._failures,
            archive_path=self._archive,
        )
        self.assertEqual(added2, 0,
                         "record was re-added despite already existing in archive")


if __name__ == "__main__":
    unittest.main()
