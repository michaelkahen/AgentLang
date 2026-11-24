from math import hypot

rows = [(a["fold"], int(a["x"]), int(a["y"]), a["label"])
        for a in c("samples.csv")]
train = [a for a in rows if a[0] != "test"]
test = [a for a in rows if a[0] == "test"]
pools = {f: [a for a in train if a[0] != f] for f in ("0", "1", "2")}

def predict(row, pool, size, metric, weights):
    _, x0, y0, _ = row
    def distance(a):
        dx, dy = a[1] - x0, a[2] - y0
        return hypot(dx, dy) if metric == "euclidean" else abs(dx) + abs(dy)

    neighbors = t(((distance(a), a[3]) for a in pool), size, lambda a: a[0])
    zeros = weights == "distance" and neighbors[0][0] == 0
    scores = {}
    for d, label in neighbors:
        if zeros and d:
            break
        vote = 1 if zeros or weights == "uniform" else 1 / d
        scores[label] = scores.get(label, 0) + vote
    return min(scores, key=lambda label: (-scores[label], label))

grid = []
for size in (1, 3, 5):
    for metric in ("euclidean", "manhattan"):
        for weights in ("uniform", "distance"):
            correct = sum(predict(a, pools[a[0]], size, metric, weights) == a[3]
                          for a in train)
            grid.append(dict(k=size, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda i: grid[i]["correct"])
g = grid[best]
predictions = [predict(a, train, g["k"], g["metric"], g["weights"]) for a in test]
wj(dict(grid=grid, best=best, predictions=predictions,
        test_correct=sum(p == a[3] for p, a in zip(predictions, test))))