from app.connectors.jira import JiraConnector


def test_parse_status_history_extracts_only_status_items():
    histories = [
        {
            "created": "2026-05-01T10:00:00.000+0000",
            "author": {"displayName": "Ann"},
            "items": [
                {"field": "status", "fromString": "To Do", "toString": "In Progress"},
                {"field": "assignee", "fromString": None, "toString": "Bob"},
            ],
        },
        {
            "created": "2026-05-02T12:00:00.000+0000",
            "author": {"displayName": "Bob"},
            "items": [
                {"field": "status", "fromString": "In Progress", "toString": "Done"},
            ],
        },
    ]
    transitions = JiraConnector._parse_status_history(histories)
    assert len(transitions) == 2
    assert transitions[0]["from_status"] == "To Do"
    assert transitions[0]["to_status"] == "In Progress"
    assert transitions[0]["author"] == "Ann"
    assert transitions[1]["to_status"] == "Done"


def test_parse_status_history_empty():
    assert JiraConnector._parse_status_history([]) == []
