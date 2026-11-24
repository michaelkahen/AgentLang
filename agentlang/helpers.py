"""I/O helpers shared by AgentLang and the native Python control."""

import builtins as _ag_builtins


def csvrows(path):
    """Read a UTF-8 CSV into a list of dictionaries, using its header as keys."""
    import csv

    with _ag_builtins.open(path, encoding="utf-8", newline="") as stream:
        return _ag_builtins.list(csv.DictReader(stream))


def readjson(path=None):
    """Load JSON from a UTF-8 file or from standard input when path is omitted."""
    import json
    import sys

    if path is None:
        return json.load(sys.stdin)
    with _ag_builtins.open(path, encoding="utf-8") as stream:
        return json.load(stream)


def writejson(value):
    """Print one JSON value, using Python's default JSON formatting."""
    import json

    _ag_builtins.print(json.dumps(value))


c = csvrows
r = readjson
wj = writejson
