"""Value profiles: signatures, population similarity, single-value witness."""
from ofunnel import profile, signature, similarity, value_witness


def test_signature_is_run_length_class_shape():
    assert signature("4021-KP73") == "d4-A2d2"
    assert signature("4021-KP73", fine=False) == "d-Ad"
    assert signature("2026-06-17") == "d4-d2-d2"
    assert signature("") == "" and signature("   ") == ""


def test_similarity_separates_and_unites():
    codes = profile(["0503-AA90", "0938-AV45", "1018-BH58"])
    codes2 = profile(["1235-AA55", "0694-AK13"])
    dates = profile(["2026-06-17", "2026-05-14"])
    words = profile(["Consistent with Change", "Withdrawn"])
    assert similarity(codes, codes2) > 0.9          # same population, different values
    assert similarity(codes, dates) < similarity(codes, codes2)
    assert similarity(codes, words) < 0.4
    assert similarity(profile([]), codes) == 0.0     # unknown, not similar


def test_value_witness_levels():
    p = profile(["0503-AA90", "0938-AV45"])
    assert value_witness("1018-BH58", p) == 1.0      # fine signature seen
    assert value_witness("Withdrawn", p) < 0.5
    assert value_witness("x", None) is None
    assert value_witness("", p) == 0.0
