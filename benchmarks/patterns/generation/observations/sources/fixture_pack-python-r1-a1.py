import csv
import io
from itertools import groupby
from operator import itemgetter
from pathlib import Path

factor = int(input())

def csv_input(path):
    with open(path, encoding='utf-8', newline='') as f:
        header, *rows = csv.reader(f)
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows * factor)
    return len(rows) * factor, out.getvalue().encode('utf-8')

result = {}
for task, path in (
    ('late_flights', 'data/tweets.csv'),
    ('goal_gap', 'data/projects.csv'),
    ('word_counts', 'word_counts.in'),
    ('sort_scores', 'sort_scores.in'),
):
    if path.endswith('.csv'):
        records, data = csv_input(path)
    else:
        rows = r(path) * factor
        records, data = len(rows), b(rows)

    golden_path = task + '.out'
    if task == 'sort_scores':
        golden = b([row for _, group in groupby(r(golden_path), itemgetter(1))
                    for row in list(group) * factor])
    else:
        golden = Path(golden_path).read_bytes()
        if task == 'late_flights':
            golden = f'{int(golden) * factor}\n'.encode()

    result[task] = dict(records=records, bytes=len(data),
                        input_sha256=h(data), golden_sha256=h(golden))

wj(result)