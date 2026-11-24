"""Offline workload contracts, deterministic inputs and independent expected outputs."""

import csv
import hashlib
import io
import json
import math
import random
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

PROMPTS = {
    "movie_credits": """Build a science-fiction film crew report from two UTF-8 CSV files in the working directory. movies.csv has id,genres and credits.csv has id,crew. Treat movie IDs as literal nonempty strings. For each genres/crew cell try JSON, then Python literal syntax (never eval); empty, malformed and non-list values represent an empty list. Ignore non-dict list elements. Collect unique movie IDs having any genre dict with name exactly 'Science Fiction' or 'Sci-Fi'. A qualifying row is enough even if another movies.csv row with the same ID has no matching genre. Join credits by movie ID. For each eligible credit entry, require a crew dict with a positive integer id (exclude bool), regardless of name. Count every occurrence, including repeat jobs in one film and repeated credits rows; separately count distinct films per person. Print one JSON object: {"films": number of qualifying movie IDs, "credited_films": number of those with at least one valid crew entry, "appearances": total valid occurrences, "leaders": up to 5 objects {"id": integer, "credits": count, "movies": distinct film count}}. Sort leaders by credits descending, then movies descending, then numeric id ascending. Use empty counts/list if no match.""",
    "knn_grid": """Tune a K-nearest-neighbor classifier using only the Python standard library. Read samples.csv in cwd (UTF-8 header fold,x,y,label). Integer folds 0,1,2 are training folds; fold test is a labeled holdout. Coordinates are integers, labels nonempty strings, all rows valid. Preserve original file order as the distance tie-break. For each k in [1,3,5], then metric in ['euclidean','manhattan'], then weights in ['uniform','distance'] (this exact nested order), predict each training row using all training rows from the other folds. All training pools have at least five rows. Euclidean is ordinary (square-root) distance. Sort neighbors by (distance,input order), use first k. For uniform voting each selected neighbor contributes one vote. For distance voting, if any selected neighbor is at distance zero, count only selected zero-distance neighbors with one vote each; otherwise use weights 1/distance. Largest score wins, with lexicographically smallest label breaking exactly equal scores. Use raw coordinates; no scaling. Print one JSON object {"grid": [{"k": k,"metric": str,"weights": str,"correct": number of correctly classified training rows}, ...] in grid order, "best": zero-based index of the first grid entry with highest correct count, "predictions": predicted holdout labels in file order using that best configuration and all training rows, "test_correct": number of correct holdout predictions}. A holdout may be empty.""",
    "fixture_pack": """Produce checksums for a scaled test-fixture pack using only Python's standard library. Read a positive integer repeat factor from stdin. The following UTF-8 seed files exist in cwd: data/tweets.csv, data/projects.csv (each has a header), word_counts.in (JSON string array), sort_scores.in (JSON [name,score] pairs), and matching golden files late_flights.out (integer count), goal_gap.out and word_counts.out (single line UTF-8 bytes ending LF), sort_scores.out (JSON pairs already stable-sorted ascending by score). Repeat the entire input record sequence factor times, never repeating the CSV header. Encode CSV from parsed cells via csv.writer with default excel dialect except lineterminator='\\n', encoding UTF-8, preserving embedded newlines; encode JSON via Python json.dumps defaults followed by one LF. Scale goldens: late_flights is its original count times factor plus LF; goal_gap and word_counts bytes are preserved exactly; for sort_scores repeat each consecutive equal-score group of the sorted golden sequence factor times, preserving order inside each group, then JSON-encode as above. Print one JSON object keyed by late_flights, goal_gap, word_counts, sort_scores. For each task give {"records": scaled input record count (excludes CSV header), "bytes": scaled input byte length, "input_sha256": lower-case hex SHA-256 of scaled input bytes, "golden_sha256": lower-case hex SHA-256 of scaled golden bytes}. Files may be treated in memory; no output files are required. Pick sources in the order listed above for their matching tasks.""",
}
TASKS = tuple(PROMPTS)

