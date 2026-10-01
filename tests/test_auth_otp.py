"""Public RFC 6238 vectors and mocked OS boundaries; no personal secrets."""

import argparse
import base64
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


otp = load("auth_otp", ROOT / "bin/auth-otp")
installer = load("install_app", ROOT / "scripts/install_app.py")
scanner = load("check_publication", ROOT / "scripts/check-publication.py")
# RFC 6238 Appendix B: published, synthetic test data, never a live credential.
RFC_KEYS = {
    "SHA1": b"12345678901234567890",
    "SHA256": b"12345678901234567890123456789012",
    "SHA512": b"1234567890123456789012345678901234567890123456789012345678901234",
}
RFC_TIMES = [59, 1111111109, 1111111111, 1234567890, 2000000000, 20000000000]
RFC_CODES = {
    "SHA1": ["94287082", "07081804", "14050471", "89005924", "69279037", "65353130"],
    "SHA256": ["46119246", "68084774", "67062674", "91819424", "90698825", "77737706"],
    "SHA512": ["90693936", "25091201", "99943326", "93441116", "38618901", "47863826"],
}
PUBLIC_SECRET = base64.b32encode(RFC_KEYS["SHA1"]).decode()


class TOTPTests(unittest.TestCase):
    def test_all_rfc_vectors(self):
        for algorithm, key in RFC_KEYS.items():
            config = otp.parse_secret(base64.b32encode(key).decode(), algorithm, 8, 30)
            for timestamp, expected in zip(RFC_TIMES, RFC_CODES[algorithm]):
                with self.subTest(algorithm=algorithm, timestamp=timestamp):
                    self.assertEqual(otp.generate_totp(config, timestamp)[0], expected)

    def test_default_six_digits_and_boundary(self):
        config = otp.parse_secret(PUBLIC_SECRET)
        self.assertEqual(otp.generate_totp(config, 59), ("287082", 1))
        self.assertEqual(otp.generate_totp(config, 60)[1], 30)

    def test_whitespace_lowercase_and_unpadded_base32(self):
        self.assertEqual(otp.parse_secret(" \n" + PUBLIC_SECRET.lower().rstrip("=") + " "),
                         otp.parse_secret(PUBLIC_SECRET))

    def test_uri_settings_and_explicit_overrides(self):
        uri = f"otpauth://totp/Example:personal?secret={PUBLIC_SECRET}&algorithm=SHA256&digits=8&period=60"
        config = otp.parse_secret(uri)
        self.assertEqual(config[1:], ("SHA256", 8, 60))
        self.assertEqual(otp.parse_secret(uri, "SHA1", 6, 30)[1:], ("SHA1", 6, 30))

    def test_bad_secrets_have_sanitized_errors(self):
        inputs = ["", "BAD!SECRET", "A", "=" * 8, "x" * 8193,
                  "otpauth://hotp/example?secret=" + PUBLIC_SECRET,
                  "otpauth://totp/example", "otpauth://totp/example?secret=",
                  "otpauth://totp/example?secret=x&secret=y",
                  f"otpauth://totp/example?secret={PUBLIC_SECRET}&period=0",
                  f"otpauth://totp/example?secret={PUBLIC_SECRET}&digits=7",
                  f"otpauth://totp/example?secret={PUBLIC_SECRET}&algorithm=MD5",
                  f"otpauth://totp/example?secret={PUBLIC_SECRET}&period=oops",
                  f"otpauth://totp/example?secret={PUBLIC_SECRET}&period=30&period=60"]
        for raw in inputs:
            with self.subTest(kind=inputs.index(raw)):
                with self.assertRaises(otp.OTPError) as error:
                    otp.parse_secret(raw)
                if raw:
                    self.assertNotIn(raw, str(error.exception))

    def test_parameter_limits(self):
        for overrides in [{"digits": 5}, {"period": -1}, {"period": 86401},
                          {"algorithm": "MD5"}]:
            with self.subTest(overrides=overrides), self.assertRaises(otp.OTPError):
                otp.parse_secret(PUBLIC_SECRET, **overrides)


