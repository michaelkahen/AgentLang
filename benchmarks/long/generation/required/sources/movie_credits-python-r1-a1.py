import ast
import json
import sys

if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)


def entries(cell):
    if not cell:
        return []
    try:
        value = json.loads(cell)
    except (ValueError, RecursionError):
        try:
            value = ast.literal_eval(cell)
        except (ValueError, SyntaxError, RecursionError):
            return []
    return value if isinstance(value, list) else []


films = {
    row["id"]
    for row in csvrows("movies.csv")
    if row["id"] and any(
        isinstance(genre, dict) and genre.get("name") in ("Science Fiction", "Sci-Fi")
        for genre in entries(row["genres"])
    )
}

credited_films = set()
credits = {}
movies = {}
appearances = 0

for row in csvrows("credits.csv"):
    film = row["id"]
    if film not in films:
        continue
    for member in entries(row["crew"]):
        if not isinstance(member, dict):
            continue
        person = member.get("id")
        if type(person) is int and person > 0:
            credits[person] = credits.get(person, 0) + 1
            movies.setdefault(person, set()).add(film)
            credited_films.add(film)
            appearances += 1

leaders = sorted(credits, key=lambda person: (-credits[person], -len(movies[person]), person))[:5]
writejson({
    "films": len(films),
    "credited_films": len(credited_films),
    "appearances": appearances,
    "leaders": [
        {"id": person, "credits": credits[person], "movies": len(movies[person])}
        for person in leaders
    ],
})