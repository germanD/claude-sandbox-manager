import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

import capture  # noqa: E402
import common   # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def mine(name):
    return capture.mine_transcript(os.path.join(FIX, name + ".jsonl"))


class TestClassify(unittest.TestCase):
    def test_seccomp_is_runtime_not_permission(self):
        # The seccomp stderr literally says "Permission denied" but it is a
        # runtime failure, not a CC permission gate. (regression guard)
        txt = ("Exit code 1\napply-seccomp: write /proc/self/setgroups (nested "
               "userns is capability-restricted; caller must provide "
               "CAP_SYS_ADMIN): Permission denied")
        self.assertEqual(capture.classify(txt), "runtime_failure")

    def test_user_rejection_is_permission(self):
        self.assertEqual(
            capture.classify("The user doesn't want to proceed with this tool use."),
            "permission_denied",
        )

    def test_deny_rule_is_permission(self):
        self.assertEqual(
            capture.classify("Permission to use Bash with command ls has been denied."),
            "permission_denied",
        )

    def test_generic_error_is_runtime(self):
        self.assertEqual(capture.classify("Exit code 1\nunknown flag: --state"),
                         "runtime_failure")


class TestNoise(unittest.TestCase):
    def test_cancelled_parallel_is_noise(self):
        self.assertTrue(capture.is_noise("Cancelled: parallel tool call Bash(x) errored"))

    def test_user_interrupt_is_noise(self):
        self.assertTrue(capture.is_noise("[Request interrupted by user]"))

    def test_real_error_is_not_noise(self):
        self.assertFalse(capture.is_noise("Exit code 1\nsegfault"))


class TestSignature(unittest.TestCase):
    def test_canon_normalizes_variable_bits(self):
        c = capture._canon("failed at line 42 addr 0xFF id "
                           "12345678-1234-1234-1234-123456789012")
        self.assertNotIn("42", c)
        self.assertIn("line N", c)
        self.assertIn("<uuid>", c)
        self.assertIn("0xN", c)

    def test_salient_line_skips_exit_code(self):
        self.assertEqual(capture._salient_line("Exit code 1\nreal message"),
                         "real message")

    def test_salient_line_fallback_when_only_exit_code(self):
        self.assertEqual(capture._salient_line("Exit code 127"), "(no error detail)")

    def test_signature_for_exit_code_only_error(self):
        self.assertEqual(
            capture.signature("runtime_failure", "Bash", "", "Exit code 127"),
            "Bash:(no error detail)",
        )


class TestMine(unittest.TestCase):
    def test_seccomp(self):
        recs = mine("seccomp_failure")
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["kind"], "runtime_failure")
        self.assertEqual(r["tool"], "Bash")
        self.assertTrue(r["signature"].startswith("Bash:apply-seccomp"))
        self.assertIn("apply-seccomp", r["snippet"])

    def test_user_rejection(self):
        recs = mine("user_rejection")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "permission_denied")

    def test_deny_readonly(self):
        recs = mine("deny_readonly")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "permission_denied")
        self.assertTrue(recs[0]["command"].startswith("ls"))

    def test_noise_filtered_out(self):
        self.assertEqual(mine("noise_cancelled"), [])

    def test_secret_command_redacted(self):
        recs = mine("secret_command")
        self.assertEqual(len(recs), 1)
        self.assertNotIn("sk-abcdef1234567890abcdef", recs[0]["command"])

    def test_privmisc_masked_not_dropped_and_no_leak(self):
        recs = mine("privmisc_denylisted")
        self.assertEqual(len(recs), 1, "denylisted record should be masked, not dropped")
        r = recs[0]
        self.assertEqual(r["command"], "cat [denied-args]")
        self.assertEqual(r["cwd"], "[redacted]")
        self.assertEqual(r["project"], "[redacted]")
        self.assertNotIn("priv-misc", __import__("json").dumps(r))

    def test_mixed_only_error_results(self):
        recs = mine("mixed_results")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["tool"], "Edit")

    def test_toolresult_string_does_not_crash(self):
        recs = mine("toolresult_string")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["kind"], "runtime_failure")


    def test_orphaned_tool_use_id_fallback(self):
        # A tool_result whose tool_use_id has no matching tool_use block should
        # produce a record with tool == "(unknown)" and a signature starting
        # with "(unknown):", not crash or silently drop the failure.
        recs = mine("orphaned_tool_use_id")
        self.assertEqual(len(recs), 1, "orphaned tool_use_id must yield exactly one record")
        r = recs[0]
        self.assertEqual(r["tool"], "(unknown)")
        self.assertTrue(
            r["signature"].startswith("(unknown):"),
            "expected signature starts with (unknown):, got " + r["signature"],
        )


