import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

import common  # noqa: E402
import doctor  # noqa: E402


def rec(**kw):
    base = {
        "ts": "2026-06-01T00:00:00Z", "session_id": "s", "tool_use_id": "t",
        "project": "p", "cwd": "/c", "tool": "Bash", "kind": "runtime_failure",
        "signature": "sig", "command": "", "snippet": "",
    }
    base.update(kw)
    return base


class TestCluster(unittest.TestCase):
    def test_counts_and_ranking(self):
        recs = [
            rec(signature="A", session_id="s1"),
            rec(signature="A", session_id="s2"),
            rec(signature="B", session_id="s1"),
        ]
        clusters = doctor.cluster(recs)
        self.assertEqual(clusters[0]["signature"], "A")
        self.assertEqual(clusters[0]["count"], 2)
        self.assertEqual(len(clusters[0]["sessions"]), 2)


class TestSuggest(unittest.TestCase):
    def test_seccomp_suggestion_is_the_verified_fix(self):
        c = doctor.cluster([rec(
            signature="Bash:apply-seccomp: write /proc/self/setgroups",
            snippet="apply-seccomp: write /proc/self/setgroups",
        )])[0]
        s = " ".join(doctor.suggest(c)).lower()
        self.assertIn("apparmor_restrict_unprivileged_userns", s)
        self.assertIn("bwrap-userns-restrict", s)
        self.assertIn("#43454", s)
        self.assertIn("#24238", s)  # applyPath override is ignored
        self.assertNotIn("applypath override — and verify", s)  # old wrong advice gone

    def test_over_broad_deny_on_readonly_command(self):
        c = doctor.cluster([rec(
            kind="permission_denied", tool="Bash",
            signature="permission_denied:Bash:ls [denied-args]",
            command="ls [denied-args]",
        )])[0]
        s = " ".join(doctor.suggest(c)).lower()
        self.assertIn("read-only", s)
        self.assertIn("too broad", s)

    def test_generic_permission_denied_suggestion(self):
        c = doctor.cluster([rec(
            kind="permission_denied", tool="Bash",
            signature="permission_denied:Bash:curl [denied-args]",
            command="curl https://x",
        )])[0]
        s = " ".join(doctor.suggest(c)).lower()
        self.assertIn("allow", s)


class TestSources(unittest.TestCase):
    def test_sources_from_log_groups_by_project_session(self):
        recs = [
            rec(project="p1", session_id="s1"),
            rec(project="p1", session_id="s1"),
            rec(project="p2", session_id="s2"),
        ]
        srcs = doctor._sources_from_log(recs)
        self.assertEqual(len(srcs), 2)
        total = {(s["project"], s["session"]): s["failures"] for s in srcs}
        self.assertEqual(total[("p1", "s1")], 2)

    def test_print_sources_does_not_leak_redacted(self):
        scanned = [{"project": "[redacted]", "session": "abc.jsonl", "failures": 3}]
        buf = io.StringIO()
        with redirect_stdout(buf):
            doctor.print_sources(scanned)
        out = buf.getvalue()
        self.assertIn("[redacted]", out)
        self.assertIn("abc.jsonl", out)


class TestBanner(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.mkdtemp()
        self._orig_fp = common.FAILURES_PATH
        self._orig_lrp = common.LAST_REPORTED_PATH
        common.FAILURES_PATH = os.path.join(self._d, "failures.jsonl")
        common.LAST_REPORTED_PATH = os.path.join(self._d, "last_reported.json")

    def tearDown(self):
        common.FAILURES_PATH = self._orig_fp
        common.LAST_REPORTED_PATH = self._orig_lrp

    def _write_log(self, records):
        with open(common.FAILURES_PATH, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def _write_last_reported(self, ts):
        with open(common.LAST_REPORTED_PATH, "w", encoding="utf-8") as fh:
            json.dump({"ts": ts}, fh)

    def _banner(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = doctor.banner_check()
        return result, buf.getvalue()

    def test_no_log_is_silent(self):
        result, out = self._banner()
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_empty_log_is_silent(self):
        self._write_log([])
        result, out = self._banner()
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_new_failures_show_banner(self):
        self._write_log([rec(ts="2026-08-04T10:00:00.000Z")])
        result, out = self._banner()
        self.assertTrue(result)
        self.assertIn("sandbox-audit", out)
        self.assertIn("/sandbox-audit:doctor", out)

    def test_old_failures_are_silent(self):
        self._write_log([rec(ts="2026-08-01T10:00:00.000Z")])
        self._write_last_reported("2026-08-02T00:00:00.000Z")
        result, out = self._banner()
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_banner_updates_last_reported_so_next_call_is_silent(self):
        self._write_log([rec(ts="2026-08-04T10:00:00.000Z")])
        self._banner()  # first call prints
        result, out = self._banner()  # second call should be silent
        self.assertFalse(result)
        self.assertEqual(out, "")

    def test_no_last_reported_triggers_banner(self):
        self._write_log([rec(ts="2026-08-04T10:00:00.000Z")])
        self.assertFalse(os.path.exists(common.LAST_REPORTED_PATH))
        result, _ = self._banner()
        self.assertTrue(result)

    def test_banner_mentions_cluster_count(self):
        self._write_log([
            rec(ts="2026-08-04T10:00:00.000Z", signature="A"),
            rec(ts="2026-08-04T11:00:00.000Z", signature="B"),
        ])
        _, out = self._banner()
        self.assertIn("2 cluster(s)", out)


if __name__ == "__main__":
    unittest.main()
