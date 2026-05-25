import pytest
from sqlmodel import select

from app.connectors.jira import JiraConnector
from app.core.crypto import encrypt_token
from app.models.base import (
    DocKind,
    DocScope,
    DocSource,
    Provider,
    TaskType,
)
from app.models.doc import DocReference
from app.models.integration import Connection
from app.models.project import Initiative, Project, Task
from app.services import doc_graph
from app.services import mapping as ext_mapping

# --- pure: URL extraction --------------------------------------------------------

def test_extract_urls_from_plain_string() -> None:
    assert doc_graph.extract_urls("https://www.figma.com/file/abc") == [
        "https://www.figma.com/file/abc"
    ]


def test_extract_urls_from_adf_link_and_card() -> None:
    adf = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "design",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://figma.com/file/x"}}
                        ],
                    }
                ],
            },
            {"type": "inlineCard", "attrs": {"url": "https://team.atlassian.net/wiki/prd"}},
        ],
    }
    urls = doc_graph.extract_urls(adf)
    assert "https://figma.com/file/x" in urls
    assert "https://team.atlassian.net/wiki/prd" in urls


def test_is_doc_url_filters_chrome() -> None:
    assert doc_graph.is_doc_url("https://docs.google.com/document/d/prd")
    assert not doc_graph.is_doc_url("https://jira/secure/useravatar?avatarId=1.png")
    assert not doc_graph.is_doc_url("https://host/rest/api/3/issue/1")


# --- pure: applying a mapping ----------------------------------------------------

def _epic() -> dict:
    return {
        "id": "100",
        "key": "PLAT-1",
        "fields": {
            "summary": "Checkout epic",
            "customfield_10042": "https://www.figma.com/file/abc",
            "customfield_10050": "https://docs.google.com/document/d/prd123",
            "status": {"iconUrl": "https://jira/images/icons/status.png"},  # noise
        },
    }


def test_doc_links_for_epic_maps_kinds_and_sweeps_remote_links() -> None:
    links = doc_graph.doc_links_for_epic(
        _epic(),
        [
            {"jira_field": "customfield_10042", "doc_kind": "design"},
            {"jira_field": "customfield_10050", "doc_kind": "prd"},
        ],
        parse_description_links=False,
        parse_remote_links=True,
        remote_links=[{"url": "https://team.atlassian.net/wiki/td", "title": "Tech Design"}],
    )
    by_url = {link.url: link for link in links}
    assert by_url["https://www.figma.com/file/abc"].kind == DocKind.design
    assert by_url["https://docs.google.com/document/d/prd123"].kind == DocKind.prd
    assert by_url["https://team.atlassian.net/wiki/td"].kind == DocKind.other
    # the icon URL is chrome and must not be harvested
    assert not any("icons" in link.url for link in links)


def test_doc_links_dedup_prefers_explicit_mapping() -> None:
    # the same URL appears both as a mapped field and a remote link → kept once, as the kind.
    links = doc_graph.doc_links_for_epic(
        {"id": "1", "key": "K-1", "fields": {"customfield_1": "https://x/design"}},
        [{"jira_field": "customfield_1", "doc_kind": "design"}],
        parse_description_links=False,
        parse_remote_links=True,
        remote_links=[{"url": "https://x/design", "title": "Design"}],
    )
    assert len(links) == 1
    assert links[0].kind == DocKind.design


# --- fixtures --------------------------------------------------------------------

