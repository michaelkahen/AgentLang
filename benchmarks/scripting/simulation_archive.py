"""Apply narrow spelling edits to frozen scripts without reformatting the source."""

import ast
from collections import Counter
import hashlib
import io
import json
import keyword
from pathlib import Path
import subprocess
import tokenize

from agentlang import compile_python, compile_source


BASELINE = "8a5b5c538912000a18eedb100cb4402da5960d7c"


def previous_source(root, path):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=root).decode()


def tooling_sources(root):
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", BASELINE, "benchmarks"], cwd=root, text=True
    ).splitlines()
    for path in paths:
        if path.endswith(".py") and "sources" not in Path(path).parts:
            yield path, previous_source(root, path), False


def sources(root):
    for folder in ("long/generation/observations", "long/generation/required",
                   "patterns/generation/observations"):
        for p in sorted((root / "benchmarks" / folder / "sources").iterdir()):
            if p.suffix in (".ag", ".py"):
                yield str(p.relative_to(root)), p.read_text(), p.suffix == ".ag"
    pilot = root / "benchmarks/pilot/generation/trials.json"
    for t in json.loads(pilot.read_text())["trials"]:
        if t["passed"]:
            yield (f"{pilot.relative_to(root)}#{t['arm']}/{t['task']}/{t['round']}",
                   t["source"], t["arm"] == "compact")


def eligible_edits(source):
    """Find single-string .get calls and mixed identifier-key *literal* mappings.

    Only strip whitespace in the selected key or punned field. Ignore records
    with comments, unpacking, composite or duplicate keys, or a trailing empty
    field other than a trailing comma. Preserve all expression spelling.
    """
    offsets = [0]
    for line in io.StringIO(source):
        offsets.append(offsets[-1] + len(line))

    def offset(pos):
        return offsets[pos[0] - 1] + pos[1]

    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    gets, records, stack = [], [], []
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.OP and tok.string == "." and i + 4 < len(tokens):
            name, opening, key, closing = tokens[i + 1:i + 5]
            if (i and tokens[i - 1].end == tok.start and name.string == "get"
                    and opening.string == "(" and key.type == tokenize.STRING and closing.string == ")"):
                value = ast.literal_eval(key.string)
                if isinstance(value, str) and value.isascii() and value.isidentifier():
                    gets.append((offset(tok.start), offset(closing.end), "?" + value))
        if tok.type != tokenize.OP:
            continue
        if tok.string in ("{", "(", "["):
            stack.append((i, []))
        elif tok.string == "," and stack:
            stack[-1][1].append(i)
        elif tok.string in ("}", ")", "]") and stack:
            start, commas = stack.pop()
            if tok.string != "}" or (start and tokens[start - 1].string == "d"):
                continue
            replacements, names = [], set()
            copied = computed = 0
            # Require every field to qualify. Exact byte/character offsets remain
            # those of the authored source even across multiline values.
            ends = [*commas, i]
            begin = start + 1
            for end in ends:
                field = [t for t in tokens[begin:end] if t.type != tokenize.NL]
                begin = end + 1
                if not field and end == i:
                    continue
                if (len(field) < 3 or field[0].type != tokenize.STRING or field[1].string != ":"
                        or any(t.type == tokenize.COMMENT for t in field)):
                    break
                key = ast.literal_eval(field[0].string)
                if not (isinstance(key, str) and key.isascii() and key.isidentifier()
                        and not keyword.iskeyword(key) and key not in names):
                    break
                names.add(key)
                if len(field) == 3 and field[2].type == tokenize.NAME and field[2].string == key:
                    replacements.append((offset(field[0].start), offset(field[2].end), key))
                    copied += 1
                else:
                    replacements.append((offset(field[0].start), offset(field[1].end), key + "="))
                    computed += 1
            else:
                if copied and computed:
                    pos = offset(tokens[start].start)
                    records.append([(pos, pos, "d"), *replacements])
    return gets, records


def apply(source, edits):
    for a, b, value in sorted(edits, reverse=True):
        source = source[:a] + value + source[b:]
    return source


def inspect(programs, encodings):
    paths = list(programs)
    seen = set()
    rows = []
    for path, src, compact in paths:
        digest = hashlib.sha256(src.encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        gets, records = eligible_edits(src)
        edits = [item for record in records for item in record]
        baseline = compile_source if compact else compile_python
        reference = ast.dump(ast.parse(baseline(src)))
        variants = dict(current=src, lookup=apply(src, gets), record=apply(src, edits),
                        combined=apply(src, gets + edits))
        for label, variant in variants.items():
            if ast.dump(ast.parse(compile_source(variant))) != reference:
                raise AssertionError(f"{path} {label} changed the standalone AST")
        counts = {enc.name: {k: len(enc.encode_ordinary(s)) for k, s in variants.items()}
                  for enc in encodings}
        rows.append(dict(path=path, sha256=digest, lookups=len(gets), records=len(records), tokens=counts))
    return dict(sources_before_dedup=len(paths), unique_sources=len(rows),
                changed_sources=sum(bool(row["lookups"] or row["records"]) for row in rows),
                lookup_sites=sum(row["lookups"] for row in rows),
                mixed_record_sites=sum(row["records"] for row in rows),
                tokens={e.name: dict(sum((Counter(r["tokens"][e.name]) for r in rows), Counter()))
                        for e in encodings}, programs=rows)
