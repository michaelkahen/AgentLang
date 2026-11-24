import csv
import io
from itertools import groupby
from pathlib import Path

factor = int(input())
result = {}

for task, source in zip(
    ("late_flights", "goal_gap", "word_counts", "sort_scores"),
    ("data/tweets.csv", "data/projects.csv", "word_counts.in", "sort_scores.in"),
):
    if source.endswith(".csv"):
        with open(source, encoding="utf-8", newline="") as file:
            rows = csv.reader(file)
            header = next(rows)
            records = list(rows)
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(header)
        for _ in range(factor):
            writer.writerows(records)
        data = output.getvalue().encode("utf-8")
    else:
        records = r(source)
        data = b(records * factor)

    path = Path(task + ".out")
    if task == "late_flights":
        golden = f"{int(path.read_bytes()) * factor}\n".encode()
    elif task == "sort_scores":
        scaled = []
        for _, group in groupby(r(str(path)), key=lambda pair: pair[1]):
            scaled.extend(list(group) * factor)
        golden = b(scaled)
    else:
        golden = path.read_bytes()

    result[task] = {
        "records": len(records) * factor,
        "bytes": len(data),
        "input_sha256": h(data),
        "golden_sha256": h(golden),
    }

wj(result)