async def _jira_conn(session, project_id: int = 1) -> Connection:
    connection = Connection(
        provider=Provider.jira,
        name="jira",
        encrypted_token=encrypt_token("api-token"),
        config={
            "base_url": "https://example.atlassian.net",
            "email": "a@b.com",
            "project_id": project_id,
            "jira_project_key": "PLAT",
        },
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


# --- mapping config round-trip ---------------------------------------------------

@pytest.mark.asyncio
async def test_set_and_get_mapping(db_session) -> None:
    connection = await _jira_conn(db_session)
    saved = await doc_graph.set_mapping(
        db_session,
        connection.id,
        mappings=[{"jira_field": "customfield_10042", "field_name": "Figma", "doc_kind": "design"}],
        parse_description_links=False,
        parse_remote_links=True,
    )
    assert saved["mappings"][0]["doc_kind"] == "design"
    assert saved["parse_remote_links"] is True
    again = doc_graph.get_mapping(connection)
    assert again["mappings"][0]["jira_field"] == "customfield_10042"


# --- analyze (sample epics for AI mapping inference) -----------------------------

@pytest.mark.asyncio
async def test_analyze_surfaces_url_fields(db_session, monkeypatch) -> None:
    connection = await _jira_conn(db_session)

    async def fake_fields(self) -> dict:
        return {"customfield_10042": "Design Link"}

    async def fake_fetch_epics(self, *, limit=None, all_fields=True) -> list:
        return [_epic()]

    async def fake_remote(self, key) -> list:
        return [{"url": "https://team.atlassian.net/wiki/prd", "title": "PRD"}]

    monkeypatch.setattr(JiraConnector, "list_fields", fake_fields)
    monkeypatch.setattr(JiraConnector, "fetch_epics", fake_fetch_epics)
    monkeypatch.setattr(JiraConnector, "fetch_remote_links", fake_remote)

    out = await doc_graph.analyze_epic_doc_fields(db_session, connection.id, limit=5)
    field_ids = {c["field_id"] for c in out["distinct_fields"]}
    assert "customfield_10042" in field_ids
    assert out["epics"][0]["remote_links"][0]["url"].endswith("/wiki/prd")
    # the chrome icon URL is filtered out of candidates
    assert "status" not in field_ids


# --- harvest ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_harvest_attaches_and_is_idempotent(db_session, monkeypatch) -> None:
    project = Project(key="PLAT", name="Platform")
    db_session.add(project)
    await db_session.flush()
    epic_task = Task(project_id=project.id, name="Epic", type=TaskType.summary)
    db_session.add(epic_task)
    await db_session.flush()
    connection = await _jira_conn(db_session, project.id)
    await ext_mapping.upsert_ref(
        db_session,
        provider=Provider.jira,
        external_id="100",
        entity_type="task",
        entity_id=epic_task.id,
        external_key="PLAT-1",
    )
    await doc_graph.set_mapping(
        db_session,
        connection.id,
        mappings=[{"jira_field": "customfield_10042", "doc_kind": "design"}],
        parse_description_links=False,
        parse_remote_links=True,
    )

    async def fake_fetch_epics(self, *, limit=None, all_fields=True) -> list:
        return [_epic()]

    async def fake_remote(self, key) -> list:
        return [{"url": "https://team.atlassian.net/wiki/prd", "title": "PRD"}]

    monkeypatch.setattr(JiraConnector, "fetch_epics", fake_fetch_epics)
    monkeypatch.setattr(JiraConnector, "fetch_remote_links", fake_remote)

    result = await doc_graph.harvest(db_session, connection.id)
    assert result.epics_scanned == 1
    assert result.references_created == 2  # figma (design) + remote link (other)

    refs = (await db_session.execute(select(DocReference))).scalars().all()
    assert {r.kind for r in refs} == {DocKind.design, DocKind.other}
    design = next(r for r in refs if r.kind == DocKind.design)
    assert design.scope_level == DocScope.task
    assert design.scope_id == epic_task.id
    assert design.source == DocSource.jira_epic

    again = await doc_graph.harvest(db_session, connection.id)
    assert again.references_created == 0
    assert again.references_updated == 2


@pytest.mark.asyncio
async def test_harvest_requires_a_mapping(db_session, monkeypatch) -> None:
    connection = await _jira_conn(db_session)
    await doc_graph.set_mapping(
        db_session,
        connection.id,
        mappings=[],
        parse_description_links=False,
        parse_remote_links=False,
    )
    with pytest.raises(doc_graph.DocGraphError):
        await doc_graph.harvest(db_session, connection.id)


# --- coverage --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_coverage_rolls_up_initiative(db_session) -> None:
    initiative = Initiative(key="Q3", name="Q3")
    db_session.add(initiative)
    await db_session.flush()
    project = Project(key="P", name="P", initiative_id=initiative.id)
    db_session.add(project)
    await db_session.flush()
    task = Task(project_id=project.id, name="Epic", type=TaskType.summary)
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        DocReference(scope_level=DocScope.task, scope_id=task.id, kind=DocKind.design, url="https://f/x")
    )
    db_session.add(
        DocReference(
            scope_level=DocScope.project, scope_id=project.id, kind=DocKind.prd, url="https://p/x"
        )
    )
    await db_session.commit()

    cov = await doc_graph.coverage(db_session, DocScope.initiative, initiative.id)
    assert cov["total_references"] == 2
    assert DocKind.design in cov["present"]
    assert DocKind.prd in cov["present"]
    assert DocKind.tech_design in cov["missing"]
    assert DocKind.architecture in cov["missing"]
