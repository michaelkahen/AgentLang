from math import sqrt

def predict(row, pool, k, metric, weights):
    _, x, y, _ = row

    def distance(neighbor):
        dx, dy = x - neighbor[1], y - neighbor[2]
        return sqrt(dx * dx + dy * dy) if metric == 'euclidean' else abs(dx) + abs(dy)

    neighbors = sorted(((distance(n), n[3]) for n in pool), key=lambda n: n[0])[:k]
    weighted = weights == 'distance'
    zeros = weighted and neighbors[0][0] == 0
    scores = {}
    for d, label in neighbors:
        if zeros and d != 0:
            break
        scores[label] = scores.get(label, 0) + (1 / d if weighted and not zeros else 1)
    return min(scores, key=lambda label: (-scores[label], label))

rows = [(r['fold'], int(r['x']), int(r['y']), r['label']) for r in c('samples.csv')]
train = [row for row in rows if row[0] != 'test']
test = [row for row in rows if row[0] == 'test']
pools = {fold: [row for row in train if row[0] != fold] for fold in ('0', '1', '2')}
grid = []
for k in (1, 3, 5):
    for metric in ('euclidean', 'manhattan'):
        for weights in ('uniform', 'distance'):
            correct = sum(predict(row, pools[row[0]], k, metric, weights) == row[3]
                          for row in train)
            grid.append(dict(k=k, metric=metric, weights=weights, correct=correct))

best = max(range(len(grid)), key=lambda i: grid[i]['correct'])
config = {key: grid[best][key] for key in ('k', 'metric', 'weights')}
predictions = [predict(row, train, **config) for row in test]
wj(dict(grid=grid, best=best, predictions=predictions,
        test_correct=sum(label == row[3] for label, row in zip(predictions, test))))