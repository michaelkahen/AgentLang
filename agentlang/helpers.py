"""Semantic operations available to both AgentLang and the native Python control."""

import builtins as _ag_builtins


def csvrows(path):
    """Read a UTF-8 CSV into a list of dictionaries, using its header as keys."""
    import csv
    from itertools import zip_longest

    with _ag_builtins.open(path, encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        fields = _ag_builtins.next(reader, [])
        width = _ag_builtins.len(fields)
        result = []
        for row in reader:
            if row:
                if _ag_builtins.len(row) > width:
                    record = _ag_builtins.dict(_ag_builtins.zip(fields, row))
                    record[None] = row[width:]
                else:
                    record = _ag_builtins.dict(zip_longest(fields, row))
                result.append(record)
        return result


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


def parsevalue(text, default=None):
    """Read JSON or a Python literal, returning default when neither parses."""
    import ast
    import json

    try:
        return json.loads(text)
    except (_ag_builtins.ValueError, _ag_builtins.RecursionError, _ag_builtins.TypeError):
        pass
    if not _ag_builtins.isinstance(text, _ag_builtins.str):
        return default
    try:
        return ast.literal_eval(text.strip())
    except (_ag_builtins.ValueError, _ag_builtins.TypeError, _ag_builtins.SyntaxError,
            _ag_builtins.RecursionError, _ag_builtins.OverflowError):
        return default


def jsonbytes(value):
    """Serialize using default JSON formatting, one LF, and UTF-8."""
    import json

    return (json.dumps(value) + "\n").encode("utf-8")


def shahex(data):
    """Return a SHA-256 digest as lowercase hexadecimal."""
    import hashlib

    return hashlib.sha256(data).hexdigest()


def least(items, key=None):
    """First minimum item by key, including the first item in a tie."""
    return _ag_builtins.min(items, key=key)


def greatest(items, key=None):
    """First maximum item by key, including the first item in a tie."""
    return _ag_builtins.max(items, key=key)


def smallest(items, n, key=None):
    """Select up to n lowest-ranked items in stable order."""
    import heapq
    import operator

    n = operator.index(n)
    if n < 0:
        raise _ag_builtins.ValueError("n must be nonnegative")
    return heapq.nsmallest(n, items, key=key)


c = csvrows
r = readjson
wj = writejson
v = parsevalue
b = jsonbytes
h = shahex
k = least
x = greatest
t = smallest

# Native execution and standalone compilation use the same public vocabulary.
SHARED_HELPERS = {
    fn.__name__: fn for fn in (csvrows, readjson, writejson, parsevalue, jsonbytes,
                               shahex, least, greatest, smallest)
}
SHARED_HELPERS.update(c=c, r=r, wj=wj, v=v, b=b, h=h, k=k, x=x, t=t)
