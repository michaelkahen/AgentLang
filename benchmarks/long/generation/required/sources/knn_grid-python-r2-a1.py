from math import sqrt

training = []
holdout = []
for row in csvrows("samples.csv"):
    sample = (row["fold"], int(row["x"]), int(row["y"]), row["label"])
    (holdout if sample[0] == "test" else training).append(sample)

pools = {
    fold: [sample for sample in training if sample[0] != fold]
    for fold in ("0", "1", "2")
}

def predict(sample, pool, k, metric, weights):
    _, x, y, _ = sample
    neighbors = []
    for _, nx, ny, label in pool:
        dx, dy = x - nx, y - ny
        distance = dx * dx + dy * dy if metric == "euclidean" else abs(dx) + abs(dy)
        neighbors.append((distance, label))
    neighbors.sort(key=lambda neighbor: neighbor[0])

    zero_only = weights == "distance" and neighbors[0][0] == 0
    scores = {}
    for distance, label in neighbors[:k]:
        if zero_only and distance:
            break
        if weights == "uniform" or zero_only:
            vote = 1
        else:
            vote = 1 / (sqrt(distance) if metric == "euclidean" else distance)
        scores[label] = scores.get(label, 0) + vote
    return min(scores, key=lambda label: (-scores[label], label))

grid = []
for k in (1, 3, 5):
    for metric in ("euclidean", "manhattan"):
        for weights in ("uniform", "distance"):
            correct = sum(
                predict(sample, pools[sample[0]], k, metric, weights) == sample[3]
                for sample in training
            )
            grid.append(dict(k=k, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda index: grid[index]["correct"])
choice = grid[best]
predictions = [
    predict(sample, training, choice["k"], choice["metric"], choice["weights"])
    for sample in holdout
]
writejson(dict(
    grid=grid,
    best=best,
    predictions=predictions,
    test_correct=sum(label == sample[3] for label, sample in zip(predictions, holdout)),
))