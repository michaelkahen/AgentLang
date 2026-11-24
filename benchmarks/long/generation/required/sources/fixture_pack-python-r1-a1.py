import csv
import hashlib
import io
import itertools
import json
import sys
from pathlib import Path

factor = int(sys.stdin.read())

def json_bytes(value):
    return (json.dumps(value) + "\n").encode("utf-8")

result = {}
for task, source in (
    ("late_flights", "data/tweets.csv"),
    ("goal_gap", "data/projects.csv"),
    ("word_counts", "word_counts.in"),
    ("sort_scores", "sort_scores.in"),
):
    with open(source, encoding="utf-8", newline="") as seed:
        if source.endswith(".csv"):
            reader = csv.reader(seed)
            header = next(reader)
            records = list(reader)
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerow(header)
            for _ in range(factor):
                writer.writerows(records)
            input_bytes = buffer.getvalue().encode("utf-8")
        else:
            records = json.load(seed)
            input_bytes = json_bytes(records * factor)

    golden = Path(task + ".out").read_bytes()
    if task == "late_flights":
        golden = f"{int(golden) * factor}\n".encode("utf-8")
    elif task == "sort_scores":
        scaled = []
        for _, group in itertools.groupby(json.loads(golden), key=lambda pair: pair[1]):
            scaled.extend(list(group) * factor)
        golden = json_bytes(scaled)

    result[task] = {
        "records": len(records) * factor,
        "bytes": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "golden_sha256": hashlib.sha256(golden).hexdigest(),
    }

print(json.dumps(result))