def matches(stdout, expected):
    """Check a single JSON value, preserving numeric/boolean types and unique keys."""
    def object_from_pairs(pairs):
        result = dict(pairs)
        if len(pairs) != len(result):
            raise ValueError("duplicate JSON key")
        return result

    def reject_constant(value):
        raise ValueError(f"invalid JSON constant {value}")

    def equal(actual, reference):
        if type(actual) is not type(reference):
            return False
        if isinstance(reference, dict):
            return (actual.keys() == reference.keys()
                    and all(equal(actual[k], v) for k, v in reference.items()))
        if isinstance(reference, list):
            return (len(actual) == len(reference)
                    and all(equal(a, b) for a, b in zip(actual, reference)))
        return actual == reference

    try:
        value = json.loads(stdout, object_pairs_hook=object_from_pairs, parse_constant=reject_constant)
        return equal(value, expected)
    except (ValueError, RecursionError):
        return False


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    return stream.getvalue().encode()


def json_bytes(value):
    return (json.dumps(value) + "\n").encode()


def movie_case(variant, folder):
    # Each source cell is paired with its hand-annotated meaning. The oracle
    # builds its relational counts from these annotations, without a parser.
    movies = [
        ("001", '[{"name":"Sci-Fi"}]', True),
        ("002", "[{'name': 'Science Fiction'}, {'name':'Drama'}]", True),
        ("003", '"Sci-Fi"', False),
        ("004", "[1, null, {}, {\"name\": \"Science Fiction\"}]", True),
        ("005", "not valid json", False),
        ("001", '[{"name":"Mystery"}]', False),
        ("006", '[{"name":"Sci-Fi"}]', True),
        ("007", '[{"name":"Sci-Fi"}]', True),
        ("", '[{"name":"Sci-Fi"}]', False),
        ("008", '[{"name":"Sci-Fi"}]', True),
    ]
    crews = [
        ("001", '[{"id":9},{"id":9},{"id":2}]', [9, 9, 2]),
        ("001", "[{'name': \"O'Brien\", 'id': 12}]", [12]),
        ("002", '[{"id":2},{"id":2},{"id":true},{"id":7}]', [2, 2, 7]),
        ("004", '[{},42,{"id":0},{"id":"12"},{"id":12},{"id":3}]', [12, 3]),
        ("006", 'malformed', []),
        ("004", '[{"id":11},{"id":9},{"id":99},{"id":-3},{"id":2.0}]', [11, 9, 99]),
        ("003", '[{"id":900}]', [900]),
        ("009", '[{"id":999}]', [999]),
        ("", '[{"id":1000}]', [1000]),
        ("008", '{"id":4}', []),
    ]
    if variant == "edges":
        movies = [("a", "[]", False), ("", "[{'name':'Sci-Fi'}]", False),
                  ("b", '[{"name":"science fiction"}]', False), ("x", "{}", False)]
        crews = [("a", '[{"id":6}]', [6]), ("", '[{"id":99}]', [99])]
    if variant == "audit":
        movies = [("17", '[{"name":"Sci-Fi"}]', True), ("017", '[{"name":"Drama"}]', False),
                  ("q", "[{'name':'Science Fiction'}]", True),
                  ("r", '[{"name":"Sci-Fi"}]', True), ("s", '[{"name":"Sci-Fi"}]', True)]
        crews = [("17", '[{"id":1},{"id":1},{"id":4},{"id":7}]', [1, 1, 4, 7]),
                 ("q", "[{'id':3}, {'id':4}, {'id': True}, {'id':7}]", [3, 4, 7]),
                 ("r", '[{"id":3}]', [3]), ("017", '[{"id":901}]', [901]),
                 ("s", '[{"id":"5"}]', [])]
    copies = 800 if variant == "profile" else 1
    movie_rows, credit_rows, wanted, memberships = [], [], set(), []
    for n in range(copies):
        prefix = f"{n}:" if copies > 1 else ""
        for key, text, selected in movies:
            movie_id = prefix + key if key else ""
            movie_rows.append((movie_id, text))
            if selected:
                wanted.add(movie_id)
        for key, text, people in crews:
            movie_id = prefix + key if key else ""
            credit_rows.append((movie_id, text))
            memberships.extend((movie_id, person) for person in people)

    (folder / "movies.csv").write_bytes(csv_bytes([("id", "genres"), *movie_rows]))
    (folder / "credits.csv").write_bytes(csv_bytes([("id", "crew"), *credit_rows]))
    joined = [(movie, crew) for movie, crew in memberships if movie in wanted]
    counts = Counter(person for _, person in joined)
    film_counts = Counter(person for _, person in set(joined))
    people = sorted(counts, key=lambda person: (-counts[person], -film_counts[person], person))
    result = {
        "films": len(wanted), "credited_films": len({movie for movie, _ in joined}),
        "appearances": len(joined),
        "leaders": [{"id": p, "credits": counts[p], "movies": film_counts[p]} for p in people[:5]],
    }
    return {"stdin": b"", "expected": result,
            "dimensions": {"movies_rows": len(movie_rows), "credits_rows": len(credit_rows)}}


