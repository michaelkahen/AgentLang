"""Measure spelling changes on accepted agent programs while holding their Python AST fixed."""

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sys
import tokenize

import tiktoken

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from agentlang import compile_source
from agentlang.compiler import _SHORT_HELPERS, _SHORT_STAGES, count_short_stages

STAGES = {long: short for short, long in _SHORT_STAGES.items()}
COMMANDS = dict(emit="p", jsonout="j")
HELPERS = {long: short for short, long in _SHORT_HELPERS.items()}
VARIANTS = ("authored", "long_spaced", "long_tight", "colon_long", "short_stages",
            "short_commands_and_stages", "all_short")
MAPS = {"stage": STAGES, "command": COMMANDS, "helper": HELPERS}


def lookup(table, word):
    if word in table:
        return word
    return next((long for long, short in table.items() if short == word), None)


@dataclass(frozen=True)
class Site:
    kind: str
    name: str
    start: int
    end: int
    short_as_written: bool

    def render(self, variant):
        if self.kind == "stage":
            if variant == "long_spaced":
                return " | " + self.name
            if variant == "long_tight":
                return "|" + self.name
            if variant == "colon_long":
                return ":" + self.name
            return ":" + STAGES[self.name]
        shorten = ((self.kind == "command" and variant in VARIANTS[-2:])
                   or (self.kind == "helper" and variant == "all_short"))
        return MAPS[self.kind][self.name] if shorten else self.name


def candidates(source):
    offsets = [0]
    for line in io.StringIO(source):
        offsets.append(offsets[-1] + len(line))
    def offset(position):
        return offsets[position[0] - 1] + position[1]

    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    prev = None
    depth = 0
    expression_start = True
    for index, tok in enumerate(tokens):
        if tok.type in {tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT}:
            continue
        if tok.type == tokenize.NAME:
            start, end = offset(tok.start), offset(tok.end)
            word = tok.string
            if depth == 0 and prev and prev.string in {"|", ":"} and prev.end[0] == tok.start[0]:
                long = lookup(STAGES, word)
                if long:
                    left = offset(prev.start)
                    line_start = offsets[prev.start[0] - 1]
                    # Only claim spaces between tokens, never a line's indentation.
                    if source[line_start:left].strip():
                        left -= len(source[line_start:left]) - len(source[line_start:left].rstrip(" \t"))
                    yield Site("stage", long, left, end, word == STAGES[long])
            if expression_start and (long := lookup(COMMANDS, word)):
                yield Site("command", long, start, end, word == COMMANDS[long])
            if tokens[index + 1].string == "(" and (long := lookup(HELPERS, word)):
                if not prev or prev.string not in {".", "def", "class"}:
                    yield Site("helper", long, start, end, word == HELPERS[long])
        if tok.type == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
        expression_start = tok.type == tokenize.NEWLINE or tok.string == ";"
        prev = tok


def bound_names(nodes):
    names = set()
    for top in nodes:
        for node in ast.walk(top):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name.split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name:
                names.add(node.name)
            elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
                names.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                names.add(node.rest)
    return names


def compiled_form(source):
    """Normalize only compiler-supplied unshadowed helper aliases, then compare ASTs."""
    program = ast.parse(compile_source(source))
    aliases = {short: long for long, short in HELPERS.items()}
    definitions = {}
    kept = []
    for node in program.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Name)
            and aliases.get(node.targets[0].id) == node.value.id):
            definitions[node.targets[0].id] = (node, node.value.id)
        else:
            kept.append(node)
    bindings = bound_names(kept)
    if definitions:
        safe = {short: long for short, (_, long) in definitions.items() if short not in bindings}
        # Keep any ambiguous alias assignment in its original position.
        ignored = {id(definitions[short][0]) for short in safe}
        program.body = [node for node in program.body if id(node) not in ignored]
        for node in ast.walk(program):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in safe:
                node.id = safe[node.id]
    return ast.dump(program), bindings


def measured_sites(source, reference, bindings):
    verified, skipped = [], Counter()
    for site in candidates(source):
        candidate = "all_short" if not site.short_as_written else "long_spaced"
        alternate = site.render(candidate)
        if source[site.start:site.end] == alternate:
            continue
        if site.kind == "helper" and HELPERS[site.name] in bindings:
            skipped["helper alias bound in source"] += 1
            continue
        probe = source[:site.start] + alternate + source[site.end:]
        try:
            equivalent = compiled_form(probe)[0] == reference
        except (ValueError, SyntaxError):
            equivalent = False
        if equivalent:
            verified.append(site)
        else:
            skipped["different AST or syntax"] += 1
    return sorted(verified, key=lambda item: item.start), skipped


def variant_source(source, sites, name):
    if name == "authored":
        return source
    parts = []
    end = 0
    for site in sites:
        if site.start < end:
            raise ValueError("overlapping edits")
        parts.extend([source[end:site.start], site.render(name)])
        end = site.end
    return "".join(parts) + source[end:]


