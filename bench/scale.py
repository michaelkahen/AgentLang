"""Build larger, deterministic copies of the four bundled exercise fixtures."""

import csv
import hashlib
import json
import shutil
from itertools import groupby


FILES = {
    "late_flights": "data/tweets.csv",
    "goal_gap": "data/projects.csv",
    "word_counts": "word_counts.in",
    "sort_scores": "sort_scores.in",
}


def prepare_examples(base, destination, factor, names):
    """Return the working directory and dimensions of each workload's input."""
    examples = base
    if factor > 1:
        unknown = set(names) - FILES.keys()
        if unknown:
            raise ValueError(f"Scaling is undefined for {', '.join(sorted(unknown))}")
        examples = destination
        shutil.copytree(base, examples)

    dimensions = {}
    for name in names:
        if name not in FILES:
            continue
        relpath = FILES[name]
        source, target = base / relpath, examples / relpath
        if source.suffix == ".csv":
            with source.open(newline="", encoding="utf-8") as file:
                header, *records = csv.reader(file)
            if factor > 1:
                with target.open("w", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file, lineterminator="\n")
                    writer.writerow(header)
                    for _ in range(factor):
                        writer.writerows(records)
        else:
            records = json.loads(source.read_text(encoding="utf-8"))
            if factor > 1:
                target.write_text(json.dumps(records * factor) + "\n", encoding="utf-8")
        dimensions[name] = {
            "input": relpath,
            "records": len(records) * factor,
            "input_bytes": target.stat().st_size,
            "input_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        if factor == 1:
            continue

        # Repeating the full fixture preserves word frequencies' ordering and both group means.
        # Count multiplies. A stable ascending sort repeats each tied group in original order.
        golden = examples / f"{name}.out"
        if name == "late_flights":
            count = int(golden.read_text(encoding="utf-8"))
            golden.write_text(f"{count * factor}\n", encoding="utf-8")
        elif name == "sort_scores":
            sorted_seed = json.loads(golden.read_text(encoding="utf-8"))
            expected = []
            for _, ties in groupby(sorted_seed, key=lambda pair: pair[1]):
                expected.extend(list(ties) * factor)
            golden.write_text(json.dumps(expected) + "\n", encoding="utf-8")
    return examples, dimensions
