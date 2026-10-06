#!/usr/bin/env python3
"""Install Azoth's pinned, project-local toolchain with upstream checksums."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".azoth"
TOOLS = LOCAL / "tools"
DOWNLOADS = LOCAL / "downloads"
LOCK = ROOT / "toolchain.lock.json"
USER_AGENT = "Azoth-local-toolchain-bootstrap/1"


def read_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def latest_github_asset(repository: str, pattern: str) -> dict[str, str]:
    release = read_json(f"https://api.github.com/repos/{repository}/releases/latest")
    asset = next((item for item in release["assets"] if re.fullmatch(pattern, item["name"])), None)
    if asset is None:
        raise RuntimeError(f"no release asset matching {pattern!r} in {repository}")
    digest = asset.get("digest", "")
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"GitHub did not publish a SHA-256 digest for {asset['name']}")
    return {
        "version": release["tag_name"],
        "url": asset["browser_download_url"],
        "sha256": digest.removeprefix("sha256:"),
    }


def latest_jdk() -> dict[str, str]:
    assets = read_json(
        "https://api.adoptium.net/v3/assets/latest/25/hotspot"
        "?architecture=x64&image_type=jdk&os=windows"
    )
    package = assets[0]["binary"]["package"]
    return {
        "version": package["name"].removeprefix("OpenJDK25U-jdk_x64_windows_hotspot_").removesuffix(".zip"),
        "url": package["link"],
        "sha256": package["checksum"],
    }


def refresh_lock() -> dict:
    """Resolve current stable releases; only official project feeds are used."""
    lock = {
        "format": 1,
        "updated": date.today().isoformat(),
        "tools": {
            "ghidra": latest_github_asset(
                "NationalSecurityAgency/ghidra", r"ghidra_[0-9.]+_PUBLIC_[0-9]+\.zip"
            ),
            "jdk": latest_jdk(),
            "caddy": latest_github_asset(
                "caddyserver/caddy", r"caddy_[0-9.]+_windows_amd64\.zip"
            ),
        },
        "python": {
            "pyOpenSSL": read_json("https://pypi.org/pypi/pyOpenSSL/json")["info"]["version"],
            "frida": read_json("https://pypi.org/pypi/frida/json")["info"]["version"],
            "Pillow": read_json("https://pypi.org/pypi/Pillow/json")["info"]["version"],
        },
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"updated {LOCK.relative_to(ROOT)} to current upstream stable versions")
    return lock


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(tool: str, spec: dict[str, str]) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    suffix = Path(spec["url"].split("?", 1)[0]).suffix or ".zip"
    target = DOWNLOADS / f"{tool}-{spec['version']}{suffix}"
    if target.is_file() and sha256(target) == spec["sha256"]:
        return target
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(spec["url"], headers={"User-Agent": USER_AGENT})
    print(f"downloading {tool} {spec['version']}...")
    with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out)
    actual = sha256(partial)
    if actual != spec["sha256"]:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 mismatch for {tool}: expected {spec['sha256']}, got {actual}")
    partial.replace(target)
    return target


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            member = PurePosixPath(item.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"unsafe archive path: {item.filename}")
            path = (destination / Path(*member.parts)).resolve()
            if path != root and root not in path.parents:
                raise RuntimeError(f"archive path escapes target: {item.filename}")
        bundle.extractall(destination)


def _install_archive(tool: str, spec: dict[str, str], target_root: Path, marker: str) -> Path:
    destination = target_root / spec["version"]
    complete = destination / ".azoth-complete.json"
    if complete.is_file():
        try:
            info = json.loads(complete.read_text(encoding="utf-8"))
            if info.get("sha256") == spec["sha256"]:
                return destination
        except json.JSONDecodeError:
            pass
    archive = download(tool, spec)
    destination.mkdir(parents=True, exist_ok=True)
    safe_extract(archive, destination)
    if not next(destination.rglob(marker), None):
        raise RuntimeError(f"{tool} archive did not contain {marker}")
    complete.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return destination


def install_toolchain(lock: dict) -> None:
    ghidra = lock["tools"]["ghidra"]
    jdk = lock["tools"]["jdk"]
    caddy = lock["tools"]["caddy"]
    _install_archive("ghidra", ghidra, TOOLS / "ghidra", "analyzeHeadless.bat")
    _install_archive("jdk", jdk, TOOLS / "jdk", "javac.exe")

    target = ROOT / "deploy" / "bin" / "caddy.exe"
    marker = TOOLS / "caddy-installed.json"
    installed = {}
    if marker.is_file():
        try:
            installed = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            installed = {}
    if not target.is_file() or installed.get("sha256") != caddy["sha256"]:
        caddy_archive = download("caddy", caddy)
        with zipfile.ZipFile(caddy_archive) as bundle:
            item = next(
                (entry for entry in bundle.infolist()
                 if Path(entry.filename).name.casefold() == "caddy.exe"),
                None,
            )
            if item is None:
                raise RuntimeError("Caddy archive does not contain caddy.exe")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.read(item))
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(caddy, indent=2) + "\n", encoding="utf-8")


def install_python_runtime(lock: dict) -> Path:
    spec = lock["runtime"]["python"]
    target = LOCAL / "python" / spec["version"]
    python = target / "python.exe"
    marker = target / ".azoth-python.json"
    if python.is_file() and marker.is_file():
        try:
            if json.loads(marker.read_text(encoding="utf-8")).get("sha256") == spec["sha256"]:
                return python
        except json.JSONDecodeError:
            pass
    if python.is_file():
        version = subprocess.run(
            [str(python), "--version"], check=False, capture_output=True, text=True
        ).stdout.strip()
        if version == f"Python {spec['version']}":
            marker.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
            return python

    installer = download("python", spec)
    target.mkdir(parents=True, exist_ok=True)
    options = [
        str(installer),
        "/quiet",
        "InstallAllUsers=0",
        f"TargetDir={target}",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "Include_tcltk=0",
        "Include_tools=0",
        "Include_pip=1",
        "Shortcuts=0",
    ]
    subprocess.run(options, check=True)
    result = subprocess.run(
        [str(python), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if result != f"Python {spec['version']}":
        raise RuntimeError(f"installed Python version mismatch: expected {spec['version']}, got {result}")
    marker.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    return python


def install_python_packages(lock: dict) -> None:
    base_python = install_python_runtime(lock)
    venv = LOCAL / "venv"
    python = venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"
    if not python.is_file():
        subprocess.run([str(base_python), "-m", "venv", str(venv)], check=True)
    packages = [f"{name}=={version}" for name, version in lock["python"].items()]
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", *packages],
        check=True,
    )
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "toolchain-state.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print("Python dependencies installed in .azoth/venv")


def main() -> int:
    if sys.platform != "win32":
        print("The local Azoth runtime bootstrap currently targets Windows.", file=sys.stderr)
        return 2
    if sys.version_info < (3, 11):
        print("Run `./az.ps1 setup` to install the locked project-local Python runtime.", file=sys.stderr)
        return 2
    update = "--update" in sys.argv[1:]
    lock = refresh_lock() if update else json.loads(LOCK.read_text(encoding="utf-8"))
    try:
        install_toolchain(lock)
        install_python_packages(lock)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print("Azoth local toolchain is ready. Ghidra workspaces stay under reverse/builds/<sha256>/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