class BoundaryTests(unittest.TestCase):
    def test_keychain_read_is_scoped_and_secret_is_not_in_arguments(self):
        with patch.object(otp.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, PUBLIC_SECRET + "\n", "")) as run:
            self.assertEqual(otp.keychain_get("auth-otp.personal", "primary", Path("/tmp/test.keychain")), PUBLIC_SECRET)
            argv = run.call_args.args[0]
            self.assertEqual(argv, ["/usr/bin/security", "find-generic-password", "-s",
                                   "auth-otp.personal", "-a", "primary", "-w", "/tmp/test.keychain"])
            self.assertNotIn(PUBLIC_SECRET, argv)
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_keychain_failure_does_not_echo_stderr(self):
        with patch.object(otp.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 44, "", "private diagnostic")):
            with self.assertRaises(otp.OTPError) as error:
                otp.keychain_get("auth-otp", "default", Path("/tmp/test.keychain"))
            self.assertNotIn("private diagnostic", str(error.exception))

    def run_cli(self, args, secret=PUBLIC_SECRET, clipboard_error=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(otp.sys, "platform", "darwin"), \
                patch.object(otp, "keychain_get", return_value=secret), \
                patch.object(otp, "copy_to_clipboard", side_effect=clipboard_error) as copy, \
                patch.object(otp.time, "time", return_value=59), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = otp.main(args)
        return result, out.getvalue(), err.getvalue(), copy

    def test_check_never_writes_clipboard_or_prints_code(self):
        status, out, err, copy = self.run_cli(["--check"])
        self.assertEqual(status, 0)
        copy.assert_not_called()
        self.assertNotIn(PUBLIC_SECRET, out + err)
        self.assertNotIn("287082", out + err)

    def test_normal_run_copies_only_code(self):
        status, out, err, copy = self.run_cli([])
        self.assertEqual(status, 0)
        copy.assert_called_once_with("287082")
        self.assertNotIn("287082", out + err)

    def test_quiet_run(self):
        status, out, err, _ = self.run_cli(["--quiet"])
        self.assertEqual((status, out, err), (0, "", ""))

    def test_unexpected_exception_is_sanitized(self):
        status, out, err, _ = self.run_cli([], clipboard_error=RuntimeError(PUBLIC_SECRET))
        self.assertEqual(status, 1)
        self.assertNotIn(PUBLIC_SECRET, out + err)

    def test_invalid_stored_secret_never_reaches_clipboard(self):
        invalid = "PRIVATE-invalid-value!"
        status, out, err, copy = self.run_cli([], secret=invalid)
        self.assertEqual(status, 1)
        copy.assert_not_called()
        self.assertNotIn(invalid, out + err)

    def test_identifier_rejects_options_and_shell_input(self):
        for value in ["-bad", "x; command", "x\ny", "", "../name"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                otp.validate_identifier(value)

    def test_clipboard_passes_code_through_stdin(self):
        with patch.object(otp.subprocess, "run") as run:
            otp.copy_to_clipboard("000001")
            run.assert_called_once_with(["/usr/bin/pbcopy"], input="000001", text=True, check=True)


class InstallerTests(unittest.TestCase):
    def test_name_validation(self):
        self.assertEqual(installer.app_name("개인 OTP"), "개인 OTP")
        for value in ["../app", "app/name", "app:name", "app\nname", " .hidden", ".hidden"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                installer.app_name(value)

    def test_applescript_string_escaping(self):
        self.assertEqual(installer.applescript_string('a"b'), '"a\\"b"')
        with self.assertRaises(ValueError):
            installer.applescript_string("bad\npath")

    def test_existing_unrelated_app_is_not_replaced(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "auth-otp.app"
            target.mkdir()
            with patch.object(installer.sys, "platform", "darwin"), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                installer.main(["--destination", folder, "--replace"])
            self.assertTrue(target.exists())


class PublicationTests(unittest.TestCase):
    def test_detects_synthetic_credentials_and_private_paths(self):
        for category, value in [
            ("github-token", "gh" + "p_" + "a" * 30),
            ("personal-email", "private" + "@" + "invalid.test"),
            ("personal-home-path", "/" + "Users/" + "private/project"),
            ("literal-otp-secret", "secret=" + PUBLIC_SECRET),
        ]:
            with self.subTest(category=category):
                self.assertIn(category, scanner.findings("sample.txt", value.encode()))

    def test_rejects_keychain_files_and_app_bundles(self):
        self.assertIn("sensitive-file-name", scanner.findings("sample.keychain-db", b""))
        self.assertIn("sensitive-file-name", scanner.findings("sample.app/Contents/test", b""))

    def test_allows_documentation_placeholders(self):
        self.assertEqual(scanner.findings("example.txt", b"secret=YOUR_BASE32_SECRET"), [])

    def test_sanitized_icons_have_no_ancillary_metadata(self):
        for name in ["assets/auth-otp-icon.png", "assets/auth-otp.icns"]:
            with self.subTest(name=name):
                self.assertEqual(scanner.findings(name, (ROOT / name).read_bytes()), [])


if __name__ == "__main__":
    unittest.main()
