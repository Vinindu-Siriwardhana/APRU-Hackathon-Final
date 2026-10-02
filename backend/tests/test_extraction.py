import json
from types import SimpleNamespace

import numpy as np

from app.extraction import ClaudeReader, SimulatedReader, page1_prompt, page1_schema, page2_schema
from app.sample_data import make_month
from app.schema import load_template

T = load_template()


def _walk(node, fn):
    fn(node)
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


def test_schemas_stay_within_structured_output_limits():
    """API limits: <=16 union-typed and <=24 optional parameters. We use none of either."""
    for schema in (page1_schema(T), page2_schema(T)):
        unions, optional = [], []

        def check(n):
            if isinstance(n, dict) and n.get("type") == "object":
                assert n.get("additionalProperties") is False
                optional.extend(set(n.get("properties", {})) - set(n.get("required", [])))
            if isinstance(n, dict) and (isinstance(n.get("type"), list) or "anyOf" in n):
                unions.append(n)
        _walk(schema, check)
        assert not unions and not optional


def test_prompt_forbids_fixing_arithmetic():
    p = page1_prompt(T)
    assert "Do NOT convert, round, add up, or correct" in p and "savings_to_date" in p


def test_claude_reader_request_shape():
    truth = {k: v.value for k, v in make_month(T).fields.items()}
    canned = SimulatedReader(T, truth).read([], "", page1_schema(T))
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(canned))])

    r = ClaudeReader(model="claude-opus-5-5", client=SimpleNamespace(messages=FakeMessages()))
    out = r.read([np.full((3000, 2000, 3), 255, np.uint8)], "prompt", page1_schema(T))
    assert out == canned
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    img = sent["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/jpeg"
