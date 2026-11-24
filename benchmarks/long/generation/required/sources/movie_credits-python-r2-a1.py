import ast
import json
from collections import Counter, defaultdict

def objects(cell):
    try:
        value = json.loads(cell)
    except (ValueError, RecursionError):
        try:
            value = ast.literal_eval(cell.strip())
        except (ValueError, SyntaxError, RecursionError):
            return
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, dict))

films = {
    row["id"] for row in csvrows("movies.csv")
    if row["id"] and any(
        genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in objects(row["genres"])
    )
}
counts = Counter()
person_films = defaultdict(set)
credited_films = set()

for row in csvrows("credits.csv"):
    movie = row["id"]
    if movie in films:
        for entry in objects(row["crew"]):
            person = entry.get("id")
            if type(person) is int and person > 0:
                counts[person] += 1
                person_films[person].add(movie)
                credited_films.add(movie)

leaders = sorted(counts, key=lambda p: (-counts[p], -len(person_films[p]), p))[:5]
writejson({
    "films": len(films),
    "credited_films": len(credited_films),
    "appearances": sum(counts.values()),
    "leaders": [
        {"id": p, "credits": counts[p], "movies": len(person_films[p])}
        for p in leaders
    ],
})