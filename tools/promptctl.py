#!/usr/bin/env python3
"""promptctl — manage, validate, render and evaluate the prompt library.

Usage:
  promptctl list
  promptctl validate                     # schema + lint every prompt and eval suite
  promptctl render <id> [-v key=value]... [--vars-file f.yaml] [--json]
  promptctl eval [<id>] [--live]         # offline: render every case; --live: call the model
  promptctl catalog                      # regenerate CATALOG.md

Dependencies: PyYAML, jsonschema. Live evals call the Anthropic Messages API
over plain HTTPS using ANTHROPIC_API_KEY (no SDK required).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
SCHEMA_DIR = ROOT / "schema"
VAR_PATTERN = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


# --------------------------------------------------------------------------- model
@dataclass
class Prompt:
    path: Path
    data: dict
    evals: dict | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.data.get("id", "<missing id>")

    @property
    def expected_id(self) -> str:
        rel = self.path.parent.relative_to(PROMPTS_DIR)
        return ".".join(rel.parts)


class _StrDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps ISO dates as strings, so they validate as JSON Schema strings."""


_StrDateLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(text: str):
    return yaml.load(text, Loader=_StrDateLoader)


def load_schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8")))


def discover() -> list[Prompt]:
    prompts = []
    for path in sorted(PROMPTS_DIR.rglob("prompt.yaml")):
        data = load_yaml(path.read_text(encoding="utf-8")) or {}
        evals_path = path.parent / "evals.yaml"
        evals = load_yaml(evals_path.read_text(encoding="utf-8")) if evals_path.exists() else None
        prompts.append(Prompt(path=path, data=data, evals=evals))
    return prompts


def find(prompt_id: str) -> Prompt:
    for p in discover():
        if p.id == prompt_id:
            return p
    sys.exit(f"error: no prompt with id '{prompt_id}'. Run `promptctl list`.")


# --------------------------------------------------------------------------- rendering
def template_vars(p: Prompt) -> set[str]:
    tpl = p.data.get("template", {})
    return set(VAR_PATTERN.findall(tpl.get("system", "") + "\n" + tpl.get("user", "")))


def render(p: Prompt, values: dict) -> dict:
    declared = {v["name"]: v for v in p.data["variables"]}
    resolved = {}
    missing = []
    for name, spec in declared.items():
        if name in values:
            resolved[name] = values[name]
        elif "default" in spec:
            resolved[name] = spec["default"]
        elif spec.get("required", True):
            missing.append(name)
        else:
            resolved[name] = ""
    if missing:
        raise ValueError(f"missing required variable(s): {', '.join(missing)}")
    unknown = set(values) - set(declared)
    if unknown:
        raise ValueError(f"unknown variable(s): {', '.join(sorted(unknown))}")

    def sub(text: str) -> str:
        return VAR_PATTERN.sub(lambda m: str(resolved[m.group(1)]), text)

    tpl = p.data["template"]
    out = {"user": sub(tpl["user"])}
    if "system" in tpl:
        out["system"] = sub(tpl["system"])
    return out


# --------------------------------------------------------------------------- validation
def check(p: Prompt, prompt_validator, evals_validator) -> None:
    for err in prompt_validator.iter_errors(p.data):
        loc = "/".join(str(x) for x in err.absolute_path) or "<root>"
        p.errors.append(f"schema: {loc}: {err.message}")
    if p.errors:
        return  # lint assumes a schema-valid document

    if p.id != p.expected_id:
        p.errors.append(f"id '{p.id}' must match folder path '{p.expected_id}'")

    declared = {v["name"] for v in p.data["variables"]}
    used = template_vars(p)
    for name in sorted(used - declared):
        p.errors.append(f"template uses undeclared variable '{{{{{name}}}}}'")
    for name in sorted(declared - used):
        p.warnings.append(f"variable '{name}' is declared but never used")

    log = p.data.get("changelog") or []
    if not log:
        p.warnings.append("no changelog entries")
    elif log[0]["version"] != p.data["version"]:
        p.errors.append(f"latest changelog entry ({log[0]['version']}) != version ({p.data['version']})")

    if p.data["status"] in ("stable",) and p.evals is None:
        p.errors.append("stable prompts must ship an evals.yaml")

    if p.evals is not None:
        for err in evals_validator.iter_errors(p.evals):
            loc = "/".join(str(x) for x in err.absolute_path) or "<root>"
            p.errors.append(f"evals schema: {loc}: {err.message}")
        if not p.errors:
            for case in p.evals["cases"]:
                try:
                    render(p, case["vars"])
                except ValueError as e:
                    p.errors.append(f"eval case '{case['name']}': {e}")

    ids_seen = [s for s in p.data.get("tags", []) if s != s.lower()]
    if ids_seen:
        p.warnings.append(f"tags should be lowercase: {ids_seen}")


def validate_all() -> list[Prompt]:
    pv, ev = load_schema("prompt.schema.json"), load_schema("evals.schema.json")
    prompts = discover()
    for p in prompts:
        check(p, pv, ev)
    ids = [p.id for p in prompts]
    for dup in {i for i in ids if ids.count(i) > 1}:
        for p in prompts:
            if p.id == dup:
                p.errors.append(f"duplicate id '{dup}'")
    return prompts


