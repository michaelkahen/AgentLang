from fractions import Fraction
from math import isqrt

rows = [(r["fold"], int(r["x"]), int(r["y"]), r["label"])
        for r in csvrows("samples.csv")]
train = [r for r in rows if r[0] != "test"]
test = [r for r in rows if r[0] == "test"]
metrics = ("euclidean", "manhattan")
grid = [{"k": k, "metric": metric, "weights": weights, "correct": 0}
        for k in (1, 3, 5) for metric in metrics
        for weights in ("uniform", "distance")]


def neighbors(row, pool, metric):
    _, x, y, _ = row
    ranked = []
    for _, a, b, label in pool:
        dx, dy = x - a, y - b
        distance = dx * dx + dy * dy if metric == "euclidean" else abs(dx) + abs(dy)
        ranked.append((distance, label))
    ranked.sort(key=lambda item: item[0])
    return ranked[:5]


def greater(left, right, metric):
    if metric == "manhattan":
        return sum(Fraction(1, d) for d in left) > sum(Fraction(1, d) for d in right)

    # Terms share a square class exactly when the product is a square.
    groups = {}
    terms = [(d, 1) for d in left] + [(d, -1) for d in right]
    for d, sign in terms:
        for base in groups:
            root = isqrt(d * base)
            if root * root == d * base:
                groups[base] += Fraction(sign * root, d)
                break
        else:
            groups[d] = Fraction(sign)
    if not any(groups.values()):
        return False

    # Bound the nonzero difference with scaled integer square roots.
    bits = 32
    while True:
        scale = 1 << (2 * bits)
        total = sum(sign * isqrt(scale // d) for d, sign in terms)
        if total >= len(right):
            return True
        if total <= -len(left):
            return False
        bits *= 2


def predict(ranked, k, metric, weights):
    selected = ranked[:k]
    counts = weights == "uniform" or selected[0][0] == 0
    votes = {}
    for distance, label in selected:
        if weights == "uniform" or not counts or distance == 0:
            votes.setdefault(label, []).append(distance)
    if counts:
        return min(votes, key=lambda label: (-len(votes[label]), label))
    labels = iter(sorted(votes))
    winner = next(labels)
    for label in labels:
        if greater(votes[label], votes[winner], metric):
            winner = label
    return winner


pools = {fold: [row for row in train if row[0] != fold]
         for fold in ("0", "1", "2")}
for row in train:
    ranked = {metric: neighbors(row, pools[row[0]], metric) for metric in metrics}
    for entry in grid:
        metric = entry["metric"]
        entry["correct"] += predict(ranked[metric], entry["k"], metric,
                                    entry["weights"]) == row[3]

best = max(range(len(grid)), key=lambda index: grid[index]["correct"])
choice = grid[best]
metric = choice["metric"]
predictions = [predict(neighbors(row, train, metric), choice["k"], metric,
                       choice["weights"]) for row in test]
writejson({"grid": grid, "best": best, "predictions": predictions,
           "test_correct": sum(label == row[3] for label, row in zip(predictions, test))})