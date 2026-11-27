"""Load the previous release side by side with the working tree for comparisons."""

from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys

from benchmarks.scripting.launches import ROOT, stage_package

REVISION = "0e896bc4efcdf0d93b012dbf181b73e4f99f05d1"


def scripts():
    """The full .ag corpus at the start of this round."""
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION], cwd=ROOT, text=True)
    for path in names.splitlines():
        if path.endswith(".ag"):
            yield path, subprocess.check_output(["git", "show", f"{REVISION}:{path}"], cwd=ROOT).decode()


def load_compiler(directory):
    """Stage the pinned package in a caller-owned temporary directory."""
    stage_package(directory, REVISION)
    path = Path(directory) / "agentlang" / "__init__.py"
    name = "_agentlang_previous_release"
    spec = spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
    module = module_from_spec(spec)
    # A preceding benchmark in this process may have removed its staging directory.
    for child in ("compiler", "helpers"):
        sys.modules.pop(f"{name}.{child}", None)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return import_module(f"{name}.compiler")