# --------------------------------------------------------------------------- evals
def call_anthropic(p: Prompt, rendered: dict) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    model = os.environ.get("PROMPTCTL_MODEL_OVERRIDE") or p.data["model"]["name"]
    body = {
        "model": model,
        "max_tokens": p.data["model"].get("max_tokens", 2048),
        "temperature": p.data["model"].get("temperature", 0),
        "messages": [{"role": "user", "content": rendered["user"]}],
    }
    if "system" in rendered:
        body["system"] = rendered["system"]
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode(),
        headers={"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    return "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return m.group(1) if m else text


def assert_output(output: str, a: dict) -> str | None:
    """Return None on pass, or a failure message."""
    t, v = a["type"], a.get("value")
    cs = a.get("case_sensitive", False)
    hay, needle = (output, str(v)) if cs else (output.lower(), str(v).lower())
    if t == "contains":
        return None if needle in hay else f"expected to contain {v!r}"
    if t == "not_contains":
        return None if needle not in hay else f"expected NOT to contain {v!r}"
    if t == "regex":
        return None if re.search(v, output, 0 if cs else re.I) else f"no match for /{v}/"
    if t == "max_chars":
        return None if len(output) <= int(v) else f"{len(output)} chars > {v}"
    if t in ("is_json", "json_schema"):
        try:
            doc = json.loads(_strip_fences(output))
        except json.JSONDecodeError as e:
            return f"not valid JSON: {e}"
        if t == "json_schema":
            errs = list(Draft202012Validator(v).iter_errors(doc))
            return None if not errs else f"JSON schema: {errs[0].message}"
        return None
    return f"unknown assertion type {t}"


def run_evals(prompts: list[Prompt], live: bool) -> int:
    failures = total = 0
    for p in prompts:
        if not p.evals:
            continue
        print(f"\n▸ {p.id} v{p.data['version']}")
        for case in p.evals["cases"]:
            total += 1
            try:
                rendered = render(p, case["vars"])
            except ValueError as e:
                failures += 1
                print(f"  ✗ {case['name']}: render failed: {e}")
                continue
            if not live:
                print(f"  ✓ {case['name']} (rendered, {len(case['assert'])} assertion(s) not run offline)")
                continue
            try:
                output = call_anthropic(p, rendered)
            except RuntimeError as e:
                failures += 1
                print(f"  ✗ {case['name']}: {e}")
                continue
            problems = [m for a in case["assert"] if (m := assert_output(output, a))]
            if problems:
                failures += 1
                print(f"  ✗ {case['name']}")
                for m in problems:
                    print(f"      - {m}")
            else:
                print(f"  ✓ {case['name']}")
    mode = "live" if live else "offline"
    print(f"\n{total - failures}/{total} cases passed ({mode})")
    return 1 if failures else 0


# --------------------------------------------------------------------------- catalog
def build_catalog(prompts: list[Prompt]) -> str:
    lines = [
        "# Prompt Catalog",
        "",
        "> Generated by `python tools/promptctl.py catalog`. Do not edit by hand.",
        "",
        "| ID | Name | Version | Status | Model | Evals | Description |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in sorted(prompts, key=lambda x: x.id):
        d = p.data
        link = p.path.parent.relative_to(ROOT).as_posix()
        n = len(p.evals["cases"]) if p.evals else 0
        lines.append(
            f"| [`{d['id']}`]({link}/prompt.yaml) | {d['name']} | {d['version']} | {d['status']} "
            f"| {d['model']['name']} | {n} | {d['description'].strip().splitlines()[0]} |"
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- CLI
def parse_vars(pairs: list[str], vars_file: str | None) -> dict:
    values = {}
    if vars_file:
        values.update(load_yaml(Path(vars_file).read_text(encoding="utf-8")) or {})
    for pair in pairs or []:
        if "=" not in pair:
            sys.exit(f"error: -v expects key=value, got '{pair}'")
        k, v = pair.split("=", 1)
        if v.startswith("@"):
            v = Path(v[1:]).read_text(encoding="utf-8")
        values[k] = v
    return values


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="promptctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    r = sub.add_parser("render")
    r.add_argument("id")
    r.add_argument("-v", "--var", action="append", help="key=value, or key=@file to read from a file")
    r.add_argument("--vars-file")
    r.add_argument("--json", action="store_true", help="emit Messages-API-shaped JSON")
    e = sub.add_parser("eval")
    e.add_argument("id", nargs="?")
    e.add_argument("--live", action="store_true", help="call the model and run assertions")
    sub.add_parser("catalog")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        for p in discover():
            print(f"{p.id:<48} {p.data.get('version', '?'):<8} {p.data.get('status', '?')}")
        return 0

    if args.cmd == "validate":
        prompts = validate_all()
        n_err = 0
        for p in prompts:
            if p.errors or p.warnings:
                print(f"{p.path.relative_to(ROOT)}")
                for m in p.errors:
                    print(f"  ERROR   {m}")
                for m in p.warnings:
                    print(f"  WARNING {m}")
            n_err += len(p.errors)
        print(f"\nValidated {len(prompts)} prompt(s): {n_err} error(s)")
        return 1 if n_err else 0

    if args.cmd == "render":
        p = find(args.id)
        try:
            out = render(p, parse_vars(args.var, args.vars_file))
        except ValueError as e:
            sys.exit(f"error: {e}")
        if args.json:
            body = {"model": p.data["model"]["name"], "messages": [{"role": "user", "content": out["user"]}]}
            if "system" in out:
                body["system"] = out["system"]
            print(json.dumps(body, indent=2))
        else:
            if "system" in out:
                print("=== SYSTEM ===\n" + out["system"] + "\n")
            print("=== USER ===\n" + out["user"])
        return 0

    if args.cmd == "eval":
        prompts = validate_all()
        broken = [p for p in prompts if p.errors]
        if broken:
            print("Fix validation errors first (`promptctl validate`).")
            return 1
        if args.id:
            prompts = [p for p in prompts if p.id == args.id] or [find(args.id)]
        return run_evals(prompts, args.live)

    if args.cmd == "catalog":
        (ROOT / "CATALOG.md").write_text(build_catalog(discover()), encoding="utf-8")
        print("Wrote CATALOG.md")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
