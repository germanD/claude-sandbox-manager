import os
import sys
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

import common  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
