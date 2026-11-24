from math import sqrt


def neighbors(row, pool, metric):
    _, x, y, _ = row
    if metric == "euclidean":
        ranked = sorted(
            (((x - a) ** 2 + (y - b) ** 2, label) for _, a, b, label in pool),
            key=lambda pair: pair[0],
        )
        return [(sqrt(distance), label) for distance, label in ranked[:5]]
    ranked = sorted(
        ((abs(x - a) + abs(y - b), label) for _, a, b, label in pool),
        key=lambda pair: pair[0],
    )
    return ranked[:5]


def predict(ranked, k, weights):
    scores = {}
    zero_only = weights == "distance" and ranked[0][0] == 0
    for distance, label in ranked[:k]:
        if zero_only and distance != 0:
            break
        vote = 1 if weights == "uniform" or zero_only else 1 / distance
        scores[label] = scores.get(label, 0) + vote
    return min(scores, key=lambda label: (-scores[label], label))


training, holdout = [], []
for record in csvrows("samples.csv"):
    fold = record["fold"]
    row = (fold if fold == "test" else int(fold),
           int(record["x"]), int(record["y"]), record["label"])
    (holdout if fold == "test" else training).append(row)

metrics = ("euclidean", "manhattan")
pools = {fold: [row for row in training if row[0] != fold] for fold in range(3)}
rankings = {
    metric: [neighbors(row, pools[row[0]], metric) for row in training]
    for metric in metrics
}

grid = []
for k in (1, 3, 5):
    for metric in metrics:
        for weights in ("uniform", "distance"):
            correct = sum(
                predict(ranked, k, weights) == row[3]
                for ranked, row in zip(rankings[metric], training)
            )
            grid.append(dict(k=k, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda index: grid[index]["correct"])
config = grid[best]
predictions = [
    predict(neighbors(row, training, config["metric"]), config["k"], config["weights"])
    for row in holdout
]
writejson(dict(
    grid=grid,
    best=best,
    predictions=predictions,
    test_correct=sum(label == row[3] for label, row in zip(predictions, holdout)),
))