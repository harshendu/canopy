from app.services.impact import downstream_components
from app.services.markdown_adr import parse_markdown_adr


def test_parse_markdown_adr_sections():
    md = (
        "# Use Postgres\n\n"
        "## Context\nWe need a durable store.\n\n"
        "## Decision\nUse Postgres.\n\n"
        "## Consequences\nOps overhead.\n"
    )
    r = parse_markdown_adr(md, "fallback")
    assert r["title"] == "Use Postgres"
    assert r["context"] is not None and "durable" in r["context"]
    assert r["decision"] is not None and "Postgres" in r["decision"]
    assert r["consequences"] is not None and "Ops" in r["consequences"]


def test_parse_markdown_adr_fuzzy_and_fallback():
    r = parse_markdown_adr("## Background and forces\nx\n## Outcome\ny", "myfile.md")
    assert r["title"] == "myfile.md"  # no level-1 heading -> fallback
    assert r["context"] == "x"  # matched via "forces"
    assert r["consequences"] == "y"  # matched via "outcome"
    assert r["decision"] is None


def test_downstream_components_walks_dependents():
    # edge (source, target): source depends on target. Reverse-walk from the seed.
    edges = [(1, 2), (3, 1)]  # 1 depends on 2; 3 depends on 1
    assert downstream_components({2}, edges) == {1, 3}


def test_downstream_components_excludes_seed_and_unrelated():
    assert downstream_components({1}, [(1, 2)]) == set()  # nothing depends on 1
