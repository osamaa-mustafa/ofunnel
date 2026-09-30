"""The funnel (residue -> alias proposals -> promote) and the pipeline (extract, scavenger, learn)."""
from ofunnel import Pipeline, Requirement, capture, extract, funnel, promote

CODE = r"^\d{4}-[A-Z]{2}\d{2}$"


def _trees(keys_renamed):
    out = []
    for i in range(6):
        raw = b'<r><%s>%04d-AA90</%s><stage>final</stage></r>' % (
            keys_renamed.encode(), i, keys_renamed.encode())
        out.append(capture(raw, fmt="xml")[0])
    return out


def test_funnel_proposes_and_promotes_alias_from_residue():
    trees = _trees("f7")
    req = [Requirement("code", keys=("code",), shape=CODE, exemplars=("0503-AA90",), fuzzy=None)]
    report = funnel(trees, req, min_support=3)
    by = {(p.requirement, p.key): p for p in report.proposals}
    assert ("code", "f7") in by and by[("code", "f7")].support == 6
    promoted = promote(report, min_support=3, min_confidence=0.6)
    assert "f7" in promoted.get("code", [])


def test_scavenger_recovers_unique_opaque_key():
    r = extract(b"<r><c1>4021-KP73</c1></r>",
                [Requirement("code", keys=("code",), shape=CODE)], fmt="xml", scavenge=True)
    m = r.fields["code"]
    assert m.found and m.method == "scavenge" and m.value == "4021-KP73"


def test_scavenger_abstains_on_decoy():
    raw = b"<r><related>9999-ZZ99</related><c1>4021-KP73</c1></r>"
    r = extract(raw, [Requirement("code", keys=("code",), shape=CODE)], fmt="xml", scavenge=True)
    assert not r.fields["code"].found and r.reasons["code"].startswith("ambiguous:")


def test_pipeline_learns_and_folds_alias():
    pipe = Pipeline([Requirement("code", keys=("code",), shape=CODE,
                                 exemplars=("0503-AA90",), fuzzy=None)])
    for i in range(6):
        pipe.extract(b'<r><f7>%04d-AA90</f7></r>' % i)
    report, promoted = pipe.learn(min_support=3, min_confidence=0.6)
    assert "f7" in promoted.get("code", [])
    after = pipe.extract(b"<r><f7>4021-KP73</f7></r>", keep_for_learning=False)
    assert after.fields["code"].method == "key" and after.value("code") == "4021-KP73"


def test_extract_reports_residue():
    r = extract(b"<r><code>4021-KP73</code><extra>hello</extra></r>",
                [Requirement("code", keys=("code",))], fmt="xml")
    assert any(n.key == "extra" for n in r.residue)
