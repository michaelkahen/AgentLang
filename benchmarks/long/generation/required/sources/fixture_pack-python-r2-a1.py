import csv
import hashlib
import io
import itertools
import json
import sys
from pathlib import Path

factor = int(sys.stdin.readline())

def json_bytes(value):
    return (json.dumps(value) + "\n").encode("utf-8")

def csv_input(path):
    with open(path, encoding="utf-8", newline="") as source:
        header, *rows = csv.reader(source)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows * factor)
    return len(rows) * factor, output.getvalue().encode("utf-8")

result = {}
for task, source in [
    ("late_flights", "data/tweets.csv"),
    ("goal_gap", "data/projects.csv"),
    ("word_counts", "word_counts.in"),
    ("sort_scores", "sort_scores.in"),
]:
    if source.endswith(".csv"):
        records, data = csv_input(source)
    else:
        rows = json.loads(Path(source).read_text(encoding="utf-8")) * factor
        records, data = len(rows), json_bytes(rows)

    golden = Path(task + ".out").read_bytes()
    if task == "late_flights":
        golden = f"{int(golden) * factor}\n".encode("utf-8")
    elif task == "sort_scores":
        groups = itertools.groupby(json.loads(golden), key=lambda pair: pair[1])
        scaled = []
        for _, group in groups:
            scaled.extend(list(group) * factor)
        golden = json_bytes(scaled)

    result[task] = {
        "records": records,
        "bytes": len(data),
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "golden_sha256": hashlib.sha256(golden).hexdigest(),
    }

print(json.dumps(result))