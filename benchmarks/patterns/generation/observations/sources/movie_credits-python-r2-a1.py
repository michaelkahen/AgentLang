from collections import Counter, defaultdict

def entries(cell):
    items = v(cell) if cell else None
    return (item for item in items if isinstance(item, dict)) if isinstance(items, list) else ()

films = {
    row["id"] for row in c("movies.csv")
    if row["id"] and any(g.get("name") in ("Science Fiction", "Sci-Fi")
                         for g in entries(row["genres"]))
}
credited = set()
counts = Counter()
movies = defaultdict(set)

for row in c("credits.csv"):
    film = row["id"]
    if film in films:
        for member in entries(row["crew"]):
            person = member.get("id")
            if type(person) is int and person > 0:
                credited.add(film)
                counts[person] += 1
                movies[person].add(film)

wj({
    "films": len(films),
    "credited_films": len(credited),
    "appearances": sum(counts.values()),
    "leaders": [
        {"id": p, "credits": counts[p], "movies": len(movies[p])}
        for p in t(counts, 5, lambda p: (-counts[p], -len(movies[p]), p))
    ],
})