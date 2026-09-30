"""Use the resolution machinery to align two column sets: match each source column to a target column by
name similarity, optionally corroborated by value populations. This is the schema-matching view of the ladder.

Run:  python examples/schema_matching.py
"""
from ofunnel import key_similarity, profile, similarity

SOURCE = {
    "cust_id": ["1001", "1002", "1003"],
    "dob": ["1990-01-05", "1985-11-30", "2001-07-14"],
    "full_name": ["Ada Lovelace", "Alan Turing", "Grace Hopper"],
}
TARGET = {
    "customer_identifier": ["2001", "2002", "2003"],
    "date_of_birth": ["1970-02-02", "1962-03-03", "1988-09-09"],
    "name": ["Katherine Johnson", "Edsger Dijkstra", "Barbara Liskov"],
}


def score(sc, tc, sv, tv):
    name = key_similarity(sc, tc)                       # abbreviation / stem / initialism aware
    val = similarity(profile(sv), profile(tv))          # value-population witness
    return name if name >= 0.9 else 0.6 * name + 0.4 * val


print(f"{'source':22} -> {'best target':22} score")
print("-" * 56)
for sc, sv in SOURCE.items():
    best = max(TARGET, key=lambda tc: score(sc, tc, sv, TARGET[tc]))
    print(f"{sc:22} -> {best:22} {score(sc, best, sv, TARGET[best]):.2f}")
