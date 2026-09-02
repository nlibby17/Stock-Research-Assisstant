from __future__ import annotations

import hashlib
import inspect
import io
import json
import textwrap
import tokenize
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

SEC_FORMULA_CONTRACT_VERSION = "sec-formula-contract-v1"
SEMANTIC_VERSION_POLICY = {
    "requires_version_change": [
        "metric meaning",
        "period selection",
        "quality or exclusion semantics",
        "lineage interpretation",
    ],
    "does_not_require_version_change": [
        "comments or formatting",
        "platform newline style",
        "file relocation",
        "verified behavior-preserving refactor",
    ],
}


class ConceptSpec(Protocol):
    canonical_name: str
    period_type: str
    units: tuple[str, ...]
    members: tuple[tuple[str, str], ...]


def _stable_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_source_tokens(source: str) -> list[list[str]]:
    normalized = textwrap.dedent(source.replace("\r\n", "\n").replace("\r", "\n"))
    output: list[list[str]] = []
    ignored = {tokenize.ENCODING, tokenize.COMMENT, tokenize.NL, tokenize.ENDMARKER}
    structural = {tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE}
    for token in tokenize.generate_tokens(io.StringIO(normalized).readline):
        if token.type in ignored:
            continue
        if token.type in structural:
            output.append([tokenize.tok_name[token.type], ""])
        else:
            output.append([tokenize.tok_name[token.type], token.string])
    return output


def implementation_sources(
    dependencies: Iterable[tuple[str, object]],
) -> dict[str, str]:
    sources: dict[str, str] = {}
    for name, dependency in dependencies:
        if name in sources:
            raise ValueError(f"Duplicate SEC formula dependency name: {name}")
        try:
            sources[name] = inspect.getsource(dependency)
        except (OSError, TypeError) as exc:
            raise ValueError(f"SEC formula dependency source is unavailable: {name}") from exc
    if not sources:
        raise ValueError("SEC formula implementation registry cannot be empty")
    return sources


def implementation_fingerprint_from_sources(sources: Mapping[str, str]) -> str:
    if not sources:
        raise ValueError("SEC formula implementation sources cannot be empty")
    payload = [
        {"name": name, "tokens": _canonical_source_tokens(source)}
        for name, source in sorted(sources.items())
    ]
    return _stable_fingerprint(payload)


def canonical_concept_policy(concept_specs: Iterable[ConceptSpec]) -> dict[str, object]:
    concepts: list[dict[str, object]] = []
    seen: set[str] = set()
    for spec in sorted(concept_specs, key=lambda item: item.canonical_name):
        if spec.canonical_name in seen:
            raise ValueError(f"Duplicate SEC concept policy name: {spec.canonical_name}")
        seen.add(spec.canonical_name)
        concepts.append(
            {
                "canonical_name": spec.canonical_name,
                "period_type": spec.period_type,
                "units": sorted(set(spec.units)),
                "members": [
                    {
                        "priority": priority,
                        "taxonomy": taxonomy,
                        "concept": concept,
                    }
                    for priority, (taxonomy, concept) in enumerate(spec.members)
                ],
            }
        )
    return {
        "status": "configured" if concepts else "unconfigured",
        "concepts": concepts,
    }


def build_formula_contract_manifest(
    *,
    semantic_version: str,
    formula_definitions: Mapping[str, object],
    concept_specs: Iterable[ConceptSpec],
    implementation_sources: Mapping[str, str],
) -> dict[str, object]:
    definitions = json.loads(json.dumps(formula_definitions, sort_keys=True))
    concept_policy = canonical_concept_policy(concept_specs)
    payload: dict[str, object] = {
        "contract_version": SEC_FORMULA_CONTRACT_VERSION,
        "version": semantic_version,
        "semantic_version": semantic_version,
        "semantic_version_policy": json.loads(json.dumps(SEMANTIC_VERSION_POLICY, sort_keys=True)),
        "definitions": definitions,
        "formula_policy_fingerprint": _stable_fingerprint(definitions),
        "implementation_dependencies": sorted(implementation_sources),
        "implementation_fingerprint": implementation_fingerprint_from_sources(
            implementation_sources
        ),
        "concept_policy": concept_policy,
        "concept_policy_fingerprint": _stable_fingerprint(concept_policy),
    }
    payload["fingerprint"] = _stable_fingerprint(payload)
    return payload
