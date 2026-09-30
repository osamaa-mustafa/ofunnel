"""Quickstart: capture, extract, and see an absence reported with a reason.

Run:  python examples/quickstart.py
"""
from ofunnel import Requirement, capture, check_complete, extract

raw = b"""<record>
  <code>4021-KP73</code>
  <received>2026-06-17</received>
  <!-- draft -->
</record>"""

# 1) capture is lossless and gated
node, fmt = capture(raw)
print("format:", fmt, "| complete:", check_complete(raw, node, fmt))

# 2) declare requirements in the tree's language, not as byte patterns
reqs = [
    Requirement("code", keys=("code", "id"), shape=r"\d{4}-[A-Z]{2}\d{2}"),
    Requirement("received", keys=("received", "date"), normalize="date"),
    Requirement("effective", keys=("effective", "effective_date"), normalize="date"),
]

result = extract(raw, reqs)
for name in ("code", "received", "effective"):
    m = result.fields[name]
    if m.found:
        print(f"{name:10} = {m.value!r:25} (method={m.method}, confidence={m.confidence})")
    else:
        print(f"{name:10} = ABSENT (reason: {m.reason})")
