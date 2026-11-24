from math import sqrt

train, test = [], []
for row in c("samples.csv"):
    fold = row["fold"]
    sample = (fold, int(row["x"]), int(row["y"]), row["label"])
    (test if fold == "test" else train).append(sample)

def predict(row, pool, n, metric, weights):
    _, x0, y0, _ = row
    neighbors = []
    for _, x1, y1, label in pool:
        dx, dy = x0 - x1, y0 - y1
        d = sqrt(dx * dx + dy * dy) if metric == "euclidean" else abs(dx) + abs(dy)
        neighbors.append((d, label))
    neighbors.sort(key=lambda pair: pair[0])
    weighted = weights == "distance"
    zeros_only = weighted and neighbors[0][0] == 0
    scores = {}
    for d, label in neighbors[:n]:
        if zeros_only and d != 0:
            break
        scores[label] = scores.get(label, 0) + (1 / d if weighted and not zeros_only else 1)
    return min(scores, key=lambda label: (-scores[label], label))

pools = {row[0]: [s for s in train if s[0] != row[0]] for row in train}
grid = []
for n in (1, 3, 5):
    for metric in ("euclidean", "manhattan"):
        for weights in ("uniform", "distance"):
            correct = sum(predict(s, pools[s[0]], n, metric, weights) == s[3] for s in train)
            grid.append(dict(k=n, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda i: grid[i]["correct"])
config = grid[best]
predictions = [predict(s, train, config["k"], config["metric"], config["weights"]) for s in test]
wj(dict(grid=grid, best=best, predictions=predictions,
        test_correct=sum(p == s[3] for p, s in zip(predictions, test))))