class TestPersistenceDedup(unittest.TestCase):
    def setUp(self):
        self._orig = (common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH,
                      common.LAST_REPORTED_PATH)
        self._d = tempfile.mkdtemp()
        common.DATA_DIR = self._d
        common.FAILURES_PATH = os.path.join(self._d, "failures.jsonl")
        common.ARCHIVE_PATH = os.path.join(self._d, "failures.archive.jsonl")
        common.LAST_REPORTED_PATH = os.path.join(self._d, "last_reported.json")

    def tearDown(self):
        common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH, \
            common.LAST_REPORTED_PATH = self._orig
        shutil.rmtree(self._d, ignore_errors=True)

    def test_append_is_idempotent(self):
        recs = mine("seccomp_failure")
        self.assertEqual(capture.append_records(recs), 1)
        self.assertEqual(capture.append_records(recs), 0)  # dedup
        with open(common.FAILURES_PATH) as fh:
            self.assertEqual(sum(1 for _ in fh), 1)


def _rec(session, tid, days_ago, now):
    ts = (now - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"ts": ts, "session_id": session, "tool_use_id": tid,
            "tool": "Bash", "kind": "runtime_failure", "signature": "Bash:x",
            "command": "echo", "snippet": "boom", "project": "p", "cwd": "/p"}


