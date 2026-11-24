import ast
import json
from collections import Counter, defaultdict
from heapq import nsmallest


def records(cell):
    for parse in (json.loads, ast.literal_eval):
        try:
            value = parse(cell)
        except (ValueError, SyntaxError, RecursionError, OverflowError):
            continue
        if isinstance(value, list):
            return (entry for entry in value if isinstance(entry, dict))
        break
    return ()


films = {
    row["id"]
    for row in csvrows("movies.csv")
    if row["id"] and any(
        genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in records(row["genres"])
    )
}
credited_films = set()
credits = Counter()
movies = defaultdict(set)

for row in csvrows("credits.csv"):
    film = row["id"]
    if film not in films:
        continue
    for entry in records(row["crew"]):
        person = entry.get("id")
        if type(person) is int and person > 0:
            credits[person] += 1
            movies[person].add(film)
            credited_films.add(film)

leaders = nsmallest(
    5, credits, key=lambda person: (-credits[person], -len(movies[person]), person)
)
writejson({
    "films": len(films),
    "credited_films": len(credited_films),
    "appearances": sum(credits.values()),
    "leaders": [
        {"id": person, "credits": credits[person], "movies": len(movies[person])}
        for person in leaders
    ],
})