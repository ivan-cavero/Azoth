#!/usr/bin/env python3
"""One-shot: move flat scripts/ into kind folders + write catalog.json.

Safe to re-run: skips files already in place. Uses `git mv` when in a repo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

# basename -> relative path under scripts/
LAYOUT: dict[str, str] = {
    # toolchain
    "bootstrap.py": "toolchain/bootstrap.py",
    "doctor.py": "toolchain/doctor.py",
    # check
    "check-docs.py": "check/check-docs.py",
    "check-paths.py": "check/check-paths.py",
    # test
    "e2e-entry-stub.py": "test/e2e-entry-stub.py",
    # export
    "export-channel-fixture.py": "export/export-channel-fixture.py",
    "export-ladder-fixtures.py": "export/export-ladder-fixtures.py",
    "export-spawn-template.py": "export/export-spawn-template.py",
    "export-wire-fixtures.py": "export/export-wire-fixtures.py",
    # measure
    "ack-audit.py": "measure/ack-audit.py",
    "ack-coverage.py": "measure/ack-coverage.py",
    "ack-window.py": "measure/ack-window.py",
    "alc-position.py": "measure/alc-position.py",
    "icon-timeline.py": "measure/icon-timeline.py",
    "inbound-inventory.py": "measure/inbound-inventory.py",
    "measure-angle-frame.py": "measure/measure-angle-frame.py",
    "measure-cable.py": "measure/measure-cable.py",
    "measure-episodes.py": "measure/measure-episodes.py",
    "measure-inventory-grammar.py": "measure/measure-inventory-grammar.py",
    "measure-position-field.py": "measure/measure-position-field.py",
    "measure-run.py": "measure/measure-run.py",
    "measure-walk.py": "measure/measure-walk.py",
    "measure-world-log.py": "measure/measure-world-log.py",
    "request-response-map.py": "measure/request-response-map.py",
    "wire-parity.py": "measure/wire-parity.py",
    # patch
    "patch-actor-guard.py": "patch/patch-actor-guard.py",
    "patch-dtls-disk.py": "patch/patch-dtls-disk.py",
    "patch-portray-predicate.py": "patch/patch-portray-predicate.py",
    "patch-teardown-guard.py": "patch/patch-teardown-guard.py",
    # gui
    "bmp-diff.py": "gui/bmp-diff.py",
    "click-window.py": "gui/click-window.py",
    "focus-window.py": "gui/focus-window.py",
    "hold-key.py": "gui/hold-key.py",
    "ocr-image.ps1": "gui/ocr-image.ps1",
    "post-input.py": "gui/post-input.py",
    "send-input.py": "gui/send-input.py",
    "shot.py": "gui/shot.py",
    "shrink-image.py": "gui/shrink-image.py",
    "watch-indicator.py": "gui/watch-indicator.py",
    "winwindow.py": "gui/winwindow.py",
    # session
    "capture-world-run.py": "session/capture-world-run.py",
    "form-test-escapes.py": "session/form-test-escapes.py",
    "night-run.py": "session/night-run.py",
    "prejoin-smoke.py": "session/prejoin-smoke.py",
    "private-run.py": "session/private-run.py",
    "run-instrumented-attempt.py": "session/run-instrumented-attempt.py",
    "run-second-client.py": "session/run-second-client.py",
    "trace-session.py": "session/trace-session.py",
    "try-world-shape.py": "session/try-world-shape.py",
    "watch-session.py": "session/watch-session.py",
    # wire
    "decode-ch0.py": "wire/decode-ch0.py",
    "decode-ch1-635.py": "wire/decode-ch1-635.py",
    "logwire.py": "wire/logwire.py",
    "world-inject.py": "wire/world-inject.py",
    # re helpers (static analysis support; heavy RE stays in reverse/tools)
    "corpus-contains.py": "re/corpus-contains.py",
    "corpus-fn.py": "re/corpus-fn.py",
    "find-codec-facet.py": "re/find-codec-facet.py",
    "map-descriptors.py": "re/map-descriptors.py",
    # ops
    "gen_openapi.py": "ops/gen_openapi.py",
    "trust-caddy-ca.py": "ops/trust-caddy-ca.py",
}


def git_mv(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if not src.exists():
        print(f"missing source: {src}", file=sys.stderr)
        return
    subprocess.check_call(["git", "mv", str(src), str(dst)], cwd=ROOT)


def main() -> int:
    for name, rel in sorted(LAYOUT.items()):
        src = SCRIPTS / name
        dst = SCRIPTS / rel
        if src.resolve() == dst.resolve():
            continue
        if dst.is_file() and not src.is_file():
            continue
        if src.is_file():
            git_mv(src, dst)
            print(f"moved {name} -> {rel}")

    catalog = {
        "format": 1,
        "entry": "python ef.py run <name>",
        "kinds": sorted({Path(p).parts[0] for p in LAYOUT.values()}),
        "scripts": {
            Path(name).stem: {
                "path": rel,
                "kind": Path(rel).parts[0],
                "file": name,
            }
            for name, rel in sorted(LAYOUT.items())
        },
    }
    (SCRIPTS / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    print(f"catalog: {len(catalog['scripts'])} scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
