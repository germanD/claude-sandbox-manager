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


class TestDetectSignatureSplit(unittest.TestCase):
    def test_no_split_returns_false(self):
        recs = [rec(signature="Bash:(no error detail)"), rec(signature="Bash:(no error detail)")]
        self.assertFalse(doctor._detect_signature_split(recs))

    def test_old_and_new_exit_code_format_returns_true(self):
        recs = [
            rec(tool="Bash", kind="runtime_failure", signature="Bash:Exit code 1"),
            rec(tool="Bash", kind="runtime_failure", signature="Bash:(no error detail)"),
        ]
        self.assertTrue(doctor._detect_signature_split(recs))

    def test_old_and_new_unknown_prefix_returns_true(self):
        # Old orphaned records have tool="" (pre-#19 fallback was ("", "")).
        # New orphaned records have tool="(unknown)". They are in different
        # (kind, tool) groups, so the orphan check must group by kind only.
        recs = [
            rec(tool="", kind="runtime_failure", signature=":some error"),
            rec(tool="(unknown)", kind="runtime_failure", signature="(unknown):some error"),
        ]
        self.assertTrue(doctor._detect_signature_split(recs))

    def test_different_tools_do_not_cross_trigger(self):
        recs = [
            rec(tool="Bash", kind="runtime_failure", signature="Bash:Exit code 1"),
            rec(tool="Edit", kind="runtime_failure", signature="Edit:(no error detail)"),
        ]
        self.assertFalse(doctor._detect_signature_split(recs))

    def test_empty_records_returns_false(self):
        self.assertFalse(doctor._detect_signature_split([]))


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



