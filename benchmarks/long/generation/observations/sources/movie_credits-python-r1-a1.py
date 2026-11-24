import ast
import json
from collections import Counter, defaultdict


def entries(cell):
    if not cell:
        return ()
    try:
        value = json.loads(cell)
    except (ValueError, RecursionError):
        try:
            value = ast.literal_eval(cell.strip())
        except (ValueError, SyntaxError, TypeError, RecursionError, OverflowError):
            return ()
    return (item for item in value if isinstance(item, dict)) if isinstance(value, list) else ()


films = {
    row["id"]
    for row in csvrows("movies.csv")
    if row["id"] and any(
        genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in entries(row["genres"])
    )
}

credits = Counter()
person_films = defaultdict(set)
credited_films = set()

for row in csvrows("credits.csv"):
    film = row["id"]
    if film not in films:
        continue
    for member in entries(row["crew"]):
        person = member.get("id")
        if type(person) is int and person > 0:
            credits[person] += 1
            person_films[person].add(film)
            credited_films.add(film)

leaders = sorted(
    credits, key=lambda person: (-credits[person], -len(person_films[person]), person)
)[:5]
writejson({
    "films": len(films),
    "credited_films": len(credited_films),
    "appearances": sum(credits.values()),
    "leaders": [
        {"id": person, "credits": credits[person], "movies": len(person_films[person])}
        for person in leaders
    ],
})