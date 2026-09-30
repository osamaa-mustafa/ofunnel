"""O-Funnel: lossless structural capture, then requirement resolution over structure.

Turn any supported document (XML, JSON, CSV, HTML, implicit key-value text) into one universal keyed-node
tree, prove the capture is complete, then resolve declared requirements against it format-blind. Nothing is
matched against raw bytes; everything is matched against structure, keys, types, value shapes, neighbors and
value populations, fused into one score.

    from ofunnel import capture, check_complete, by_key, by_value_shape
    node, fmt = capture(raw)                     # or capture(raw, fmt="csv")
    assert check_complete(raw, node, fmt)        # gate: fail the run if it does not reconstruct
    code = by_key(node, "code") or by_value_shape(node, r"\\b\\d{4}-[A-Z]{2}\\d{2}\\b")
"""
__version__ = "0.1.0"

from .adapters import ADAPTERS, capture, from_csv, from_html, from_json, from_text_kv, from_xml, sniff
from .language import by_construct, collections, fields, normalize, records
from .model import (ANNOTATION, BOOLEAN, COLLECTION, CONSTRUCTS, GROUP, INDEXED, INFERRED, NAMED, NULL,
                    NUMBER, RECORD, SCALAR, STRING, TEXT, VALUE, Node)
from .oracle import check_complete
from .query import by_key, by_path, by_value_shape, residue
from .funnel import FunnelReport, Proposal, funnel, promote
from .pipeline import ExtractResult, Pipeline, extract
from .profile import Profile, profile, signature, similarity, value_witness
from .calibration import reliability
from .require import (Match, Requirement, ResolveReport, as_bool, as_date, as_number, as_text, key_similarity,
                      key_tokens, resolve, resolve_all)

__all__ = ["Node", "NAMED", "INDEXED", "INFERRED", "SCALAR", "GROUP", "capture", "sniff", "ADAPTERS",
           "from_xml", "from_json", "from_csv", "from_text_kv", "from_html", "check_complete",
           "by_key", "by_value_shape", "by_path", "residue",
           "normalize", "by_construct", "records", "collections", "fields",
           "VALUE", "RECORD", "COLLECTION", "TEXT", "ANNOTATION", "CONSTRUCTS",
           "STRING", "NUMBER", "BOOLEAN", "NULL",
           "Requirement", "Match", "ResolveReport", "resolve", "resolve_all",
           "as_bool", "as_number", "as_date", "as_text", "key_similarity", "key_tokens",
           "funnel", "promote", "Proposal", "FunnelReport",
           "extract", "Pipeline", "ExtractResult",
           "Profile", "profile", "signature", "similarity", "value_witness", "reliability",
           "__version__"]
