import io
import os
import sys
import unittest
from contextlib import redirect_stdout

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

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


if __name__ == "__main__":
    unittest.main()
