"""Repo-local output paths shared by private-client probes."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_STATE = REPO_ROOT / ".azoth"


def project_log(name: str) -> Path:
    path = LOCAL_STATE / "logs" / Path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def probe_capture(name: str) -> Path:
    path = LOCAL_STATE / "captures" / "probes" / Path(name).name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
