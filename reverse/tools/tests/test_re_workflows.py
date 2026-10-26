"""RE workflow import gate.

Every workflow in `reverse/tools/catalog.json` is a public entry point:
`python ef.py re <name>`. The kind-layout reorg moved those files into kind
subfolders and left the cross-kind imports alone (`corpus/decomp.py` imports
`peutil`, `pe/*.py` and `type/*.py` import `catalog`), so seven of the ten
workflows died with `ModuleNotFoundError` before they could print usage. A
catalog entry that cannot be started is worse than a missing one: the failure
looks like a client problem, not a packaging problem.

Each workflow is loaded in a fresh interpreter, so a module left in this
process's `sys.modules` cannot hide a broken path. Module bodies only define
functions and constants (every one is guarded by `if __name__ == "__main__"`),
so loading a workflow does no analysis work.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]
CATALOG = TOOLS / "catalog.json"

LOAD_MODULE = (
    "import importlib.util as u, sys\n"
    "spec = u.spec_from_file_location('re_workflow_probe', sys.argv[1])\n"
    "module = u.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
)


class WorkflowImports(unittest.TestCase):
    def test_every_catalogued_workflow_imports(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        workflows = catalog["workflows"]
        self.assertGreater(len(workflows), 0, "the catalog lists no workflows")
        for name, meta in sorted(workflows.items()):
            with self.subTest(workflow=name):
                script = TOOLS / meta["path"]
                self.assertTrue(script.is_file(), f"{name}: missing {script}")
                proc = subprocess.run(
                    [sys.executable, "-c", LOAD_MODULE, str(script)],
                    cwd=REPO,
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"`python ef.py re {name}` cannot start:\n{proc.stderr.strip()[-1200:]}",
                )


if __name__ == "__main__":
    unittest.main()
