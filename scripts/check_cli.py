"""End-to-end exercise of the Typer CLI, confirming parity with the API.

Drives the CLI in-process with Typer's CliRunner against the real database
(requires Ollama for auto-embedding). Mirrors check_projects.py's coverage but
through CLI commands instead of HTTP.
"""

import json
import uuid

from typer.testing import CliRunner

from wise_mem.cli import app

runner = CliRunner()


def _json(args: list[str]) -> object:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed:\n{result.output}"
    return json.loads(result.stdout)


def _ok(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args} failed:\n{result.output}"


def main() -> None:
    # db
    assert runner.invoke(app, ["db", "current"]).exit_code == 0
    print("✓ db current")

    # projects
    a_id = _json(["project", "add", "CLI Alpha"])["id"]
    b_id = _json(["project", "add", "CLI Beta", "--description", "second"])["id"]
    uuid.UUID(a_id)
    assert _json(["project", "get", a_id])["name"] == "CLI Alpha"
    print(f"✓ project add/get: A={a_id[:8]} B={b_id[:8]}")

    # memory add (auto-embed) + linking
    m1 = _json(["memory", "add", "cli apple banana", "--project", a_id])
    assert m1["had_deleted_project"] is False
    m2 = _json(["memory", "add", "cli cherry date"])
    _ok(["memory", "link", str(m2["id"]), b_id])
    m3 = _json(["memory", "add", "cli shared fig", "--project", a_id, "--project", b_id])
    assert {p["id"] for p in _json(["memory", "projects", str(m3["id"])])} == {a_id, b_id}
    print("✓ memory add + auto-embed + linking (at-create, endpoint, dual)")

    # list filter (ANY)
    ids_a = {m["id"] for m in _json(["memory", "list", "--project", a_id])}
    assert m1["id"] in ids_a and m3["id"] in ids_a and m2["id"] not in ids_a
    print("✓ list --project filter")

    # search modes honour the project filter and carry the right score key
    sem_b = _json(["memory", "search", "fruit", "--mode", "semantic", "--project", b_id])
    assert m1["id"] not in {h["id"] for h in sem_b}
    assert all("distance" in h for h in sem_b)
    ft = _json(["memory", "search", "apple", "--mode", "fulltext"])
    assert any(h["id"] == m1["id"] and "rank" in h for h in ft)
    hy = _json(["memory", "search", "shared", "--mode", "hybrid"])
    assert hy and "score" in hy[0]
    print("✓ search semantic/fulltext/hybrid (filtered, scored)")

    # update re-embeds; 404 on unknown project
    upd = _json(["memory", "update", str(m1["id"]), "--content", "cli updated text"])
    assert upd["content"] == "cli updated text"
    assert runner.invoke(
        app, ["memory", "add", "x", "--project", str(uuid.uuid4())]
    ).exit_code == 1
    print("✓ update (re-embed) + 404 on unknown project")

    # unlink does NOT flag; project delete DOES
    _ok(["memory", "unlink", str(m2["id"]), b_id])
    assert _json(["memory", "get", str(m2["id"])])["had_deleted_project"] is False
    _ok(["project", "delete", a_id])
    assert _json(["memory", "get", str(m1["id"])])["had_deleted_project"] is True
    assert {p["id"] for p in _json(["memory", "projects", str(m3["id"])])} == {b_id}
    print("✓ unlink leaves flag False; project delete sets flag + cascades")

    # cleanup
    for mid in (m1["id"], m2["id"], m3["id"]):
        _ok(["memory", "delete", str(mid)])
    _ok(["project", "delete", b_id])
    print("✓ cleanup")

    print("\nAll CLI checks passed.")


if __name__ == "__main__":
    main()
