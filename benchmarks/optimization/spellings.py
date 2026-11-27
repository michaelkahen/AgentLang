"""Count eight spellings for fixed identifier sequences and check transfer to complete scripts."""

import argparse
import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import random
import subprocess
import tokenize

import tiktoken

from agentlang import compile_source
from agentlang.compiler import _translate
from benchmarks.optimization.baseline import REVISION
from benchmarks.patterns.batch.run import TASKS, split_response
from benchmarks.scripting.record_preparation import measure
from benchmarks.scripting.simulation_archive import apply, eligible_edits, sources, tooling_sources


ROOT = Path(__file__).resolve().parents[2]
SEED = 207173
ENCODINGS = ("o200k_base", "cl100k_base")
DOMAINS = (
    "id name group owner active weight age country email language role created_at updated_at label",
    "score rank votes metric distance fold train test uniform euclidean manhattan confidence precision recall",
    "movies releases genres credits director editor writer actor title budget revenue year country language",
    "opened running failed closed cancelled pending queued active stale timed_out skipped done requested verified",
    "model actor tool system user assistant timestamp command usage input_tokens output_tokens cache retries status",
    "count sum min max mean median median_us samples size total codes rows columns features",
    "sku cost price tax quantity paid vendor region order_id shipment shipped postal_code unit aisle",
    "α β γ café naïve résumé Zürich 東京 香港 Ελλάδα Oslo Québec Österreich México",
)
TEMPLATES = (
    "fields = {}\n", "selected = mode in {}\n", "ordered = sorted({})\n",
    "for name in {}:\n    totals[name] = 0\n",
    "def defaults():\n    return {}\n", "schema = dict.fromkeys({}, 0)\n",
    "out = [entry[key] for key in {}]\n", "result = list(zip({}, values))\n",
)


def spellings(words, kind):
    left, right = ("[", "]") if kind == "list" else ("(", ")")
    quoted = [repr(word) for word in words]
    spaced = " ".join(words)
    split = repr(spaced) + ".split()"
    return {
        "quoted": left + ", ".join(quoted) + right,
        "compact_quotes": left + ",".join(quoted) + right,
        "split": split if kind == "list" else "tuple(" + split + ")",
        "dollar": "$" + left + spaced + right,
        "comma": "$" + left + ",".join(words) + right,
        "question": "?" + left + spaced + right,
        "typed_braces": ("l" if kind == "list" else "t") + "{" + spaced + "}",
        "single_word_sigil": left + ",".join("$" + word for word in words) + right,
    }


def generated(n, encoders):
    rng = random.Random(SEED)
    domains = [s.split() for s in DOMAINS]
    totals = {enc.name: Counter() for enc in encoders}
    directions = {enc.name: Counter() for enc in encoders}
    lengths = Counter()
    value_checks = 0
    seen = set()
    while len(seen) < n:
        domain = rng.choice(domains)
        size = rng.choice((2, 3, 4, 6, 8, 12))
        words = rng.sample(domain, size)
        kind = rng.choice(("list", "tuple"))
        template = rng.choice(TEMPLATES)
        variants = {k: template.format(v) for k, v in spellings(words, kind).items()}
        fingerprint = hashlib.sha256(variants["quoted"].encode()).digest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        lengths[size] += 1
        if len(seen) % 32 == 0:
            expression = spellings(words, kind)["dollar"]
            value = eval(compile_source(expression), {})
            expected = words if kind == "list" else tuple(words)
            if type(value) is not type(expected) or value != expected:
                raise AssertionError(expression)
            value_checks += 1
        for enc in encoders:
            costs = {k: len(enc.encode_ordinary(v)) for k, v in variants.items()}
            best = min(costs[k] for k in ("quoted", "compact_quotes", "split"))
            totals[enc.name].update(costs)
            totals[enc.name]["best_existing"] += best
            diff = costs["dollar"] - best
            directions[enc.name]["shorter" if diff < 0 else "longer" if diff > 0 else "equal"] += 1
    return {"distinct_cases": n, "case_sha256": hashlib.sha256(b"".join(sorted(seen))).hexdigest(),
            "literal_value_checks": value_checks, "renderings_per_encoder": n * 8, "template_count": len(TEMPLATES),
            "word_counts": lengths, "tokens": totals, "dollar_vs_best_existing": directions}


def sequence_edits(source):
    """Replace only self-contained list/tuple literals of two or more plain words."""
    lines = [0]
    for line in io.StringIO(source):
        lines.append(lines[-1] + len(line))

    def pos(coord):
        return lines[coord[0] - 1] + coord[1]

    toks = [t for t in tokenize.generate_tokens(io.StringIO(source).readline)
            if t.type != tokenize.NL]
    stack = []
    edits = []
    for i, tok in enumerate(toks):
        if tok.type != tokenize.OP:
            continue
        if tok.string in "([{":
            stack.append(i)
        elif tok.string in ")]}" and stack:
            start = stack.pop()
            if tok.string == "}":
                continue
            # Exclude indexing, function calls and signatures.
            before = toks[start - 1] if start else None
            if before and (before.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING)
                           or before.string in (")", "]", "}")) and before.string not in {
                               "return", "yield", "in", "is", "else", "not", "and", "or"}:
                continue
            items = toks[start + 1:i]
            if len(items) < 3 or any(t.string != "," for t in items[1::2]):
                continue
            words = []
            for t in items[::2]:
                if (t.type != tokenize.STRING or t.string[:1] not in ("'", '"')
                        or not t.string[1:-1].isidentifier()):
                    break
                words.append(t.string[1:-1])
            else:
                kind = "list" if tok.string == "]" else "tuple"
                edits.append((pos(toks[start].start), pos(tok.end), words, kind))
    return edits


