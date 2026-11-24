import csv
import io
from itertools import groupby
from operator import itemgetter
from pathlib import Path

factor = int(input())


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as file:
        header, *rows = csv.reader(file)
    scaled = rows * factor
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(scaled)
    return len(scaled), buffer.getvalue().encode("utf-8")


def read_json(path):
    rows = r(path) * factor
    return len(rows), b(rows)


scores = [
    row
    for _, group in groupby(r("sort_scores.out"), key=itemgetter(1))
    for row in list(group) * factor
]

fixtures = [
    ("late_flights", read_csv("data/tweets.csv"),
     f"{int(Path('late_flights.out').read_bytes()) * factor}\n".encode()),
    ("goal_gap", read_csv("data/projects.csv"), Path("goal_gap.out").read_bytes()),
    ("word_counts", read_json("word_counts.in"), Path("word_counts.out").read_bytes()),
    ("sort_scores", read_json("sort_scores.in"), b(scores)),
]

wj({
    name: dict(records=count, bytes=len(data), input_sha256=h(data),
               golden_sha256=h(golden))
    for name, (count, data), golden in fixtures
})