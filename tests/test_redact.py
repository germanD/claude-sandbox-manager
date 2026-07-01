import os
import sys
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)

import redact  # noqa: E402


class TestRedaction(unittest.TestCase):
    def test_authorization_header_scrubbed(self):
        out = redact.redact("curl -H 'Authorization: Bearer sk-abcdef1234567890abcdef'")
        self.assertNotIn("sk-abcdef1234567890abcdef", out)
        self.assertIn("[REDACTED]", out)

    def test_bare_sk_key_scrubbed(self):
        out = redact.redact("key=sk-abcdefghij0123456789")
        self.assertNotIn("sk-abcdefghij0123456789", out)

    def test_github_token_scrubbed(self):
        out = redact.redact("git remote add o https://ghp_ABCDEFGH12345678xyz@github.com")
        self.assertNotIn("ghp_ABCDEFGH12345678xyz", out)
        self.assertIn("[REDACTED_TOKEN]", out)

    def test_aws_key_scrubbed(self):
        out = redact.redact("export AWS=AKIAIOSFODNN7EXAMPLE")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_pem_block_scrubbed(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----"
        out = redact.redact("here " + pem)
        self.assertNotIn("abc", out)
        self.assertIn("[REDACTED_PRIVATE_KEY]", out)

    def test_env_secret_assignment_scrubbed(self):
        out = redact.redact("MY_SECRET=supersecretvalue GITHUB_TOKEN=abcd1234")
        self.assertNotIn("supersecretvalue", out)
        self.assertNotIn("abcd1234", out)

    def test_redact_none_and_empty(self):
        self.assertEqual(redact.redact(""), "")
        self.assertIsNone(redact.redact(None))


class TestDenylist(unittest.TestCase):
    def test_priv_misc_is_default_denied(self):
        self.assertIn("priv-misc", redact.load_denylist())

    def test_is_denied_matches_substring_case_insensitive(self):
        self.assertTrue(redact.is_denied("cat /home/u/Priv-Misc/x"))
        self.assertFalse(redact.is_denied("cat /home/u/public/x"))

    def test_is_denied_ignores_empty_args(self):
        self.assertFalse(redact.is_denied("", None, "ls"))


class TestMasking(unittest.TestCase):
    def test_mask_command_bash_keeps_program_only(self):
        self.assertEqual(
            redact.mask_command("Bash", "cat /home/u/priv-misc/secret.txt"),
            "cat [denied-args]",
        )

    def test_mask_command_bash_single_token(self):
        self.assertEqual(redact.mask_command("Bash", "pwd"), "pwd")

    def test_mask_command_non_bash_is_path_masked(self):
        self.assertEqual(
            redact.mask_command("Read", "/home/u/priv-misc/secret.txt"),
            "[denied-path]",
        )

    def test_mask_command_strips_leading_path_of_program(self):
        self.assertEqual(
            redact.mask_command("Bash", "/usr/bin/ls -la /priv-misc"),
            "ls [denied-args]",
        )

    def test_mask_snippet_by_kind(self):
        self.assertIn("permission denied", redact.mask_snippet("permission_denied"))
        self.assertIn("error", redact.mask_snippet("runtime_failure"))


class TestCleanSnippet(unittest.TestCase):
    def test_truncates_long_text(self):
        out = redact.clean_snippet("x" * 500, limit=100)
        self.assertLessEqual(len(out), 101)  # +1 for the ellipsis char
        self.assertTrue(out.endswith("…"))

    def test_redacts_before_truncating(self):
        out = redact.clean_snippet("token=sk-abcdefghij0123456789 tail")
        self.assertNotIn("sk-abcdefghij0123456789", out)


if __name__ == "__main__":
    unittest.main()
