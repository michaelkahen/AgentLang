from collections import Counter, defaultdict

def entries(cell):
    values = v(cell or "")
    return (item for item in values if isinstance(item, dict)) if isinstance(values, list) else ()

films = {
    row["id"] for row in c("movies.csv")
    if row["id"] and any(
        genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in entries(row["genres"])
    )
}
credited = set()
credits = Counter()
movies = defaultdict(set)

for row in c("credits.csv"):
    film = row["id"]
    if film in films:
        for member in entries(row["crew"]):
            person = member.get("id")
            if type(person) is int and person > 0:
                credits[person] += 1
                movies[person].add(film)
                credited.add(film)

leaders = t(credits, 5, lambda p: (-credits[p], -len(movies[p]), p))
wj({
    "films": len(films),
    "credited_films": len(credited),
    "appearances": sum(credits.values()),
    "leaders": [
        {"id": p, "credits": credits[p], "movies": len(movies[p])}
        for p in leaders
    ],
})