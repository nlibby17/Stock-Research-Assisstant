from __future__ import annotations

from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from stockrank import cli
from stockrank.data.sec import SecConceptSpec
from stockrank.sec_fact_vintages import (
    reconstruct_sec_company_fact,
    select_sec_company_fact_vintages,
)
from stockrank.sec_financials import (
    FORMULA_VERSION,
    formula_implementation_dependencies,
    formula_manifest,
)
from stockrank.sec_formula_contract import (
    SEC_FORMULA_CONTRACT_VERSION,
    build_formula_contract_manifest,
    canonical_concept_policy,
    implementation_fingerprint_from_sources,
    implementation_sources,
)


def concept_specs() -> tuple[SecConceptSpec, ...]:
    return (
        SecConceptSpec(
            canonical_name="revenue",
            period_type="duration",
            units=("USD", "EUR"),
            members=(
                ("us-gaap", "Revenues"),
                ("us-gaap", "SalesRevenueNet"),
            ),
        ),
        SecConceptSpec(
            canonical_name="assets",
            period_type="instant",
            units=("USD",),
            members=(("us-gaap", "Assets"),),
        ),
    )


def test_source_fingerprint_ignores_platform_newlines_comments_and_formatting():
    compact = {"calculation": "def calculate(value):\r\n    # harmless\r\n    return value+1\r\n"}
    formatted = {"calculation": "def calculate( value ):\n\n    return value + 1\n"}

    assert implementation_fingerprint_from_sources(
        compact
    ) == implementation_fingerprint_from_sources(formatted)


def test_source_fingerprint_is_order_stable_and_sensitive_to_every_dependency():
    sources = {
        "period-selection": "def select(value):\n    return value + 1\n",
        "ratio-calculation": "def ratio(value):\n    return value * 2\n",
    }
    baseline = implementation_fingerprint_from_sources(sources)

    assert baseline == implementation_fingerprint_from_sources(dict(reversed(sources.items())))
    for name, source in sources.items():
        changed = dict(sources)
        changed[name] = source.replace("1", "3") if "1" in source else source.replace("2", "4")
        assert implementation_fingerprint_from_sources(changed) != baseline


def test_concept_policy_is_order_stable_but_member_priority_is_semantic():
    specs = concept_specs()
    reordered = (
        specs[1],
        replace(specs[0], units=tuple(reversed(specs[0].units))),
    )
    reprioritized = (replace(specs[0], members=tuple(reversed(specs[0].members))), specs[1])

    assert canonical_concept_policy(specs) == canonical_concept_policy(reordered)
    assert canonical_concept_policy(specs) != canonical_concept_policy(reprioritized)


def test_manifest_separates_semantic_implementation_and_concept_identity():
    specs = concept_specs()
    manifest = formula_manifest(concept_specs=specs)

    assert manifest["contract_version"] == SEC_FORMULA_CONTRACT_VERSION
    assert manifest["semantic_version"] == FORMULA_VERSION
    assert manifest["version"] == FORMULA_VERSION
    assert manifest["implementation_fingerprint"]
    assert manifest["concept_policy_fingerprint"]
    assert manifest["formula_policy_fingerprint"]
    assert manifest["fingerprint"]
    assert manifest["concept_policy"]["status"] == "configured"
    assert "metric meaning" in manifest["semantic_version_policy"]["requires_version_change"]
    assert (
        "file relocation" in manifest["semantic_version_policy"]["does_not_require_version_change"]
    )
    assert manifest["implementation_dependencies"] == sorted(
        name for name, _ in formula_implementation_dependencies()
    )

    bumped = formula_manifest(version="sec-financials-v2.0.0", concept_specs=specs)
    assert bumped["implementation_fingerprint"] == manifest["implementation_fingerprint"]
    assert bumped["concept_policy_fingerprint"] == manifest["concept_policy_fingerprint"]
    assert bumped["formula_policy_fingerprint"] == manifest["formula_policy_fingerprint"]
    assert bumped["fingerprint"] != manifest["fingerprint"]


def test_every_registered_dependency_participates_in_implementation_identity():
    sources = implementation_sources(formula_implementation_dependencies())
    baseline = implementation_fingerprint_from_sources(sources)

    for name in sources:
        changed = dict(sources)
        changed[name] += "\ncontract_probe = 1\n"
        assert implementation_fingerprint_from_sources(changed) != baseline


def test_observation_vintage_selection_participates_in_implementation_identity():
    dependencies = dict(formula_implementation_dependencies())

    assert dependencies["observation-vintage-reconstruction"] is reconstruct_sec_company_fact
    assert dependencies["observation-vintage-selection"] is select_sec_company_fact_vintages


def test_contract_fingerprint_changes_only_for_the_affected_identity():
    sources = {"calculation": "def calculate(value):\n    return value + 1\n"}
    definitions = {"ratio": "numerator / denominator"}
    specs = concept_specs()
    baseline = build_formula_contract_manifest(
        semantic_version="sec-v1",
        formula_definitions=definitions,
        concept_specs=specs,
        implementation_sources=sources,
    )

    implementation_change = build_formula_contract_manifest(
        semantic_version="sec-v1",
        formula_definitions=definitions,
        concept_specs=specs,
        implementation_sources={"calculation": "def calculate(value):\n    return value + 2\n"},
    )
    concept_change = build_formula_contract_manifest(
        semantic_version="sec-v1",
        formula_definitions=definitions,
        concept_specs=(
            replace(specs[0], members=tuple(reversed(specs[0].members))),
            specs[1],
        ),
        implementation_sources=sources,
    )
    policy_change = build_formula_contract_manifest(
        semantic_version="sec-v1",
        formula_definitions={"ratio": "numerator / positive denominator"},
        concept_specs=specs,
        implementation_sources=sources,
    )

    assert (
        implementation_change["implementation_fingerprint"]
        != baseline["implementation_fingerprint"]
    )
    assert (
        implementation_change["concept_policy_fingerprint"]
        == baseline["concept_policy_fingerprint"]
    )
    assert concept_change["implementation_fingerprint"] == baseline["implementation_fingerprint"]
    assert concept_change["concept_policy_fingerprint"] != baseline["concept_policy_fingerprint"]
    assert policy_change["formula_policy_fingerprint"] != baseline["formula_policy_fingerprint"]
    assert (
        len(
            {
                baseline["fingerprint"],
                implementation_change["fingerprint"],
                concept_change["fingerprint"],
                policy_change["fingerprint"],
            }
        )
        == 4
    )


def test_manifest_does_not_hash_whole_files_or_unrelated_locations(monkeypatch):
    def fail_read(*args, **kwargs):
        raise AssertionError("whole-file source should not be part of the formula contract")

    monkeypatch.setattr(Path, "read_text", fail_read)

    assert formula_manifest(concept_specs=concept_specs())["fingerprint"]


def test_financial_build_passes_the_effective_concept_policy_to_calculator(tmp_path, monkeypatch):
    specs = concept_specs()
    captured: dict[str, object] = {}
    settings = SimpleNamespace(
        database_path=tmp_path / "contract-integration.sqlite3",
        raw={"app": {"timezone": "UTC"}},
        universe=(),
        model_version="test-model",
    )

    class CapturingCalculator:
        def __init__(self, *, concept_specs):
            captured["concept_specs"] = concept_specs

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "load_sec_concept_specs", lambda current: specs)
    monkeypatch.setattr(cli, "SecFinancialCalculator", CapturingCalculator)

    result = cli.command_sec_financials_build(Namespace(as_of=None, ticker=None))

    assert result == 0
    assert captured["concept_specs"] == specs