def knn_case(variant, folder):
    # Independent oracle precomputes each held-out row's ordered neighbors once
    # per metric, then evaluates the whole parameter grid against those ranks.
    rng = random.Random({"base": 71, "edges": 116, "profile": 993, "audit": 809}[variant])
    train_size, test_size = {"base": (21, 6), "edges": (15, 0), "profile": (210, 30),
                             "audit": (18, 4)}[variant]
    labels = ("amber", "blue", "cyan")
    rows = []
    for index in range(train_size + test_size):
        x, y = rng.randrange(12), rng.randrange(12)
        if index % 7 < 2:
            x, y = 3, 3
        label = labels[(int(x > 6) + int(y > 7) + (index % 5 == 3)) % 3]
        rows.append((index % 3 if index < train_size else "test", x, y, label))
    if variant == "audit":
        # After excluding a fold the two eligible center labels disagree.
        # The additional nonzero neighbors at k=5 are all labeled z.
        rows = [(fold, x, 0, ("z", "b", "a")[fold] if x == 0 else "z")
                for fold in range(3) for x in range(6)]
        rows += [("test", x, y, label) for x, y, label in (
            (0, 0, "a"), (1, 0, "b"), (4, 0, "z"), (8, 0, "z"))]
    (folder / "samples.csv").write_bytes(csv_bytes([("fold", "x", "y", "label"), *rows]))
    grid = list(product((1, 3, 5), ("euclidean", "manhattan"), ("uniform", "distance")))
    all_predictions = [[] for _ in grid]
    for fold, x, y, _ in rows:
        candidates = [(abs(x - a), abs(y - b), i, tag)
                      for i, (source_fold, a, b, tag) in enumerate(rows[:train_size])
                      if source_fold != fold]
        ordered = {
            "euclidean": sorted((math.sqrt(dx * dx + dy * dy), i, tag)
                                for dx, dy, i, tag in candidates)[:5],
            "manhattan": sorted((dx + dy, i, tag) for dx, dy, i, tag in candidates)[:5],
        }
        for predictions, (k, metric, weights) in zip(all_predictions, grid):
            votes = defaultdict(float)
            neighbors = ordered[metric][:k]
            for distance, _, label in neighbors:
                if weights == "uniform":
                    votes[label] += 1
                elif not neighbors[0][0]:
                    if distance == 0:
                        votes[label] += 1
                else:
                    votes[label] += 1 / distance
            predictions.append(min(votes, key=lambda tag: (-votes[tag], tag)))

    expected_grid = []
    for (k, metric, weights), preds in zip(grid, all_predictions):
        correct = sum(pred == row[3] for pred, row in zip(preds, rows[:train_size]))
        expected_grid.append(dict(k=k, metric=metric, weights=weights, correct=correct))
    best = max(range(len(grid)), key=lambda index: expected_grid[index]["correct"])
    holdout = all_predictions[best][train_size:]
    result = {"grid": expected_grid, "best": best, "predictions": holdout,
              "test_correct": sum(pred == row[3] for pred, row in zip(holdout, rows[train_size:]))}
    return {"stdin": b"", "expected": result, "dimensions": {"train_rows": train_size, "test_rows": test_size}}


