"""The funnel: discover a drifted key alias from residue, promote it, and resolve it cheaply next time.

Run:  python examples/learn_aliases.py
"""
from ofunnel import Pipeline, Requirement

# A field whose key has drifted to an opaque token 'f7' across a batch of documents.
DOCS = [b'<r><f7>%04d-AA90</f7><stage>final</stage></r>' % i for i in range(6)]

pipe = Pipeline([
    Requirement("code", keys=("code",), shape=r"\d{4}-[A-Z]{2}\d{2}",
                exemplars=("0503-AA90",), fuzzy=None),
], auto_learn_every=None)

# Before learning: 'f7' is opaque, so 'code' is absent (the ladder will not guess).
first = pipe.extract(DOCS[0])
print("before learning: code =", first.value("code"), "| residue keys =",
      [n.key for n in first.residue])

for raw in DOCS[1:]:
    pipe.extract(raw)

report, promoted = pipe.learn(min_support=3, min_confidence=0.6)
print("\nfunnel proposals:")
for p in report.proposals:
    print(f"  {p.key!r} -> {p.requirement}  support={p.support} conf={p.confidence:.2f} "
          f"contested={p.contested} evidence={p.evidence}")
print("promoted:", promoted)

# After promotion the alias is folded into the requirement's keys.
after = pipe.extract(b'<r><f7>4021-KP73</f7><stage>final</stage></r>', keep_for_learning=False)
print("\nafter learning: code =", after.value("code"), "(method:", after.fields["code"].method + ")")
