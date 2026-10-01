"""Build a local AppleScript app without reading or embedding OTP secrets."""

import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile


BUNDLE_ID = "io.github.wondonghwi.authenticator-otp"


def identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,127}", value):
        raise argparse.ArgumentTypeError("Use a short ASCII service/account identifier.")
    return value


def app_name(value):
    if (not value.strip() or value != value.strip() or len(value) > 64
            or value.startswith(".") or any(c in value for c in '/:\\')
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise argparse.ArgumentTypeError("Use 1-64 characters without path separators or control characters.")
    return value


def applescript_string(value):
    if any(ord(c) < 32 for c in value):
        raise ValueError("Paths and settings must not contain control characters.")
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", type=app_name, default="auth-otp",
                        help="Finder/Spotlight app name (default: auth-otp).")
    parser.add_argument("--service", type=identifier, default="auth-otp")
    parser.add_argument("--account", type=identifier, default="default")
    parser.add_argument("--destination", type=Path, default=Path.home() / "Applications",
                        help="Installation directory (default: ~/Applications).")
    parser.add_argument("--replace", action="store_true",
                        help="Replace this tool's existing app with the same name.")
    args = parser.parse_args(argv)
    if sys.platform != "darwin" or sys.version_info < (3, 9):
        parser.error("macOS and Python 3.9+ are required.")
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # Distinct profile apps need distinct identifiers for Finder/Spotlight.
    bundle_id = BUNDLE_ID + "." + hashlib.sha256(args.name.encode()).hexdigest()[:16]
    target = destination / (args.name + ".app")
    if os.path.lexists(target):
        info_path = target / "Contents/Info.plist"
        try:
            info = plistlib.loads(info_path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            info = {}
        if (target.is_symlink() or info.get("CFBundleIdentifier") != bundle_id
                or not (target / "Contents/Resources/auth-otp.py").is_file()):
            parser.error("The destination already exists and is not an auth-otp app.")
        if not args.replace:
            parser.error("The app already exists. Use --replace to update it.")

    root = Path(__file__).resolve().parent.parent
    template = (root / "macos/auth-otp.applescript").read_text()
    replacements = {
        "__APP_NAME__": args.name,
        "__PYTHON_PATH__": sys.executable,
        "__SERVICE__": args.service,
        "__ACCOUNT__": args.account,
    }
    # Substitute once, so values cannot inject another placeholder substitution.
    source = re.sub(r"__APP_NAME__|__PYTHON_PATH__|__SERVICE__|__ACCOUNT__",
                    lambda m: applescript_string(replacements[m.group()]), template)
    with tempfile.TemporaryDirectory(prefix="auth-otp-build-") as folder:
        temporary = Path(folder)
        script = temporary / "launcher.applescript"
        script.write_text(source)
        app = temporary / target.name
        subprocess.run(["/usr/bin/osacompile", "-o", str(app), str(script)], check=True)
        resources = app / "Contents/Resources"
        shutil.copy2(root / "bin/auth-otp", resources / "auth-otp.py")
        shutil.copy2(root / "assets/auth-otp.icns", resources / "auth-otp.icns")
        plist = str(app / "Contents/Info.plist")
        for field, value in [("CFBundleName", args.name), ("CFBundleIconFile", "auth-otp"),
                             ("CFBundleIdentifier", bundle_id)]:
            subprocess.run(["/usr/bin/plutil", "-replace", field, "-string", value, plist], check=True)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
        subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(app)], check=True)
        # Stage on the destination filesystem before replacing a working app.
        with tempfile.TemporaryDirectory(prefix=".auth-otp-install-", dir=destination) as staging:
            staged = Path(staging) / target.name
            subprocess.run(["/usr/bin/ditto", str(app), str(staged)], check=True)
            if target.exists():
                shutil.rmtree(target)
            staged.rename(target)
    print(f"Installed {target}")
    print("Open it in Finder or Spotlight. The OTP secret stays in Keychain.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError):
        print("Installation failed. Check Python, macOS tools and destination permissions.", file=sys.stderr)
        raise SystemExit(1)
