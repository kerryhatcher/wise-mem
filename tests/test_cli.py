"""CLI tests: parity with the API via the --json output mode."""

import json
import uuid


def _json(runner, cli, args):
    result = runner.invoke(cli, ["--json", *args])
    assert result.exit_code == 0, f"{args} failed:\n{result.output}"
    return json.loads(result.stdout)


def test_project_and_memory_flow(runner, cli):
    a_id = _json(runner, cli, ["project", "add", "Alpha"])["id"]
    uuid.UUID(a_id)
    memory = _json(runner, cli, ["memory", "add", "cli apple", "--project", a_id])
    assert memory["had_deleted_project"] is False
    listed = _json(runner, cli, ["memory", "list", "--project", a_id])
    assert memory["id"] in {m["id"] for m in listed}


def test_search_modes(runner, cli):
    _json(runner, cli, ["memory", "add", "cli banana fruit"])
    sem = _json(runner, cli, ["memory", "search", "fruit", "--mode", "semantic"])
    assert sem and "distance" in sem[0]
    ft = _json(runner, cli, ["memory", "search", "banana", "--mode", "fulltext"])
    assert ft and "rank" in ft[0]


def test_project_delete_sets_flag(runner, cli):
    a_id = _json(runner, cli, ["project", "add", "A"])["id"]
    memory = _json(runner, cli, ["memory", "add", "x", "--project", a_id])
    assert runner.invoke(cli, ["project", "delete", a_id]).exit_code == 0
    got = _json(runner, cli, ["memory", "get", str(memory["id"])])
    assert got["had_deleted_project"] is True


def test_unknown_project_exits_nonzero(runner, cli):
    result = runner.invoke(cli, ["memory", "add", "x", "--project", str(uuid.uuid4())])
    assert result.exit_code == 1


def test_human_output_renders_table(runner, cli):
    # Without --json, output is a rich table (contains box-drawing chars).
    _json(runner, cli, ["memory", "add", "table row content"])
    result = runner.invoke(cli, ["memory", "list"])
    assert result.exit_code == 0
    assert "Content" in result.stdout and "─" in result.stdout
