"""Unit tests for tools/promptctl.py."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import promptctl as pc  # noqa: E402


def make_prompt(template_user="Hi {{name}}", variables=None, **overrides):
    data = {
        "id": "test.sample",
        "name": "Sample",
        "version": "1.0.0",
        "description": "A sample prompt for tests.",
        "owner": "@me",
        "status": "draft",
        "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
        "variables": variables if variables is not None else [{"name": "name", "description": "who"}],
        "template": {"user": template_user},
        "changelog": [{"version": "1.0.0", "date": "2026-09-25", "notes": "x"}],
    }
    data.update(overrides)
    return pc.Prompt(path=pc.PROMPTS_DIR / "test" / "sample" / "prompt.yaml", data=data)


def run_check(p):
    pc.check(p, pc.load_schema("prompt.schema.json"), pc.load_schema("evals.schema.json"))
    return p


def test_render_substitutes_and_defaults():
    p = make_prompt(
        "{{a}} and {{b}}",
        [{"name": "a", "description": "x"}, {"name": "b", "description": "y", "required": False, "default": "B"}],
    )
    assert pc.render(p, {"a": "A"})["user"] == "A and B"


def test_render_missing_required_raises():
    with pytest.raises(ValueError, match="missing"):
        pc.render(make_prompt(), {})


def test_render_unknown_var_raises():
    with pytest.raises(ValueError, match="unknown"):
        pc.render(make_prompt(), {"name": "x", "extra": "y"})


def test_clean_prompt_has_no_errors():
    assert run_check(make_prompt()).errors == []


def test_undeclared_variable_is_error():
    p = run_check(make_prompt("Hi {{name}} {{ghost}}"))
    assert any("ghost" in e for e in p.errors)


def test_unused_variable_is_warning():
    p = run_check(make_prompt("Hi", [{"name": "name", "description": "who"}]))
    assert any("never used" in w for w in p.warnings)


def test_changelog_version_mismatch_is_error():
    p = run_check(make_prompt(version="1.1.0"))
    assert any("changelog" in e for e in p.errors)


def test_stable_without_evals_is_error():
    p = run_check(make_prompt(status="stable"))
    assert any("evals.yaml" in e for e in p.errors)


def test_id_must_match_path():
    p = run_check(make_prompt(id="other.thing"))
    assert any("must match folder" in e for e in p.errors)


def test_bad_semver_is_schema_error():
    p = run_check(make_prompt(version="v1"))
    assert any(e.startswith("schema") for e in p.errors)


@pytest.mark.parametrize(
    "output,assertion,ok",
    [
        ("Hello World", {"type": "contains", "value": "world"}, True),
        ("Hello", {"type": "not_contains", "value": "bye"}, True),
        ("abc123", {"type": "regex", "value": r"\d{3}"}, True),
        ('```json\n{"a": 1}\n```', {"type": "is_json"}, True),
        ("not json", {"type": "is_json"}, False),
        ('{"a": 1}', {"type": "json_schema", "value": {"type": "object", "required": ["b"]}}, False),
        ("x" * 10, {"type": "max_chars", "value": 5}, False),
    ],
)
def test_assertions(output, assertion, ok):
    assert (pc.assert_output(output, assertion) is None) is ok


def test_repository_prompts_are_valid():
    broken = {p.id: p.errors for p in pc.validate_all() if p.errors}
    assert broken == {}
