from collections import defaultdict
from math import sqrt

train, test = [], []
for row in c("samples.csv"):
    sample = row["fold"], int(row["x"]), int(row["y"]), row["label"]
    (test if sample[0] == "test" else train).append(sample)

def neighbors(sample, pool, metric):
    _, x, y, _ = sample
    ranked = []
    for _, a, b, label in pool:
        dx, dy = x - a, y - b
        d = sqrt(dx * dx + dy * dy) if metric == "euclidean" else abs(dx) + abs(dy)
        ranked.append((d, label))
    return sorted(ranked, key=lambda pair: pair[0])[:5]

def predict(ranked, n, weights):
    scores = defaultdict(int)
    zero_only = weights == "distance" and ranked[0][0] == 0
    for d, label in ranked[:n]:
        if zero_only and d != 0:
            break
        scores[label] += 1 if weights == "uniform" or zero_only else 1 / d
    return min(scores, key=lambda label: (-scores[label], label))

metrics = ("euclidean", "manhattan")
validation = {
    metric: [
        neighbors(s, (r for r in train if r[0] != s[0]), metric)
        for s in train
    ]
    for metric in metrics
}
grid = [
    dict(k=n, metric=metric, weights=weights, correct=sum(
        predict(ranked, n, weights) == s[3]
        for ranked, s in zip(validation[metric], train)
    ))
    for n in (1, 3, 5)
    for metric in metrics
    for weights in ("uniform", "distance")
]
best = max(range(len(grid)), key=lambda i: grid[i]["correct"])
config = grid[best]
predictions = [
    predict(neighbors(s, train, config["metric"]), config["k"], config["weights"])
    for s in test
]
wj(dict(grid=grid, best=best, predictions=predictions,
        test_correct=sum(label == s[3] for label, s in zip(predictions, test))))