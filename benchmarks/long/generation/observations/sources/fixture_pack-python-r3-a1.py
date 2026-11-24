import csv
import hashlib
import io
import json
from itertools import groupby
from operator import itemgetter
from pathlib import Path

factor = int(input())


def json_bytes(value):
    return (json.dumps(value) + "\n").encode("utf-8")


def load_json(path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


def scale_csv(path):
    with open(path, encoding="utf-8", newline="") as source:
        header, *rows = csv.reader(source)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for _ in range(factor):
        writer.writerows(rows)
    return len(rows) * factor, buffer.getvalue().encode("utf-8")


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def summarize(records, data, golden):
    return {
        "records": records,
        "bytes": len(data),
        "input_sha256": checksum(data),
        "golden_sha256": checksum(golden),
    }


results = {}
for task, path in (
    ("late_flights", "data/tweets.csv"),
    ("goal_gap", "data/projects.csv"),
    ("word_counts", "word_counts.in"),
    ("sort_scores", "sort_scores.in"),
):
    if path.endswith(".csv"):
        records, data = scale_csv(path)
    else:
        rows = load_json(path)
        records = len(rows) * factor
        data = json_bytes(rows * factor)

    golden_path = Path(task + ".out")
    if task == "late_flights":
        golden = f"{int(golden_path.read_bytes()) * factor}\n".encode("utf-8")
    elif task == "sort_scores":
        sorted_rows = []
        for _, group in groupby(load_json(golden_path), key=itemgetter(1)):
            sorted_rows.extend(list(group) * factor)
        golden = json_bytes(sorted_rows)
    else:
        golden = golden_path.read_bytes()

    results[task] = summarize(records, data, golden)

print(json.dumps(results))