def pack_case(variant, folder):
    # Calculate expected CSV hashes by repeating canonical seed byte segments;
    # derive the sorted golden independently by stable-sorting the entire input.
    factor = {"base": 3, "edges": 1, "profile": 64, "audit": 7}[variant]
    width = 1200 if variant == "profile" else 5
    data = folder / "data"
    data.mkdir(exist_ok=True)
    scores = [[["Zoë", "A", "é", 'a"b', "A"][i % 5], (6 * i) % 9 - 4] for i in range(width)]
    words = [["word", "", "é\tword", 'hello,\nworld', "word"][i % 5] for i in range(width)]
    tweets = [("US Airways", "negative", "Late Flight") if i % 2 == 0 else
              ("Other", "positive", 'a "quoted",\ntwo-line note') for i in range(width)]
    projects = [("failed", "100.50"), ("successful", "0.25")]
    if variant == "edges":
        scores, words, tweets, projects = [], ["é"], [], []
    if variant == "audit":
        scores = [["first", -2], ["β", 1], ["q", -2], ["last", -2], ["a", 1]]
        words = ["word", "two\tlines", "comma,quote\""]
        tweets = [("Other", "negative", "line\none"), ("US Airways", "negative", "Late Flight")]
        projects.append(("stopped", "-100"))
    (folder / "word_counts.in").write_bytes(json_bytes(words))
    (folder / "sort_scores.in").write_bytes(json_bytes(scores))
    inputs = {"word_counts": (len(words) * factor, json_bytes(words * factor)),
              "sort_scores": (len(scores) * factor, json_bytes(scores * factor))}
    for task, filename, header, records in [
        ("late_flights", "tweets.csv", ("airline", "airline_sentiment", "negativereason"), tweets),
        ("goal_gap", "projects.csv", ("state", "usd_goal_real"), projects),
    ]:
        prefix, body = csv_bytes([header]), csv_bytes(records)
        (data / filename).write_bytes(prefix + body)
        inputs[task] = (len(records) * factor, prefix + body * factor)
    count = sum(row == ("US Airways", "negative", "Late Flight") for row in tweets)
    # The source task preserves these two existing golden files byte-for-byte.
    goal = b"100.25\n" if projects else b"undefined\n"
    word = ("word" if variant != "edges" else "é").encode() + b"\n"
    small_goldens = {"late_flights": f"{count}\n".encode(), "goal_gap": goal, "word_counts": word,
                     "sort_scores": json_bytes(sorted(scores, key=lambda pair: pair[1]))}
    for task, value in small_goldens.items():
        (folder / f"{task}.out").write_bytes(value)
    expanded = dict(small_goldens)
    expanded["late_flights"] = f"{count * factor}\n".encode()
    expanded["sort_scores"] = json_bytes(sorted(scores * factor, key=lambda pair: pair[1]))
    expected = {
        task: {"records": records, "bytes": len(content),
               "input_sha256": hashlib.sha256(content).hexdigest(),
               "golden_sha256": hashlib.sha256(expanded[task]).hexdigest()}
        for task, (records, content) in inputs.items()
    }
    return {"stdin": f"{factor}\n".encode(), "expected": expected,
            "dimensions": {"factor": factor, "expanded_records": sum(n for n, _ in inputs.values()),
                           "expanded_input_bytes": sum(len(b) for _, b in inputs.values())}}


def prepare(task, variant, directory):
    """Create inputs, return stdin bytes, JSON reference result and dimensions."""
    if variant not in {"base", "edges", "profile", "audit"}:
        raise ValueError(f"unknown fixture variant {variant!r}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return {"movie_credits": movie_case, "knn_grid": knn_case, "fixture_pack": pack_case}[task](variant, directory)