def _lines(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


class TestArchive(unittest.TestCase):
    def setUp(self):
        self._orig = (common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH)
        self._d = tempfile.mkdtemp()
        common.DATA_DIR = self._d
        common.FAILURES_PATH = os.path.join(self._d, "failures.jsonl")
        common.ARCHIVE_PATH = os.path.join(self._d, "failures.archive.jsonl")
        self.now = datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH = self._orig

    def _seed(self, records):
        capture._rewrite_jsonl(common.FAILURES_PATH, records)

    def test_moves_old_keeps_recent(self):
        self._seed([_rec("s", "old", 10, self.now), _rec("s", "new", 2, self.now)])
        moved, kept = capture.archive_stale(retention_days=7, now=self.now)
        self.assertEqual((moved, kept), (1, 1))
        self.assertEqual([r["tool_use_id"] for r in _lines(common.FAILURES_PATH)], ["new"])
        self.assertEqual([r["tool_use_id"] for r in _lines(common.ARCHIVE_PATH)], ["old"])

    def test_undatable_record_is_kept(self):
        bad = _rec("s", "nots", 99, self.now)
        bad["ts"] = ""
        self._seed([bad])
        moved, kept = capture.archive_stale(retention_days=7, now=self.now)
        self.assertEqual((moved, kept), (0, 1))

    def test_idempotent(self):
        self._seed([_rec("s", "old", 10, self.now)])
        self.assertEqual(capture.archive_stale(retention_days=7, now=self.now), (1, 0))
        # Second run: nothing left to move, archive not doubled.
        self.assertEqual(capture.archive_stale(retention_days=7, now=self.now), (0, 0))
        self.assertEqual(len(_lines(common.ARCHIVE_PATH)), 1)

    def test_archived_record_not_resurrected_by_append(self):
        # A record already in the archive must not be re-added to the active log
        # when the same failure is mined again (invariant: no resurrection).
        old = _rec("s", "old", 10, self.now)
        self._seed([old])
        capture.archive_stale(retention_days=7, now=self.now)
        self.assertEqual(_lines(common.FAILURES_PATH), [])
        self.assertEqual(capture.append_records([old]), 0)  # deduped vs archive
        self.assertEqual(_lines(common.FAILURES_PATH), [])


class TestScopedPersistence(unittest.TestCase):
    """Integration tests for append_records / archive_stale with explicit path
    kwargs — exercises the scoped (P8) code path without monkeypatching globals.
    """

    def setUp(self):
        self._d = tempfile.mkdtemp()
        self.fp = os.path.join(self._d, "failures.jsonl")
        self.ap = os.path.join(self._d, "failures.archive.jsonl")
        self.now = datetime.datetime(2026, 7, 8, tzinfo=datetime.timezone.utc)

    def test_append_writes_to_scoped_path(self):
        recs = capture.mine_transcript(
            os.path.join(FIX, "seccomp_failure.jsonl"))
        added = capture.append_records(recs, failures_path=self.fp,
                                       archive_path=self.ap)
        self.assertEqual(added, 1)
        self.assertTrue(os.path.exists(self.fp))
        # The specific records we wrote must not appear in the global log
        # (global log may already have real content — compare by key, not emptiness).
        scoped_keys = {(r.get("session_id"), r.get("tool_use_id"))
                       for r in _lines(self.fp)}
        global_keys = {(r.get("session_id"), r.get("tool_use_id"))
                       for r in _lines(common.FAILURES_PATH)}
        self.assertFalse(scoped_keys & global_keys,
                         "scoped write leaked records into the global log")

    def test_scoped_dedup_spans_both_files(self):
        recs = capture.mine_transcript(
            os.path.join(FIX, "seccomp_failure.jsonl"))
        capture.append_records(recs, failures_path=self.fp, archive_path=self.ap)
        capture.archive_stale(retention_days=0, now=self.now,
                              failures_path=self.fp, archive_path=self.ap)
        # Record is now in archive; re-appending must be deduped.
        added = capture.append_records(recs, failures_path=self.fp,
                                       archive_path=self.ap)
        self.assertEqual(added, 0)
        self.assertEqual(_lines(self.fp), [])

    def test_scoped_archive_does_not_touch_global(self):
        recs = [_rec("s", "old", 10, self.now)]
        capture._rewrite_jsonl(self.fp, recs)
        capture.archive_stale(retention_days=7, now=self.now,
                              failures_path=self.fp, archive_path=self.ap)
        self.assertTrue(os.path.exists(self.ap))
        # Our specific test record must not have leaked into the global archive.
        archived_keys = {(r.get("session_id"), r.get("tool_use_id"))
                         for r in _lines(self.ap)}
        global_archive_keys = {(r.get("session_id"), r.get("tool_use_id"))
                                for r in _lines(common.ARCHIVE_PATH)}
        self.assertFalse(archived_keys & global_archive_keys,
                         "scoped archive leaked records into the global archive")




class TestCaptureMain(unittest.TestCase):
    # Tests for capture.main() entry point.

    def setUp(self):
        self._orig = (common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH,
                      common.LAST_REPORTED_PATH)
        self._d = tempfile.mkdtemp()
        common.DATA_DIR = self._d
        common.FAILURES_PATH = os.path.join(self._d, "failures.jsonl")
        common.ARCHIVE_PATH = os.path.join(self._d, "failures.archive.jsonl")
        common.LAST_REPORTED_PATH = os.path.join(self._d, "last_reported.json")

    def tearDown(self):
        common.DATA_DIR, common.FAILURES_PATH, common.ARCHIVE_PATH, \
            common.LAST_REPORTED_PATH = self._orig
        shutil.rmtree(self._d, ignore_errors=True)

    def test_no_paths_returns_2(self):
        self.assertEqual(capture.main([]), 2)

    def test_basic_run_returns_0_and_writes_record(self):
        # The fixture transcript is old, so archive_stale (called by main) may
        # move the record to the archive.  Count across both files.
        fixture = os.path.join(FIX, "seccomp_failure.jsonl")
        rc = capture.main([fixture])
        self.assertEqual(rc, 0)
        active = _lines(common.FAILURES_PATH)
        archive = _lines(common.ARCHIVE_PATH)
        total = len(active) + len(archive)
        self.assertEqual(total, 1,
                         "expected exactly 1 record across active+archive")

    def test_nonexistent_path_returns_0_zero_records(self):
        # Non-existent paths are silently skipped; no records are written.
        # append_records may still create an empty file when called with 0
        # records (opens in append mode), so we check the line count, not
        # file existence.
        rc = capture.main(["nonexistent_path.jsonl"])
        self.assertEqual(rc, 0)
        self.assertEqual(_lines(common.FAILURES_PATH), [])

    def test_cwd_routes_to_scoped_path(self):
        fixture = os.path.join(FIX, "seccomp_failure.jsonl")
        project_dir = tempfile.mkdtemp()
        try:
            rc = capture.main(["--cwd", project_dir, fixture])
            self.assertEqual(rc, 0)
            _data_dir, expected_fp, _expected_ap = common.scope_paths(project_dir)
            self.assertTrue(os.path.exists(expected_fp))
            self.assertFalse(os.path.exists(common.FAILURES_PATH))
        finally:
            # project_dir is only the cwd hint; the scoped log lives under DATA_DIR (self._d)
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_archive_swallow_does_not_break_return_code(self):
        fixture = os.path.join(FIX, "seccomp_failure.jsonl")
        original = capture.archive_stale

        def _raise(**kw):
            raise RuntimeError("simulated archive failure")

        try:
            capture.archive_stale = _raise
            rc = capture.main([fixture])
            self.assertEqual(rc, 0)
        finally:
            capture.archive_stale = original

if __name__ == "__main__":
    unittest.main()
