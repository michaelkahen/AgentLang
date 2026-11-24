from collections import defaultdict
from decimal import Decimal, localcontext
from math import sqrt


def read_sample(row):
    return row["fold"], int(row["x"]), int(row["y"]), row["label"]


def neighbors(sample, pool, metric):
    _, x, y, _ = sample
    ranked = []
    for _, a, b, label in pool:
        dx, dy = abs(x - a), abs(y - b)
        distance = dx * dx + dy * dy if metric == "euclidean" else dx + dy
        ranked.append((distance, label))
    ranked.sort(key=lambda item: item[0])
    return ranked[:5]


def predict(ranked, k, metric, weights):
    selected = ranked[:k]
    scores = defaultdict(int)
    if weights == "uniform" or selected[0][0] == 0:
        for distance, label in selected:
            if weights == "uniform" or distance == 0:
                scores[label] += 1
    else:
        try:
            votes = [
                1 / (sqrt(distance) if metric == "euclidean" else distance)
                for distance, _ in selected
            ]
        except OverflowError:
            with localcontext() as context:
                context.prec = 50
                for distance, label in selected:
                    value = Decimal(distance)
                    scores[label] += 1 / (
                        value.sqrt() if metric == "euclidean" else value
                    )
        else:
            for (_, label), vote in zip(selected, votes):
                scores[label] += vote
    return min(scores, key=lambda label: (-scores[label], label))


samples = [read_sample(row) for row in csvrows("samples.csv")]
training = [sample for sample in samples if sample[0] != "test"]
holdout = [sample for sample in samples if sample[0] == "test"]
metrics = ("euclidean", "manhattan")
pools = {
    fold: [sample for sample in training if sample[0] != fold]
    for fold in ("0", "1", "2")
}
rankings = {
    metric: [neighbors(sample, pools[sample[0]], metric) for sample in training]
    for metric in metrics
}

grid = []
for k in (1, 3, 5):
    for metric in metrics:
        for weights in ("uniform", "distance"):
            correct = sum(
                predict(ranked, k, metric, weights) == sample[3]
                for sample, ranked in zip(training, rankings[metric])
            )
            grid.append(dict(k=k, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda index: grid[index]["correct"])
config = grid[best]
metric = config["metric"]
predictions = [
    predict(neighbors(sample, training, metric), config["k"], metric, config["weights"])
    for sample in holdout
]
test_correct = sum(label == sample[3] for label, sample in zip(predictions, holdout))
writejson(dict(grid=grid, best=best, predictions=predictions, test_correct=test_correct))