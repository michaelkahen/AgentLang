from collections import Counter, defaultdict

def dicts(cell):
    items = v(cell or "", [])
    return (item for item in items if isinstance(item, dict)) if isinstance(items, list) else ()

films = {
    row["id"] for row in c("movies.csv")
    if row["id"] and any(g.get("name") in ("Science Fiction", "Sci-Fi")
                         for g in dicts(row["genres"]))
}
counts = Counter()
movies = defaultdict(set)
credited = set()

for row in c("credits.csv"):
    film = row["id"]
    if film not in films:
        continue
    for member in dicts(row["crew"]):
        person = member.get("id")
        if type(person) is int and person > 0:
            counts[person] += 1
            movies[person].add(film)
            credited.add(film)

leaders = t(counts, 5, lambda p: (-counts[p], -len(movies[p]), p))
wj({
    "films": len(films),
    "credited_films": len(credited),
    "appearances": sum(counts.values()),
    "leaders": [{"id": p, "credits": counts[p], "movies": len(movies[p])}
                for p in leaders],
})