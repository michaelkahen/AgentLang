import ast
import json
from collections import Counter, defaultdict


def dicts(cell):
    if not cell:
        return ()
    try:
        value = json.loads(cell)
    except (ValueError, RecursionError):
        try:
            value = ast.literal_eval(cell.strip())
        except (ValueError, SyntaxError, RecursionError):
            return ()
    if not isinstance(value, list):
        return ()
    return (item for item in value if isinstance(item, dict))


films = {
    row["id"]
    for row in csvrows("movies.csv")
    if row["id"] and any(
        genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in dicts(row["genres"])
    )
}

credited_films = set()
credits = Counter()
person_films = defaultdict(set)

for row in csvrows("credits.csv"):
    film = row["id"]
    if film in films:
        for entry in dicts(row["crew"]):
            person = entry.get("id")
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