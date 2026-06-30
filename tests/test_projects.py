"""API tests for projects, linking, the project filter, and flag semantics."""

import uuid


def _project(client, name="P", description=None):
    body = {"name": name}
    if description is not None:
        body["description"] = description
    return client.post("/projects", json=body).json()["id"]


def test_project_crud(client):
    pid = _project(client, "Alpha", "desc")
    uuid.UUID(pid)  # the key is a real UUID
    assert client.get(f"/projects/{pid}").json()["name"] == "Alpha"
    assert pid in {p["id"] for p in client.get("/projects").json()}
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert client.get(f"/projects/{pid}").status_code == 404


def test_link_at_creation_and_any_filter(client):
    a, b = _project(client, "A"), _project(client, "B")
    m1 = client.post("/memories", json={"content": "apple", "project_ids": [a]}).json()
    m2 = client.post("/memories", json={"content": "banana", "project_ids": [b]}).json()
    ids_a = {m["id"] for m in client.get(f"/memories?project_ids={a}").json()}
    assert m1["id"] in ids_a and m2["id"] not in ids_a
    ids_ab = {
        m["id"]
        for m in client.get(f"/memories?project_ids={a}&project_ids={b}").json()
    }
    assert {m1["id"], m2["id"]} <= ids_ab


def test_link_unlink_endpoints(client):
    a = _project(client, "A")
    m = client.post("/memories", json={"content": "x"}).json()
    assert client.post(f"/memories/{m['id']}/projects/{a}").status_code == 204
    assert {p["id"] for p in client.get(f"/memories/{m['id']}/projects").json()} == {a}
    assert client.delete(f"/memories/{m['id']}/projects/{a}").status_code == 204
    # manual unlink must NOT set the flag
    assert client.get(f"/memories/{m['id']}").json()["had_deleted_project"] is False


def test_create_with_unknown_project_404(client):
    r = client.post(
        "/memories", json={"content": "x", "project_ids": [str(uuid.uuid4())]}
    )
    assert r.status_code == 404


def test_project_delete_flags_and_cascades(client):
    a, b = _project(client, "A"), _project(client, "B")
    m = client.post(
        "/memories", json={"content": "shared", "project_ids": [a, b]}
    ).json()
    assert client.delete(f"/projects/{a}").status_code == 204
    got = client.get(f"/memories/{m['id']}").json()
    assert got["had_deleted_project"] is True  # project deletion flips it
    # only the A link was removed; B survives
    assert {p["id"] for p in client.get(f"/memories/{m['id']}/projects").json()} == {b}


def test_search_honours_project_filter(client):
    a, b = _project(client, "A"), _project(client, "B")
    m1 = client.post(
        "/memories", json={"content": "alpha apple", "project_ids": [a]}
    ).json()
    client.post("/memories", json={"content": "beta cherry", "project_ids": [b]})
    hits = client.post(
        "/memories/search", json={"query": "fruit", "project_ids": [b]}
    ).json()
    assert m1["id"] not in {h["id"] for h in hits}
