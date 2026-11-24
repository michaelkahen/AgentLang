import csv
import hashlib
import io
import json
import sys
from itertools import groupby
from pathlib import Path


def json_bytes(value):
    return (json.dumps(value) + "\n").encode("utf-8")


def checksum(records, input_bytes, golden_bytes):
    return {
        "records": records,
        "bytes": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "golden_sha256": hashlib.sha256(golden_bytes).hexdigest(),
    }


def scale_csv(path, factor):
    with open(path, encoding="utf-8", newline="") as source:
        reader = csv.reader(source)
        header = next(reader)
        rows = list(reader)

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    for _ in range(factor):
        writer.writerows(rows)
    return len(rows) * factor, output.getvalue().encode("utf-8")


def main():
    factor = int(sys.stdin.read())
    result = {}

    for task, path in (
        ("late_flights", "data/tweets.csv"),
        ("goal_gap", "data/projects.csv"),
    ):
        records, input_bytes = scale_csv(path, factor)
        golden = Path(task + ".out").read_bytes()
        if task == "late_flights":
            golden = f"{int(golden) * factor}\n".encode("utf-8")
        result[task] = checksum(records, input_bytes, golden)

    for task in ("word_counts", "sort_scores"):
        rows = json.loads(Path(task + ".in").read_text(encoding="utf-8"))
        golden = Path(task + ".out").read_bytes()
        if task == "sort_scores":
            scaled = []
            for _, group in groupby(json.loads(golden), key=lambda pair: pair[1]):
                scaled.extend(list(group) * factor)
            golden = json_bytes(scaled)
        result[task] = checksum(len(rows) * factor, json_bytes(rows * factor), golden)

    print(json.dumps(result))


if __name__ == "__main__":
    main()