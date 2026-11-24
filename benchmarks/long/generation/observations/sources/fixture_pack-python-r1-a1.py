import csv
import hashlib
import io
import json
import sys
from itertools import groupby
from pathlib import Path


def encode_json(value):
    return (json.dumps(value) + "\n").encode("utf-8")


def scale_csv(path, factor):
    with open(path, encoding="utf-8", newline="") as source:
        header, *rows = csv.reader(source)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    for _ in range(factor):
        writer.writerows(rows)
    return len(rows) * factor, output.getvalue().encode("utf-8")


def scale_json(path, factor):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return len(rows) * factor, encode_json(rows * factor)


def main():
    factor = int(sys.stdin.read())
    late_count = int(Path("late_flights.out").read_bytes())
    scores = json.loads(Path("sort_scores.out").read_text(encoding="utf-8"))
    sorted_scores = []
    for _, group in groupby(scores, key=lambda pair: pair[1]):
        sorted_scores.extend(list(group) * factor)

    tasks = (
        ("late_flights", scale_csv("data/tweets.csv", factor),
         f"{late_count * factor}\n".encode("utf-8")),
        ("goal_gap", scale_csv("data/projects.csv", factor),
         Path("goal_gap.out").read_bytes()),
        ("word_counts", scale_json("word_counts.in", factor),
         Path("word_counts.out").read_bytes()),
        ("sort_scores", scale_json("sort_scores.in", factor),
         encode_json(sorted_scores)),
    )
    print(json.dumps({
        task: {
            "records": count,
            "bytes": len(data),
            "input_sha256": hashlib.sha256(data).hexdigest(),
            "golden_sha256": hashlib.sha256(golden).hexdigest(),
        }
        for task, (count, data), golden in tasks
    }))


if __name__ == "__main__":
    main()