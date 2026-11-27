"""Compare record and lookup spellings on executable pairs and frozen programs."""

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

import tiktoken

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from agentlang import compile_source
from benchmarks.scripting.simulation_archive import BASELINE, inspect, previous_source, sources, tooling_sources
from benchmarks.scripting.simulation_cases import FAMILIES, cases


GETS = ("method", "question", "dollar_question", "question_dot")
RECORDS = ("literal", "keywords", "mixed")


def execute(tree, fixtures):
    code = compile(tree, "<simulation>", "exec")
    outputs = []
    for rows in fixtures:
        scope = {"rows": rows}
        exec(code, scope)
        outputs.append(scope["result"])
    return outputs


def evaluate(case, encodings):
    renderings = {(g, r): case.source(g, r) for g in GETS for r in RECORDS}
    cached = {}
    reference_tree = None
    fixtures = case.inputs()
    for (g, r), source in renderings.items():
        if g not in ("method", "question"):
            continue  # spelling prototypes only
        if source not in cached:
            tree = ast.parse(compile_source(source))
            cached[source] = ast.dump(tree), execute(tree, fixtures)
        structure, outputs = cached[source]
        if reference_tree is None:
            reference_tree, reference_outputs = structure, outputs
        if r != "keywords" and structure != reference_tree:
            raise AssertionError(f"nonidentical AST for {case}, {g}/{r}")
        if outputs != reference_outputs:
            raise AssertionError(f"outputs differ for {case}, {g}/{r}")
    tokens = {}
    for enc in encodings:
        by_source = {s: len(enc.encode_ordinary(s)) for s in set(renderings.values())}
        tokens[enc.name] = {k: by_source[v] for k, v in renderings.items()}
    return renderings["method", "literal"], tokens, len(cached) * len(fixtures)


def study(count, seed, encodings):
    per_family = defaultdict(lambda: defaultdict(Counter))
    matrix, pairwise = defaultdict(Counter), defaultdict(Counter)
    fingerprints = set()
    fixture_runs = 0
    digest = hashlib.sha256()
    for case in cases(count, seed):
        src, scores, executions = evaluate(case, encodings)
        fingerprint = hashlib.sha256(src.encode()).digest()
        if fingerprint in fingerprints:
            raise AssertionError(f"duplicate generated source for {case}")
        fingerprints.add(fingerprint)
        digest.update(fingerprint)
        fixture_runs += executions
        for encoding, grid in scores.items():
            matrix[encoding].update({f"{g}/{r}": n for (g, r), n in grid.items()})
            # Each encoder gets its own strongest pre-existing literal / dict(...)
            # control per script. Keep old d{a,b} for records already expressible.
            baseline = min(grid["method", "literal"], grid["method", "keywords"])
            methods = dict(current=baseline, lookup=min(grid["question", "literal"], grid["question", "keywords"]),
                           record=grid["method", "mixed"], combined=grid["question", "mixed"])
            per_family[case.family][encoding].update(methods)
            for m, n in methods.items():
                if m != "current":
                    direction = "shorter" if n < baseline else "longer" if n > baseline else "equal"
                    pairwise[encoding][f"{m}/{direction}"] += 1
    return dict(per_family=count, seed=seed, distinct_scripts=len(fingerprints),
                baseline_corpus_sha256=digest.hexdigest(), fixture_executions=fixture_runs,
                proposed_spelling_renderings=len(fingerprints) * len(GETS) * len(RECORDS),
                tokens={e.name: dict(sum((p[e.name] for p in per_family.values()), Counter()))
                        for e in encodings}, by_family=per_family, compared_with_current=pairwise,
                spelling_grid=matrix)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-family", type=int, default=512)
    parser.add_argument("--seed", type=int, default=20261127)
    parser.add_argument("--output", type=Path, default=HERE / "results" / "tokens.json")
    args = parser.parse_args()
    encodings = [tiktoken.get_encoding(name) for name in ("o200k_base", "cl100k_base")]
    result = dict(tiktoken=tiktoken.__version__, python=sys.version.split()[0],
                  families=list(FAMILIES), generated=study(args.per_family, args.seed, encodings),
                  archive=inspect(sources(ROOT), encodings), tooling=inspect(tooling_sources(ROOT), encodings),
                  baseline_revision=BASELINE,
                  reference_card={e.name: {
                      "before": len(e.encode_ordinary(previous_source(ROOT, "docs/agent-reference.txt"))),
                      "after": len(e.encode_ordinary((ROOT / "docs/agent-reference.txt").read_text()))
                  } for e in encodings})
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({group: result[group]["tokens"] for group in ("generated", "archive", "tooling")}, indent=2))


if __name__ == "__main__":
    main()
