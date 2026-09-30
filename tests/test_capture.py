"""Capture is lossless across formats and gated by the completeness oracle."""
from ofunnel import (ANNOTATION, RECORD, VALUE, by_key, capture, check_complete, records, sniff)


def test_xml_roundtrip_and_constructs():
    raw = b'<record><code>4021-KP73</code><received>2026-06-17</received><!-- draft --></record>'
    node, fmt = capture(raw)
    assert fmt == "xml" and check_complete(raw, node, fmt) is True
    assert node.construct == RECORD
    assert by_key(node, "code")[0].value == "4021-KP73"
    assert by_key(node, "code")[0].construct == VALUE
    assert any(n.construct == ANNOTATION for n in node.walk())      # the comment is kept


def test_json_types_preserved():
    raw = b'{"n": 3, "f": 1.5, "b": true, "z": null, "s": "x"}'
    node, fmt = capture(raw)
    assert fmt == "json" and check_complete(raw, node, fmt)
    vt = {n.key: n.vtype for n in node.walk() if n.kind == "scalar"}
    assert vt == {"n": "number", "f": "number", "b": "boolean", "z": "null", "s": "string"}


def test_json_empty_object_vs_array_are_distinct():
    o, _ = capture(b'{"a": {}}')
    a, _ = capture(b'{"a": []}')
    obj = by_key(o, "a")[0]
    arr = by_key(a, "a")[0]
    assert obj.construct == RECORD and arr.construct == "collection"


def test_csv_rows():
    raw = b"code,received\n4021-KP73,2026-06-17\n0503-AA90,2026-01-02\n"
    node, fmt = capture(raw, fmt="csv")
    assert check_complete(raw, node, fmt)
    assert len(records(node)) == 2
    assert by_key(node, "code")[0].value == "4021-KP73"


def test_sniff():
    assert sniff(b"<?xml version='1.0'?><r/>") == "xml"
    assert sniff(b'{"a":1}') == "json"
    assert sniff(b"<!doctype html><html></html>") == "html"
    assert sniff(b"key: value\n") == "text"


def test_oracle_catches_a_dropped_node():
    raw = b'<record><code>4021-KP73</code><received>2026-06-17</received></record>'
    node, fmt = capture(raw)
    for n in list(node.walk()):
        n.children = [c for c in n.children if c.value != "4021-KP73"]
    assert check_complete(raw, node, fmt) is False


def test_html_keys_by_semantic_attribute():
    raw = b'<div class="product"><span class="sku">0503-AA90</span><span itemprop="price">$19.99</span></div>'
    node, fmt = capture(raw, fmt="html")
    assert check_complete(raw, node, fmt)
    assert by_key(node, "sku")[0].value == "0503-AA90"
    assert by_key(node, "price")[0].value == "$19.99"


def test_text_key_value_is_byte_lossless():
    raw = b"code: 4021-KP73\nreceived: 2026-06-17\n"
    node, fmt = capture(raw, fmt="text")
    assert fmt == "text" and check_complete(raw, node, fmt)
