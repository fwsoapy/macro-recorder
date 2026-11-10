"""Build everything for a release:

    python build.py

1. release\app\MacroRecorder\   the app folder (PyInstaller --onedir: starts fast, fewer antivirus flags)
2. release\MacroRecorder-portable.exe   one file, runs from anywhere
3. release\MacroRecorderSetup.exe       the one-click installer (needs Inno Setup 6)

Needs: pip install pyinstaller pillow. Pillow only draws the icon; the app itself has no dependencies.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"
WORK = ROOT / "build"


def run(*args):
    print(">", " ".join(str(a) for a in args))
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def version():
    for line in (ROOT / "app.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("APP_VERSION not found in app.py")


def find_iscc():
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe",
                  Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe",
                  Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6/ISCC.exe"]
    found = shutil.which("iscc")
    return Path(found) if found else next((p for p in candidates if p.is_file()), None)


def main():
    v = version()
    run(sys.executable, "assets/make_icon.py")
    shutil.rmtree(RELEASE, ignore_errors=True)
    icon = ROOT / "icon.ico"  # absolute: PyInstaller resolves relative paths against --specpath
    common = ["--noconfirm", "--noconsole", "--icon", icon, "--add-data", f"{icon};.",
              "--workpath", WORK, "--specpath", WORK]
    run(sys.executable, "-m", "PyInstaller", *common, "--onedir", "--name", "MacroRecorder",
        "--distpath", RELEASE / "app", "app.py")
    run(sys.executable, "-m", "PyInstaller", *common, "--onefile", "--name", "MacroRecorder-portable",
        "--distpath", RELEASE, "app.py")
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup 6 not found, so no installer was built. Get it from https://jrsoftware.org/isdl.php")
        return
    run(iscc, f"/DAppVersion={v}", "installer.iss")
    print(f"\nDone. Version {v}:")
    for item in (RELEASE / "MacroRecorderSetup.exe", RELEASE / "MacroRecorder-portable.exe"):
        print(f"  {item.relative_to(ROOT)}  ({item.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