def record(label, source, encoding):
    reference, bindings = compiled_form(source)
    sites, skipped = measured_sites(source, reference, bindings)
    metrics = {}
    for variant in VARIANTS:
        sample = variant_source(source, sites, variant)
        if compiled_form(sample)[0] != reference:
            raise ValueError(f"{label}: {variant} changed the compiled AST")
        metrics[variant] = dict(bytes=len(sample.encode()), characters=len(sample),
                                tokens=len(encoding.encode(sample, disallowed_special=())))
    by_class = Counter(site.kind for site in sites)
    short = Counter(site.kind for site in sites if site.short_as_written)
    if short["stage"] != count_short_stages(source):
        raise ValueError(f"{label}: site detector and compiler disagree on the one-letter stage count")
    return dict(source=label, sha256=hashlib.sha256(source.encode()).hexdigest(),
                eligible_sites=dict(by_class), authored_short_sites=dict(short),
                excluded_candidates=dict(skipped), metrics=metrics)


def sources():
    for path in sorted((ROOT / "examples").glob("*.ag")):
        yield "worked_examples", str(path.relative_to(ROOT)), path.read_bytes().decode()
    pilot = ROOT / "benchmarks/pilot/generation/trials.json"
    for trial in json.loads(pilot.read_bytes())["trials"]:
        if trial["arm"] == "compact" and trial["passed"]:
            label = f"{pilot.relative_to(ROOT)}#compact/{trial['task']}/round-{trial['round']}"
            yield "short_pilot", label, trial["source"]
    for group, subfolder in (("long_free_choice", "observations"), ("long_required", "required")):
        manifest = HERE / "generation" / subfolder / "results.json"
        run = json.loads(manifest.read_bytes())
        expected = {(task, repeat) for task in run["prompt_task_sha256"]
                    for repeat in range(1, run["rounds"] + 1)}
        observed = [(t["task"], t["round"]) for t in run["trials"] if t["arm"] == "compact"]
        if set(observed) != expected or len(observed) != len(expected):
            raise ValueError(f"incomplete or duplicate AgentLang trials in {manifest}")
        for trial in run["trials"]:
            if trial["arm"] != "compact" or not trial["passed"]:
                continue
            attempt = next(a for a in trial["attempts"] if a["passed"])
            path = Path(attempt["source_path"])
            if path.parts[0] != "benchmarks":
                path = manifest.parent / path
            else:
                path = ROOT / path
            label = f"{path.relative_to(ROOT)}#round-{trial['round']}"
            yield group, label, path.read_bytes().decode()


def summarize(rows):
    return dict(programs=len(rows), unique_sources=len({r["sha256"] for r in rows}),
                programs_with_eligible_sites=sum(bool(r["eligible_sites"]) for r in rows),
                programs_with_authored_short_sites=sum(bool(r["authored_short_sites"]) for r in rows),
                programs_with_eligible_stage=sum(bool(r["eligible_sites"].get("stage")) for r in rows),
                programs_with_authored_short_stage=sum(bool(r["authored_short_sites"].get("stage")) for r in rows),
                eligible_sites={kind: sum(r["eligible_sites"].get(kind, 0) for r in rows) for kind in MAPS},
                authored_short_sites={kind: sum(r["authored_short_sites"].get(kind, 0) for r in rows) for kind in MAPS},
                metrics={name: {key: sum(r["metrics"][name][key] for r in rows)
                                for key in ("bytes", "characters", "tokens")} for name in VARIANTS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "spellings.json")
    args = parser.parse_args()
    # Fail visibly if a grammar change makes the site detector stop finding aliases.
    probe = 'jsonout readjson() | where _ | list'
    tree, bindings = compiled_form(probe)
    verified, _ = measured_sites(probe, tree, bindings)
    if variant_source(probe, verified, "all_short") != "j r():w _:l":
        raise ValueError("compiler and spelling comparison disagree on short syntax")
    encoding = tiktoken.get_encoding("o200k_base")
    corpus = {}
    for group, label, source in sources():
        corpus.setdefault(group, []).append(record(label, source, encoding))
    summary = {group: summarize(rows) for group, rows in corpus.items()}
    report = dict(encoding=encoding.name, tiktoken=tiktoken.__version__,
                  scope="One accepted source per benchmark trial. Duplicates counted per trial. "
                        "Worked examples are a separate authored set. No model timing is measured here.",
                  method="All seven variants of every program have the same compiled Python AST after "
                         "normalizing unshadowed helper aliases injected by the compiler. "
                         "Only eligible syntax-site tokens and horizontal pipe padding change. "
                         "A short helper spelling is conservatively skipped if its name is bound anywhere.",
                  contrasts={"long_spaced to long_tight": "remove horizontal pipe padding",
                             "long_tight to colon_long": "switch delimiter from | to :",
                             "colon_long to short_stages": "shorten stage identifiers",
                             "short_stages to short_commands_and_stages": "shorten output command names",
                             "short_commands_and_stages to all_short": "shorten I/O helper names"},
                  variants=list(VARIANTS), summary=summary, programs=corpus)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for label, group in summary.items():
        print(label, group["programs"], {v: group["metrics"][v]["tokens"] for v in VARIANTS})


if __name__ == "__main__":
    main()