def held_out():
    """Batched responses carry their own historical task delimiters."""
    directory = "benchmarks/patterns/batch/observations/"
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", REVISION, directory],
                                    cwd=ROOT, text=True).splitlines()
    for path in paths:
        if path.endswith(".txt"):
            batch = subprocess.check_output(["git", "show", f"{REVISION}:{path}"], cwd=ROOT, text=True)
            scripts = split_response(batch, TASKS)
            if len(scripts) != 4:
                raise ValueError(path)
            for task, source in scripts.items():
                yield f"{path}#{task}", source, "compact-" in path


def project_holdout():
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", REVISION, "agentlang", "tests"], cwd=ROOT, text=True
    ).splitlines()
    for path in paths:
        if path.endswith(".py"):
            text = subprocess.check_output(["git", "show", f"{REVISION}:{path}"], cwd=ROOT, text=True)
            yield path, text, False


def transfer(programs, encoders, seen, timed=False):
    sums = {enc.name: Counter() for enc in encoders}
    alternatives = Counter()
    rng = random.Random(SEED)
    rows = []
    for path, original, _ in programs:
        if original in seen:
            continue
        seen.add(original)
        gets, records = eligible_edits(original)
        text = apply(original, gets + [e for record in records for e in record])
        # Count other proposed idioms on user code, excluding embedded helpers.
        for node in ast.walk(ast.parse(_translate(text, path)[0])):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and len(node.args) == 2 and not node.keywords
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                    and node.args[0].value.isidentifier()):
                alternatives["literal_get_with_default"] += 1
            if (isinstance(node, ast.Set) and len(node.elts) >= 2
                    and all(isinstance(v, ast.Constant) and isinstance(v.value, str)
                            and v.value.isidentifier() for v in node.elts)):
                alternatives["sets_of_words"] += 1
        sites = sequence_edits(text)
        variants = {"authored": text}
        for arm in ("dollar", "compact_quotes", "split", "question", "typed_braces", "comma", "single_word_sigil"):
            edits = [(a, b, spellings(words, kind)[arm]) for a, b, words, kind in sites]
            variants[arm] = apply(text, edits)
        if ast.dump(ast.parse(compile_source(text))) != ast.dump(ast.parse(compile_source(variants["dollar"]))):
            raise AssertionError(f"changed AST in {path}")
        counts = {}
        for enc in encoders:
            counts[enc.name] = {arm: len(enc.encode_ordinary(src)) for arm, src in variants.items()}
            costs = counts[enc.name]
            costs["best_existing"] = min(costs[k] for k in ("authored", "compact_quotes", "split"))
            sums[enc.name].update(costs)
        rows.append({"path": path, "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
                     "list": sum(s[3] == "list" for s in sites), "tuple": sum(s[3] == "tuple" for s in sites),
                     "tokens_saved": {enc: costs["authored"] - costs["dollar"] for enc, costs in counts.items()}})
        if timed and sites:
            rows[-1]["preparation_median_us"] = measure(path, text, variants["dollar"], 21, rng)["median_us"]
    return {"program_count": len(rows), "affected": sum(bool(r["list"] or r["tuple"]) for r in rows),
            "sites": sum(r["list"] + r["tuple"] for r in rows), "tokens": sums,
            "other_opportunities": alternatives, "programs": rows}


def reference_cost(encoders):
    old = subprocess.check_output(["git", "show", REVISION + ":docs/agent-reference.txt"],
                                  cwd=ROOT, text=True)
    new = (ROOT / "docs/agent-reference.txt").read_text()
    without_addition = "".join(line for line in new.splitlines(keepends=True)
                               if not line.startswith("$[id name]"))
    return {enc.name: {name: len(enc.encode_ordinary(text)) for name, text in
                       (("previous", old), ("edited_without_new_line", without_addition), ("final", new))}
            for enc in encoders}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=131072)
    args = parser.parse_args()
    if not 1 <= args.cases <= 1_000_000:
        parser.error("--cases must be in 1..1,000,000")
    encoders = [tiktoken.get_encoding(name) for name in ENCODINGS]
    simulations = generated(args.cases, encoders)
    report = {"seed": SEED, "baseline": REVISION, "tiktoken": tiktoken.__version__,
              "python": platform.python_version(), "platform": platform.platform(), "generated": simulations,
              "reference_tokens": reference_cost(encoders), "preparation_pairs": 21, "preparation_warmups": 2}
    seen = set()
    for name, programs in (("archive", sources(ROOT)), ("tools", tooling_sources(ROOT)),
                           ("batch_holdout", held_out()), ("project_holdout", project_holdout())):
        report[name] = transfer(programs, encoders, seen, timed=name.endswith("holdout"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
