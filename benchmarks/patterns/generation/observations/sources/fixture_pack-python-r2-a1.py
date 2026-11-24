import csv
import hashlib
import io
import json
from itertools import groupby
from operator import itemgetter
from pathlib import Path

factor = int(input())


def encode_json(value):
    return (json.dumps(value) + '\n').encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


result = {}
for task, source in (
    ('late_flights', 'data/tweets.csv'),
    ('goal_gap', 'data/projects.csv'),
    ('word_counts', 'word_counts.in'),
    ('sort_scores', 'sort_scores.in'),
):
    if source.endswith('.csv'):
        with open(source, encoding='utf-8', newline='') as f:
            header, *rows = csv.reader(f)
        buf = io.StringIO(newline='')
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(header)
        writer.writerows(rows * factor)
        data = buf.getvalue().encode('utf-8')
    else:
        rows = read_json(source)
        data = encode_json(rows * factor)

    golden = Path(task + '.out').read_bytes()
    if task == 'late_flights':
        golden = encode_json(int(golden) * factor)
    elif task == 'sort_scores':
        ordered = []
        for _, group in groupby(json.loads(golden.decode('utf-8')), itemgetter(1)):
            ordered.extend(list(group) * factor)
        golden = encode_json(ordered)

    result[task] = {
        'records': len(rows) * factor,
        'bytes': len(data),
        'input_sha256': hashlib.sha256(data).hexdigest(),
        'golden_sha256': hashlib.sha256(golden).hexdigest(),
    }

print(json.dumps(result))