"""One requirement set, many drifting inputs: format changes, key renames, date reformats, a same-shaped
decoy, and fully opaque keys. The scavenger recovers opaque keys but abstains on the decoy.

Run:  python examples/drift_and_scavenge.py
"""
from ofunnel import Requirement, as_date, extract

SYNONYMS = {"code": {"code", "identifier", "record identifier"}}

REQS = [
    Requirement("code", concept="code", keys=("code",), shape=r"\d{4}-[A-Z]{2}\d{2}",
                exemplars=("0503-AA90", "1235-BQ12")),
    Requirement("received", keys=("received", "received_date"), normalize="date",
                neighbors=("code",)),
]

CASES = {
    "pristine XML":   b'<r><code>4021-KP73</code><received>2026-06-17</received></r>',
    "JSON":           b'{"code":"4021-KP73","received":"2026-06-17"}',
    "camelCase":      b'<r><recordIdentifier>4021-KP73</recordIdentifier><receivedDate>2026-06-17</receivedDate></r>',
    "long-form date": b'<r><code>4021-KP73</code><received>June 17, 2026</received></r>',
    "decoy first":    b'<r><related_code>9999-ZZ99</related_code><code>4021-KP73</code><received>2026-06-17</received></r>',
    "opaque keys":    b'<r><c1>4021-KP73</c1><c2>2026-06-17</c2></r>',
}

print(f"{'case':16} {'code':12} {'received':12} method(code)")
print("-" * 56)
for label, raw in CASES.items():
    r = extract(raw, REQS, synonyms=SYNONYMS, scavenge=True)
    code = r.value("code")
    recv = r.value("received")
    recv = recv.isoformat() if recv else "-"
    print(f"{label:16} {str(code):12} {recv:12} {r.fields['code'].method}")