class TestDoctorMain(unittest.TestCase):
    """Integration tests for doctor.main() CLI argument paths."""

    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.fp = os.path.join(self._d, "failures.jsonl")
        self.ap = os.path.join(self._d, "failures.archive.jsonl")
        self.lrp = os.path.join(self._d, "last_reported.json")

        self._orig_fp = common.FAILURES_PATH
        self._orig_ap = common.ARCHIVE_PATH
        self._orig_lrp = common.LAST_REPORTED_PATH
        self._orig_dd = common.DATA_DIR

        common.FAILURES_PATH = self.fp
        common.ARCHIVE_PATH = self.ap
        common.LAST_REPORTED_PATH = self.lrp
        common.DATA_DIR = self._d

    def tearDown(self):
        common.FAILURES_PATH = self._orig_fp
        common.ARCHIVE_PATH = self._orig_ap
        common.LAST_REPORTED_PATH = self._orig_lrp
        common.DATA_DIR = self._orig_dd

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = doctor.main(argv)
        return rc, buf.getvalue()

    def _write_log(self, records, path=None):
        target = path if path is not None else self.fp
        with open(target, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    # ------------------------------------------------------------------
    # Test 1: --banner delegates and returns 0
    # ------------------------------------------------------------------
    def test_banner_returns_0(self):
        self._write_log([rec(ts="2026-08-04T10:00:00.000Z")])
        rc, out = self._run(["--banner"])
        self.assertEqual(rc, 0)
        self.assertIn("sandbox-audit", out)

    # ------------------------------------------------------------------
    # Test 2: no-log message when failures file is absent (using --global)
    # ------------------------------------------------------------------
    def test_no_log_message_when_file_absent(self):
        # fp is already a non-existent path (setUp did not create it)
        self.assertFalse(os.path.exists(self.fp))
        rc, out = self._run(["--global"])
        self.assertEqual(rc, 0)
        self.assertIn("no log", out)

    # ------------------------------------------------------------------
    # Test 3: report from log (--global)
    # ------------------------------------------------------------------
    def test_report_from_log(self):
        self._write_log([
            rec(signature="sig-A", session_id="s1"),
            rec(signature="sig-A", session_id="s2"),
        ])
        rc, out = self._run(["--global"])
        self.assertEqual(rc, 0)
        self.assertIn("2 failure(s)", out)
        self.assertIn("1 cluster(s)", out)

    # ------------------------------------------------------------------
    # Test 4: --top limits output and shows "hidden" message
    # ------------------------------------------------------------------
    def test_top_limits_output(self):
        self._write_log([
            rec(signature="sig-X", session_id="s1"),
            rec(signature="sig-Y", session_id="s2"),
            rec(signature="sig-Z", session_id="s3"),
        ])
        rc, out = self._run(["--global", "--top", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("hidden", out)

    # ------------------------------------------------------------------
    # Test 5: --verbose prints "Sources reviewed"
    # ------------------------------------------------------------------
    def test_verbose_prints_sources(self):
        self._write_log([rec(signature="sig-V", session_id="s1")])
        rc, out = self._run(["--global", "--verbose"])
        self.assertEqual(rc, 0)
        self.assertIn("Sources reviewed", out)

    # ------------------------------------------------------------------
    # Test 6: --include-archive reads both active log and archive
    # ------------------------------------------------------------------
    def test_include_archive_reads_both_files(self):
        self._write_log([rec(signature="sig-active", session_id="s1", tool_use_id="t1")])
        self._write_log(
            [rec(signature="sig-archive", session_id="s2", tool_use_id="t2")],
            path=self.ap,
        )
        rc, out = self._run(["--global", "--include-archive"])
        self.assertEqual(rc, 0)
        # 2 records total across 2 distinct clusters
        self.assertIn("2 failure(s)", out)

    # ------------------------------------------------------------------
    # Test 7: --archive flag moves stale records and returns 0
    # ------------------------------------------------------------------
    def test_archive_flag_moves_stale_records(self):
        # Write a record with a timestamp 10 days in the past
        stale_ts = "2020-01-01T00:00:00Z"  # permanently ancient; always outside any retention window
        self._write_log([rec(ts=stale_ts, signature="sig-stale", session_id="s1")])
        rc, out = self._run(["--global", "--archive", "--retention-days", "7"])
        self.assertEqual(rc, 0)
        self.assertIn("archived 1", out)
        # Archive file must exist and contain the moved record
        self.assertTrue(os.path.exists(self.ap))
        with open(self.ap, encoding="utf-8") as fh:
            lines = [ln for ln in fh if ln.strip()]
        self.assertEqual(len(lines), 1)

    # ------------------------------------------------------------------
    # Test 8: advisory note appears when old/new signature formats coexist
    # ------------------------------------------------------------------
    def test_signature_split_advisory_is_printed(self):
        self._write_log([
            rec(tool="Bash", kind="runtime_failure",
                signature="Bash:Exit code 1", session_id="s1", tool_use_id="t1"),
            rec(tool="Bash", kind="runtime_failure",
                signature="Bash:(no error detail)", session_id="s2", tool_use_id="t2"),
        ])
        rc, out = self._run(["--global"])
        self.assertEqual(rc, 0)
        self.assertIn("signature format upgrade", out)
        self.assertIn("PR #19", out)

    def test_no_advisory_when_no_split(self):
        self._write_log([
            rec(tool="Bash", kind="runtime_failure",
                signature="Bash:(no error detail)", session_id="s1", tool_use_id="t1"),
        ])
        rc, out = self._run(["--global"])
        self.assertEqual(rc, 0)
        self.assertNotIn("signature format upgrade", out)

    # ------------------------------------------------------------------
    # Test 9: --scan-history with a real fixture
    # ------------------------------------------------------------------
    def test_scan_history_with_fixture(self):
        import shutil
        projects_dir = os.path.join(self._d, "claude-projects")
        slug_dir = os.path.join(projects_dir, "fake-proj")
        os.makedirs(slug_dir, exist_ok=True)

        fixture_src = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "fixtures", "seccomp_failure.jsonl",
        )
        shutil.copy(fixture_src, os.path.join(slug_dir, "session-abc.jsonl"))

        orig_pd = common.PROJECTS_DIR
        common.PROJECTS_DIR = projects_dir
        try:
            rc, out = self._run(["--global", "--scan-history"])
        finally:
            common.PROJECTS_DIR = orig_pd

        self.assertEqual(rc, 0)
        self.assertIn("failure(s)", out)

if __name__ == "__main__":
    unittest.main()
