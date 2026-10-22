import secrets
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import server

TEST_PASSWORD = secrets.token_urlsafe(24)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("QUFO_INITIAL_PASSWORD", TEST_PASSWORD)
    monkeypatch.setattr(server, "DB", tmp_path / "workspace.sqlite3")
    monkeypatch.setattr(server.ai, "embeddings", lambda texts: None)
    monkeypatch.setattr(server.ai, "generate", lambda *args: None)
    server._attempts.clear()
    with TestClient(server.app) as client:
        yield client


def sign_in(client, username="atharv"):
    response = client.post("/api/login", json={"username": username, "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()


def add_text(client, text, visibility="team", filename="update.txt"):
    return client.post("/api/upload", files={"file": (filename, text.encode(), "text/plain")},
                       data={"title": "Engineering evidence", "visibility": visibility, "source_date": "2026-10-22"})


def test_authentication_required(client):
    assert client.get("/api/workspace").status_code == 401
    assert client.post("/api/login", json={"username": "atharv", "password": "wrong"}).status_code == 401
    sign_in(client)
    assert client.get("/api/me").json()["role"] == "admin"
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_seeded_sources_and_originals(client):
    sign_in(client)
    data = client.get("/api/workspace").json()
    assert len(data["documents"]) == 4
    assert not data["records"]
    for d in data["documents"]:
        assert d["url"].startswith("https://techcommunity.microsoft.com/")
        source = client.get("/api/documents/" + d["id"]).json()
        assert source["chunks"]
        assert client.get("/api/documents/" + d["id"] + "/original").status_code == 200


def test_upload_retention_and_deduplication(client):
    sign_in(client, "alex")
    text = "Project Aurora completed its release validation. The documented meeting deadline is November 12, 2026."
    first = add_text(client, text).json()
    assert first["status"] == "ready"
    assert not first["duplicate"]
    assert add_text(client, text).json()["duplicate"]
    assert client.get(f"/api/documents/{first['id']}/original").content.decode() == text


def test_document_permission_boundary(client):
    sign_in(client, "alex")
    private = add_text(client, "Private aurorasecret analysis contains confidential investigation evidence.", "private").json()["id"]
    team = add_text(client, "Research team zephyrsecret investigation evidence is confidential.", "team").json()["id"]
    company = add_text(client, "Company-wide project bridge update is available to every member.", "company").json()["id"]
    sign_in(client, "jordan")
    ids = {d["id"] for d in client.get("/api/workspace").json()["documents"]}
    assert private not in ids and team not in ids and company in ids
    for uid in [private, team]:
        assert client.get("/api/documents/" + uid).status_code == 404
        assert client.get("/api/documents/" + uid + "/original").status_code == 404
        assert client.delete("/api/documents/" + uid).status_code == 404
    result = client.post("/api/chat", json={"question": "What is aurorasecret?"}).json()
    assert not result["citations"]
    report = client.get("/api/report").json()
    assert not any(h["id"] in {private, team} for h in report["highlights"])


def test_employee_can_add_and_complete_work(client):
    sign_in(client, "alex")
    record = {"title": "Validate launch timing", "body": "Measured launch timings and documented the results.",
              "kind": "Task", "hours": 2.5, "cost": 250, "due": "2026-11-12", "pinned": True, "priority": "High"}
    uid = client.post("/api/records", json=record).json()["id"]
    record["status"] = "Completed"
    assert client.patch("/api/records/" + uid, json=record).status_code == 200
    report = client.get("/api/report").json()
    assert report["hours"] == 2.5 and report["cost"] == 250
    assert len(report["completed"]) == 1 and len(report["pinned"]) == 1


def test_investor_can_contribute_and_permissions_apply(client):
    sign_in(client, "jordan")
    payload = {"title": "Investment review question", "body": "Please document the evidence for the next milestone.", "kind": "Point", "visibility": "private"}
    uid = client.post("/api/records", json=payload).json()["id"]
    sign_in(client, "alex")
    assert uid not in {r["id"] for r in client.get("/api/workspace").json()["records"]}
    assert client.patch("/api/records/" + uid, json=payload).status_code == 404


def test_missing_evidence_and_source_citations(client):
    sign_in(client)
    result = client.post("/api/chat", json={"question": "What architecture changes were made to Microsoft Teams?"}).json()
    assert result["citations"]
    assert "WebView2" in result["answer"]
    for c in result["citations"]:
        assert client.get("/api/documents/" + c["document_id"]).status_code == 200
    missing = client.post("/api/chat", json={"question": "What is the recipe for chocolate tiramisu?"}).json()
    assert missing["mode"] == "Insufficient evidence"
    assert not missing["citations"]


def test_reports_respect_dates_and_audience(client):
    sign_in(client)
    assert client.get("/api/report?period=daily").json()["doc_count"] == 0
    result = client.get("/api/report?period=custom&start=2023-10-01&end=2023-10-31").json()
    assert result["doc_count"] == 1
    employee = client.get("/api/report?audience=Employees").json()
    investor = client.get("/api/report?audience=Investors").json()
    assert employee["focus"] != investor["focus"]
    assert employee["highlights"][0]["id"] != investor["highlights"][0]["id"]
    assert not investor["has_time"] and not investor["has_cost"]


def test_exports_require_approval_and_authority(client):
    sign_in(client, "alex")
    doc = client.get("/api/workspace").json()["documents"][0]["id"]
    payload = {"audience": "Public", "document_ids": [doc], "approved": True}
    assert client.post("/api/exports", json=payload).status_code == 403
    sign_in(client, "maya")
    assert client.post("/api/exports", json={**payload, "approved": False}).status_code == 422
    assert client.post("/api/exports", json={**payload, "document_ids": ["nonexistent"]}).status_code == 404
    response = client.post("/api/exports", json=payload)
    assert response.status_code == 200 and "Approved by Maya" in response.text


@pytest.mark.parametrize("filename,content", [
    ("malware.exe", b"not an allowed file"),
    ("empty.txt", b""),
    ("bad.pdf", b"not a pdf"),
    ("bad.docx", b"not a zip"),
    ("invalid.txt", b"\xff\xff"),
])
def test_invalid_uploads_are_actionable(client, filename, content):
    sign_in(client)
    response = client.post("/api/upload", files={"file": (filename, content)})
    assert response.status_code == 422


def test_word_extraction(client):
    sign_in(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>The team completed release verification and recorded its findings.</w:t></w:r></w:p></w:body></w:document>')
    response = client.post("/api/upload", files={"file": ("notes.docx", buffer.getvalue())})
    assert response.status_code == 200


def test_delete_removes_retrievable_passages(client):
    sign_in(client, "alex")
    uid = add_text(client, "Project orchidsecret completed the investigation with a verified written conclusion.").json()["id"]
    assert client.delete("/api/documents/" + uid).status_code == 200
    assert client.get("/api/documents/" + uid).status_code == 404
    assert not client.post("/api/chat", json={"question": "What is orchidsecret?"}).json()["citations"]


def test_validation_and_no_invented_finances(client):
    sign_in(client)
    assert client.post("/api/records", json={"title": "Bad entry", "body": "A sufficient description.", "hours": -1}).status_code == 422
    assert client.post("/api/records", json={"title": "Bad entry", "body": "A sufficient description.", "due": "tomorrow"}).status_code == 422
    assert client.get("/api/report?audience=Hacker").status_code == 422
    assert client.get("/api/report?period=custom").status_code == 422
    assert client.get("/api/report?start=2026-11-01&end=2026-10-01").status_code == 422
    report = client.get("/api/report").json()
    assert report["cost"] == 0 and not report["has_cost"]


def test_document_signals_are_explicit_and_source_linked(client):
    sign_in(client, "alex")
    text = ("Deadline: release review is due by 2026-11-12.\n"
            "The team completed the written requirements review.\n"
            "No private budget or deadline is available.")
    uid = add_text(client, text).json()["id"]
    document = client.get("/api/documents/" + uid).json()
    assert any(f["kind"] == "Deadline" and "2026-11-12" in f["dates"] for f in document["findings"])
    assert any(f["kind"] == "Completion" for f in document["findings"])
    assert not any("No private" in f["text"] for f in document["findings"])
    report = client.get("/api/report").json()
    assert any(f["id"] == uid for f in report["document_findings"])


def test_generated_citations_align_to_supplied_evidence(client, monkeypatch):
    sign_in(client)
    monkeypatch.setattr(server.ai, "generate",
                        lambda *args: "Microsoft replaced AngularJS with React and uses Edge WebView2.")
    result = client.post("/api/chat", json={"question": "What architecture changes were made to Microsoft Teams?"}).json()
    assert result["mode"].startswith("AI synthesis")
    import re
    reference = int(re.search(r"\[(\d+)\]", result["answer"]).group(1))
    assert "AngularJS" in result["citations"][reference - 1]["text"]
    monkeypatch.setattr(server.ai, "generate",
                        lambda *args: "Microsoft saved 900000 dollars and delivered 4700 new features.")
    result = client.post("/api/chat", json={"question": "What architecture changes were made to Microsoft Teams?"}).json()
    assert result["mode"] == "Source excerpts"
    assert "900000" not in result["answer"]


def test_related_sources_do_not_expose_restricted_content(client):
    sign_in(client, "alex")
    private = add_text(client, "Private Microsoft Teams architecture analysis uses React and WebView2.", "private").json()["id"]
    sign_in(client, "jordan")
    docs = client.get("/api/workspace").json()["documents"]
    for doc in docs:
        related = client.get("/api/documents/" + doc["id"]).json()["related"]
        assert private not in {r["id"] for r in related}


def test_record_deletion_requires_ownership(client):
    sign_in(client, "alex")
    uid = client.post("/api/records", json={"title": "Own work point", "body": "This record belongs to the contributing employee."}).json()["id"]
    sign_in(client, "jordan")
    assert client.delete("/api/records/" + uid).status_code == 404
    sign_in(client, "alex")
    assert client.delete("/api/records/" + uid).status_code == 200


def test_text_pdf_upload_retains_readable_evidence(client):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    sign_in(client, "alex")
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (The research team completed source verification and recorded its findings.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    response = client.post("/api/upload", files={"file": ("review.pdf", buffer.getvalue(), "application/pdf")})
    assert response.status_code == 200
    document = client.get("/api/documents/" + response.json()["id"]).json()
    assert "completed source verification" in document["text"]
    assert document["findings"][0]["kind"] == "Completion"


@pytest.mark.parametrize("question", ["when did it start", "when did the development start", "when did development begin"])
def test_start_question_does_not_turn_preview_into_development_date(client, question):
    sign_in(client)
    result = client.post("/api/chat", json={"question": question}).json()
    assert result["mode"] == "Source-grounded answer"
    assert "do not establish when development" in result["answer"]
    assert "public preview" in result["answer"]
    assert "2023-03-27" in result["answer"]
    assert "development started on March 27" not in result["answer"]


def test_latest_milestone_ignores_newer_documentation_update(client):
    sign_in(client)
    uid = add_text(client, "This documentation describes authentication configuration and a revised support article.").json()["id"]
    with server.db() as c:
        c.execute("UPDATE docs SET source_date='2026-10-22',title='Microsoft Teams \u00b7 Updated authentication' WHERE id=?", (uid,))
        c.execute("INSERT INTO doc_metadata VALUES(?,?,?,?,?,?,?)",
                  (uid, "official_documentation", "documentation_updated", "MicrosoftDocs/example", "revision", "CC-BY-4.0", "auth.md"))
    result = client.post("/api/chat", json={"question": "what was the last major update"}).json()
    assert "2023-10-05" in result["answer"]
    assert "general availability" in result["answer"]
    assert "2026-10-22" not in result["answer"]
    assert "latest live product release" in result["answer"]


@pytest.mark.parametrize("question", ["what is the next problem we are facing", "upcoming challenges", "current blockers"])
def test_challenge_questions_use_historical_context_without_inventing_open_issues(client, question):
    sign_in(client)
    result = client.post("/api/chat", json={"question": question}).json()
    assert result["mode"] == "Recorded status + source context"
    assert "No current open issue" in result["answer"]
    assert "not confirmed live problems" in result["answer"]
    assert result["citations"]


def test_real_recorded_issues_override_historical_concerns(client):
    sign_in(client, "alex")
    for title, status, priority in [("Expired test certificate", "Open", "Critical"),
                                    ("Old resolved issue", "Resolved", "Normal")]:
        client.post("/api/records", json={"title": title, "body": "Authentication testing needs a valid certificate.",
                                         "kind": "Issue", "status": status, "priority": priority})
    result = client.post("/api/chat", json={"question": "upcoming challenges"}).json()
    assert "Expired test certificate" in result["answer"]
    assert "Old resolved issue" not in result["answer"]
    assert result["citations"][0]["type"] == "record"


def test_conversation_preserves_subject_across_multiple_turns_and_reset(client):
    sign_in(client, "alex")
    response = client.post("/api/upload", files={"file": ("aurora.txt",
        b"Project Aurora development began on 2021-06-15. Its architecture uses a queue and workers.")},
        data={"title": "Project Aurora \u00b7 Architecture", "visibility": "private"})
    assert response.status_code == 200
    client.post("/api/chat", json={"question": "Explain Project Aurora architecture"})
    for question in ["when did it start", "when did development begin"]:
        result = client.post("/api/chat", json={"question": question}).json()
        assert "2021-06-15" in result["answer"]
        assert "2023-03-27" not in result["answer"]
    assert client.post("/api/chat/reset").status_code == 200
    result = client.post("/api/chat", json={"question": "when did it start"}).json()
    assert "2021-06-15" not in result["answer"]


def test_context_does_not_cross_users_or_expose_private_sources(client):
    sign_in(client, "alex")
    client.post("/api/upload", files={"file": ("private.txt",
        b"Project Zircon development began on 2020-02-01. This is private project evidence.")},
        data={"title": "Project Zircon \u00b7 Development", "visibility": "private"})
    client.post("/api/chat", json={"question": "When did Project Zircon development begin?"})
    sign_in(client, "jordan")
    result = client.post("/api/chat", json={"question": "when did it start"}).json()
    assert "2020-02-01" not in result["answer"]
    assert "Zircon" not in result["answer"]


def test_launch_and_development_are_different_questions(client):
    sign_in(client)
    launch = client.post("/api/chat", json={"question": "When did it become generally available?"}).json()
    assert "October 5, 2023" in launch["answer"]
    development = client.post("/api/chat", json={"question": "When did development start?"}).json()
    assert "do not establish when development" in development["answer"]


def test_semantic_cache_reuses_existing_vectors(tmp_path, monkeypatch):
    import numpy as np
    model_dir = tmp_path / "models"
    (model_dir / "embeddings").mkdir(parents=True)
    (model_dir / "embeddings/config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server.ai, "MODEL_DIR", model_dir)
    monkeypatch.setenv("QUFO_DATA", str(tmp_path / "cache"))
    class Encoder:
        calls = 0
        def encode(self, texts, **kwargs):
            self.calls += 1
            return np.array([[len(t), 1, 0] for t in texts], dtype=np.float32)
    encoder = Encoder()
    monkeypatch.setattr(server.ai, "_encoder", encoder)
    first = server.ai.embeddings(["one", "longer"])
    second = server.ai.embeddings(["longer", "one"])
    assert encoder.calls == 1
    assert np.array_equal(first[0], second[1])


def test_official_document_exports_preserve_license_and_attribution(client):
    sign_in(client)
    doc = client.get("/api/workspace").json()["documents"][0]["id"]
    with server.db() as c:
        c.execute("INSERT INTO doc_metadata VALUES(?,?,?,?,?,?,?)",
                  (doc, "official_documentation", "documentation_updated", "MicrosoftDocs/msteams-docs",
                   "pinned-revision", "CC-BY-4.0", "example.md"))
    response = client.post("/api/exports", json={"audience": "Public", "document_ids": [doc], "approved": True})
    assert response.status_code == 200
    assert "Microsoft and contributors" in response.text
    assert "CC-BY-4.0" in response.text
    assert "LICENSE-CODE" in response.text
    assert "pinned-revision" in response.text


@pytest.mark.parametrize("available,preference,expected", [
    (True, "auto", "cuda"), (False, "auto", "cpu"), (True, "cpu", "cpu"), (True, "cuda", "cuda")
])
def test_inference_device_selection(available, preference, expected):
    assert server.ai.choose_device(available, preference) == expected


def test_explicit_cuda_request_does_not_silently_run_on_cpu():
    with pytest.raises(RuntimeError, match="CUDA was requested"):
        server.ai.choose_device(False, "cuda")
    with pytest.raises(ValueError):
        server.ai.choose_device(True, "invalid")


def test_first_setup_generates_unique_private_credentials(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(server, "DB", tmp_path / "fresh.sqlite3")
    monkeypatch.delenv("QUFO_INITIAL_PASSWORD", raising=False)
    server.initialize()
    credentials = json.loads((tmp_path / "initial-credentials.json").read_text())
    assert len(credentials) == 4
    assert len(set(credentials.values())) == 4
    assert all(len(password) >= 24 for password in credentials.values())
    with server.db() as connection:
        for uid, password in credentials.items():
            row = connection.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            assert server.password_hash(password, row["salt"]) == row["hash"]
    server.initialize()
    assert json.loads((tmp_path / "initial-credentials.json").read_text()) == credentials
