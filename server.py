"""QUFO: permission-scoped knowledge, contributions, reports, and cited RAG."""
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

import chat_engine

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

try:
    from . import ai
except ImportError:
    import ai

ROOT = Path(__file__).parent
DATA = Path(os.getenv("QUFO_DATA", str(ROOT / "data")))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "qufo.sqlite3"
IST = timezone(timedelta(hours=5, minutes=30))
ROLES = {"admin", "lead", "employee", "investor"}
AUDIENCES = {"Team lead", "Employees", "Investors", "Clients", "Public"}


def now():
    return datetime.now(IST).isoformat(timespec="seconds")


@contextmanager
def db():
    connection = sqlite3.connect(DB, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def initialize():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT,email TEXT UNIQUE,role TEXT,team TEXT,salt TEXT,hash TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires REAL);
        CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY,title TEXT,text TEXT,owner TEXT REFERENCES users(id),team TEXT,
          visibility TEXT,category TEXT,source_date TEXT,created TEXT,url TEXT,filename TEXT,blob BLOB,hash TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,doc_id TEXT REFERENCES docs(id) ON DELETE CASCADE,position INTEGER,text TEXT);
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,title TEXT,body TEXT,kind TEXT,status TEXT,priority TEXT,
          due TEXT,hours REAL,cost REAL,owner TEXT REFERENCES users(id),team TEXT,visibility TEXT,pinned INTEGER,created TEXT);
        CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),period TEXT,audience TEXT,
          created TEXT,payload TEXT);
        CREATE TABLE IF NOT EXISTS doc_metadata(doc_id TEXT PRIMARY KEY REFERENCES docs(id) ON DELETE CASCADE,
          kind TEXT,date_kind TEXT,repository TEXT,revision TEXT,license TEXT,source_path TEXT);
        CREATE TABLE IF NOT EXISTS chat_context(session_token TEXT PRIMARY KEY REFERENCES sessions(token) ON DELETE CASCADE,
          user_id TEXT REFERENCES users(id),document_ids TEXT,previous_question TEXT);
        CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY,user_id TEXT,created TEXT,audience TEXT,content TEXT);
        """)
        if not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            credentials = {}
            for uid, name, role, team in [
                ("atharv", "Atharv", "admin", "Research"), ("maya", "Maya Chen", "lead", "Research"),
                ("alex", "Alex Morgan", "employee", "Research"), ("jordan", "Jordan Lee", "investor", "Investment"),
            ]:
                password = os.getenv("QUFO_INITIAL_PASSWORD") or secrets.token_urlsafe(18)
                credentials[uid] = password
                salt = secrets.token_hex(16)
                c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?)", (
                    uid, name, f"{uid}@qufo.workspace", role, team, salt, password_hash(password, salt)))
            if not os.getenv("QUFO_INITIAL_PASSWORD"):
                (DB.parent / "initial-credentials.json").write_text(json.dumps(credentials, indent=2), encoding="utf-8")
        if not c.execute("SELECT 1 FROM docs LIMIT 1").fetchone():
            for source in json.loads((ROOT / "sources/teams.json").read_text(encoding="utf-8")):
                insert_doc(c, source["title"], source["text"], "atharv", "Research", "company",
                           source["category"], source["date"], source["url"], "", None)


def split_text(text):
    paragraphs = re.split(r"\n\s*\n", text)
    chunks, current = [], ""
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            # Hard-split giant paragraphs to bound model context.
            for offset in range(0, len(sentence), 900):
                segment = sentence[offset:offset+900]
                if len(current) + len(segment) > 1100:
                    chunks.append(current.strip())
                    current = ""
                current += segment + " "
        if current and len(current) > 450:
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks


def extract_facts(text):
    """Extract explicit document signals without assigning work or inferring deadlines."""
    findings = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = sentence.strip()
        if len(sentence) < 20 or len(sentence) > 1000:
            continue
        if re.search(r"\b(no|not|never|without|doesn't)\b", sentence, re.I):
            continue
        kind = None
        if re.search(r"\b(deadline|due date|due on|due by)\b", sentence, re.I):
            kind = "Deadline"
        elif re.search(r"\b(resolved|fixed|completed|shipped)\b", sentence, re.I):
            kind = "Completion"
        elif re.search(r"\b(blocked|blocker|unresolved|regression)\b", sentence, re.I):
            kind = "Issue"
        elif re.search(r"\b(must|shall|required|requirement)\b", sentence, re.I):
            kind = "Requirement"
        elif re.search(r"\b(decided|decision|approved)\b", sentence, re.I):
            kind = "Decision"
        if not kind:
            continue
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", sentence)
        normalized = []
        for value in dates:
            try:
                datetime.strptime(value, "%Y-%m-%d")
                normalized.append(value)
            except ValueError:
                pass
        findings.append({"kind": kind, "text": sentence, "dates": normalized})
        if len(findings) >= 20:
            break
    return findings


def insert_doc(c, title, text, owner, team, visibility, category, source_date, url, filename, blob):
    digest = hashlib.sha256(text.encode()).hexdigest()
    previous = c.execute("SELECT id FROM docs WHERE hash=? AND owner=? AND visibility=? AND team=?",
                         (digest, owner, visibility, team)).fetchone()
    if previous:
        return previous["id"], True
    uid = secrets.token_hex(12)
    c.execute("INSERT INTO docs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        uid, title, text, owner, team, visibility, category, source_date, now(), url,
        filename, blob, digest, "ready"))
    c.executemany("INSERT INTO chunks VALUES(?,?,?,?)", [
        (f"{uid}-{i}", uid, i+1, chunk) for i, chunk in enumerate(split_text(text))])
    return uid, False


def allowed(item, user):
    return (user["role"] == "admin" or item["owner"] == user["id"] or item["visibility"] == "company"
            or (item["visibility"] == "team" and item["team"] == user["team"]))


def user_session(request: Request):
    token = request.cookies.get("qufo_session", "")
    with db() as c:
        row = c.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>?",
                        (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not row:
        raise HTTPException(401, "Please sign in to your workspace.")
    return dict(row)


def public_user(user):
    return {k: user[k] for k in ("id", "name", "email", "role", "team")}


def accessible(table, user):
    with db() as c:
        rows = [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY created DESC")]
    result = [r for r in rows if allowed(r, user)]
    if table == "docs":
        with db() as c:
            metadata = {r["doc_id"]: dict(r) for r in c.execute("SELECT * FROM doc_metadata")}
        for item in result:
            item["source_kind"] = metadata.get(item["id"], {}).get("kind", "research_note" if item["url"] else "upload")
            item["provenance"] = metadata.get(item["id"], {})
    return result


def validate_visibility(value):
    if value not in {"company", "team", "private"}:
        raise HTTPException(422, "Choose company, team, or private visibility.")


def validate_date(value, optional=False):
    if optional and not value:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "Dates must use YYYY-MM-DD.")


_scheduler_stop = threading.Event()


def scheduler():
    while not _scheduler_stop.wait(30):
        stamp = datetime.now(IST)
        # After 18:00, catch up today's report. Reports are per-user permission scoped.
        if stamp.hour < 18:
            continue
        with db() as c:
            users = [dict(r) for r in c.execute("SELECT * FROM users")]
        for user in users:
            for period in (["daily", "weekly"] if stamp.weekday() == 4 else ["daily"]):
                with db() as c:
                    exists = c.execute("SELECT 1 FROM reports WHERE user_id=? AND period=? AND created LIKE ?",
                                       (user["id"], period, stamp.date().isoformat()+"%")).fetchone()
                if not exists:
                    save_report(user, period, "Team lead" if user["role"] in {"admin", "lead"} else "Employees")


@asynccontextmanager
async def lifespan(app):
    initialize()
    _scheduler_stop.clear()
    worker = threading.Thread(target=scheduler, daemon=True)
    worker.start()
    yield
    _scheduler_stop.set()


app = FastAPI(title="QUFO · Quick Info", lifespan=lifespan)


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


_attempts = {}


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    host = request.client.host if request.client else "unknown"
    recent = [t for t in _attempts.get(host, []) if t > time.time()-60]
    if len(recent) >= 15:
        raise HTTPException(429, "Too many attempts. Please wait a minute.")
    _attempts[host] = recent + [time.time()]
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE id=? OR email=?",
                        (body.username.lower().strip(), body.username.lower().strip())).fetchone()
        if not row or not secrets.compare_digest(password_hash(body.password, row["salt"]), row["hash"]):
            raise HTTPException(401, "The username or password is incorrect.")
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sessions VALUES(?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(), row["id"], time.time()+86400))
    response.set_cookie("qufo_session", token, httponly=True, samesite="strict", max_age=86400)
    return public_user(dict(row))


@app.post("/api/logout")
def logout(request: Request, response: Response):
    with db() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(request.cookies.get("qufo_session", "").encode()).hexdigest(),))
    response.delete_cookie("qufo_session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(user_session)):
    return public_user(user)


@app.get("/api/health")
def health():
    return {"app": "QUFO", "status": "ready"}


@app.get("/api/workspace")
def workspace(user=Depends(user_session)):
    docs = accessible("docs", user)
    records = accessible("records", user)
    for d in docs:
        d.pop("blob", None)
        d["words"] = len(d["text"].split())
        d["preview"] = d.pop("text")[:230]
    return {"user": public_user(user), "documents": docs, "records": records, "ai": ai.status()}


@app.delete("/api/records/{uid}")
def delete_record(uid: str, user=Depends(user_session)):
    with db() as c:
        row = c.execute("SELECT * FROM records WHERE id=?", (uid,)).fetchone()
        if not row or (row["owner"] != user["id"] and user["role"] != "admin"):
            raise HTTPException(404, "Contribution not found or not owned by you.")
        c.execute("DELETE FROM records WHERE id=?", (uid,))
        c.execute("DELETE FROM reports")
        c.execute("DELETE FROM exports")
    return {"ok": True}


@app.get("/api/documents/{uid}")
def document(uid: str, user=Depends(user_session)):
    with db() as c:
        row = c.execute("SELECT * FROM docs WHERE id=?", (uid,)).fetchone()
        if not row or not allowed(row, user):
            raise HTTPException(404, "Document not found.")
        item = dict(row)
        item.pop("blob")
        metadata = c.execute("SELECT * FROM doc_metadata WHERE doc_id=?", (uid,)).fetchone()
        item["provenance"] = dict(metadata) if metadata else {}
        item["findings"] = extract_facts(item["text"])
        item["chunks"] = [dict(r) for r in c.execute("SELECT id,position,text FROM chunks WHERE doc_id=? ORDER BY position", (uid,))]
    visible = [d for d in accessible("docs", user) if d["id"] != uid]
    item["related"] = []
    if visible:
        vectorizer = TfidfVectorizer(stop_words="english")
        try:
            matrix = vectorizer.fit_transform([item["text"]] + [d["text"] for d in visible])
            scores = cosine_similarity(matrix[:1], matrix[1:])[0]
            item["related"] = [{"id": visible[i]["id"], "title": visible[i]["title"],
                                "similarity": round(float(scores[i]), 3)}
                               for i in np.argsort(-scores)[:3] if scores[i] > 0.08]
        except ValueError:
            pass
    return item


@app.get("/api/documents/{uid}/original")
def original(uid: str, user=Depends(user_session)):
    with db() as c:
        row = c.execute("SELECT * FROM docs WHERE id=?", (uid,)).fetchone()
    if not row or not allowed(row, user):
        raise HTTPException(404, "Document not found.")
    if row["blob"] is None:
        return Response(row["text"], media_type="text/plain", headers={"Content-Disposition": "attachment; filename=source-note.txt"})
    return Response(row["blob"], media_type="application/octet-stream",
                    headers={"Content-Disposition": "attachment; filename=document"+Path(row["filename"]).suffix})


@app.delete("/api/documents/{uid}")
def delete_document(uid: str, user=Depends(user_session)):
    with db() as c:
        row = c.execute("SELECT * FROM docs WHERE id=?", (uid,)).fetchone()
        if not row or (row["owner"] != user["id"] and user["role"] != "admin"):
            raise HTTPException(404, "Document not found or not owned by you.")
        c.execute("DELETE FROM docs WHERE id=?", (uid,))
        c.execute("DELETE FROM reports")
        c.execute("DELETE FROM exports")
    return {"ok": True}


def extract(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "Save text files as UTF-8 before uploading.")
    if suffix == ".pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 100:
                raise HTTPException(422, "Please split documents longer than 100 pages.")
            return "\n\n".join(f"Page {i+1}\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "This PDF could not be read. Use an unencrypted, text-based PDF.")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entry = archive.getinfo("word/document.xml")
                if entry.file_size > 10_000_000:
                    raise ValueError("Expanded document too large")
                tree = ElementTree.fromstring(archive.read(entry))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                return "\n\n".join("".join(p.itertext()) for p in tree.findall(".//w:p", ns))
        except Exception:
            raise HTTPException(422, "This Word document could not be read.")
    raise HTTPException(422, "Supported files: PDF, DOCX, TXT, and Markdown.")


@app.post("/api/upload")
def upload(file: UploadFile = File(...), title: str = Form(""), visibility: str = Form("team"),
           category: str = Form("Research"), source_date: str = Form(""), user=Depends(user_session)):
    validate_visibility(visibility)
    content = file.file.read(5_000_001)
    if len(content) > 5_000_000:
        raise HTTPException(413, "Files must be smaller than 5 MB.")
    text = extract(file.filename or "", content).strip()
    if len(text) < 30:
        raise HTTPException(422, "Not enough readable text. Scanned images need OCR before upload.")
    if len(text) > 300_000:
        raise HTTPException(422, "Please split files larger than 300,000 characters.")
    date = source_date or datetime.now(IST).date().isoformat()
    validate_date(date)
    with db() as c:
        uid, duplicate = insert_doc(c, title.strip()[:180] or Path(file.filename).name, text, user["id"],
                                   user["team"], visibility, category[:60], date, "", Path(file.filename).name, content)
    return {"id": uid, "duplicate": duplicate, "status": "ready", "chunks": len(split_text(text))}


class Record(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    body: str = Field(min_length=10, max_length=12000)
    kind: str = "Update"
    status: str = "Open"
    priority: str = "Normal"
    visibility: str = "team"
    due: str = ""
    hours: float = Field(default=0, ge=0, le=100000)
    cost: float = Field(default=0, ge=0, le=1000000000)
    pinned: bool = False


@app.post("/api/records")
def contribute(body: Record, user=Depends(user_session)):
    validate_visibility(body.visibility)
    validate_date(body.due, optional=True)
    if body.kind not in {"Update", "Task", "Issue", "Requirement", "Decision", "Research", "Point"}:
        raise HTTPException(422, "Invalid contribution type.")
    if body.status not in {"Open", "In progress", "Completed", "Resolved"} or body.priority not in {"Normal", "High", "Critical"}:
        raise HTTPException(422, "Invalid status or priority.")
    uid = secrets.token_hex(12)
    with db() as c:
        c.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            uid, body.title, body.body, body.kind, body.status, body.priority, body.due, body.hours, body.cost,
            user["id"], user["team"], body.visibility, int(body.pinned), now()))
    return {"id": uid}


@app.patch("/api/records/{uid}")
def update_record(uid: str, body: Record, user=Depends(user_session)):
    validate_visibility(body.visibility)
    validate_date(body.due, optional=True)
    if body.status not in {"Open", "In progress", "Completed", "Resolved"} or body.priority not in {"Normal", "High", "Critical"}:
        raise HTTPException(422, "Invalid status or priority.")
    with db() as c:
        row = c.execute("SELECT * FROM records WHERE id=?", (uid,)).fetchone()
        if not row or (row["owner"] != user["id"] and not (user["role"] in {"admin", "lead"} and allowed(row, user))):
            raise HTTPException(404, "Contribution not found or not editable by you.")
        c.execute("UPDATE records SET title=?,body=?,status=?,priority=?,due=?,hours=?,cost=?,visibility=?,pinned=? WHERE id=?",
                  (body.title, body.body, body.status, body.priority, body.due, body.hours, body.cost, body.visibility, int(body.pinned), uid))
        c.execute("DELETE FROM reports")
        c.execute("DELETE FROM exports")
    return {"id": uid}


def retrieve(question, user, document_ids=None):
    # Expand technical acronyms and ordinary paraphrases before both retrieval stages.
    question = re.sub(r"\bIPC\b", "IPC inter-process communication", question)
    question = re.sub(r"\bSSO\b", "SSO single sign-on authentication", question, flags=re.I)
    question = re.sub(r"\bmeeting join\b", "meeting join joining meetings", question, flags=re.I)
    docs = {d["id"]: d for d in accessible("docs", user)}
    if document_ids is not None:
        docs = {uid: doc for uid, doc in docs.items() if uid in document_ids}
    with db() as c:
        chunks = [dict(r) for r in c.execute("SELECT * FROM chunks") if r["doc_id"] in docs]
    items = [{"id": c["id"], "document_id": c["doc_id"], "title": docs[c["doc_id"]]["title"],
              "text": c["text"], "position": c["position"], "date": docs[c["doc_id"]]["source_date"],
              "url": docs[c["doc_id"]]["url"], "type": "document"} for c in chunks]
    for r in accessible("records", user):
        items.append({"id": r["id"], "document_id": None, "title": r["title"],
                      "text": f"{r['kind']}: {r['body']} Status: {r['status']}. Priority: {r['priority']}. "
                              f"Deadline: {r['due'] or 'not recorded'}. Hours: {r['hours']}. Cost: {r['cost']}.",
                      "date": r["created"][:10], "url": "", "position": 1, "type": "record"})
    if not items:
        return [], "keyword"
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    try:
        matrix = vectorizer.fit_transform([i["title"]+" "+i["text"] for i in items])
        lexical = cosine_similarity(vectorizer.transform([question]), matrix)[0]
    except ValueError:
        return [], "keyword"
    tokens = set(re.findall(r"[a-zA-Z]{3,}", question.lower())) - ENGLISH_STOP_WORDS - {"teams", "microsoft", "qufo", "please", "explain", "tell", "detail", "detailed", "documents"}
    # Lexical anchors prevent unrelated questions from becoming plausible semantic matches.
    if tokens and not any(tokens & set(re.findall(r"[a-zA-Z]{3,}", i["text"].lower())) for i in items):
        return [], "keyword"
    score = lexical.copy()
    mode = "keyword"
    try:
        vectors = ai.embeddings([question] + [i["text"] for i in items])
        if vectors is not None:
            semantic = np.dot(vectors[1:], vectors[0])
            score = 0.55 * lexical + 0.45 * np.maximum(semantic, 0)
            mode = "hybrid semantic + keyword"
    except Exception:
        mode = "keyword"
    q = question.lower()
    for i, item in enumerate(items):
        content = item["text"].lower()
        category = docs.get(item["document_id"], {}).get("category", "")
        if "inter-process communication" in q and "inter-process communication" in content:
            score[i] += 0.22
        performance_query = re.search(r"performance|memory consumption|twice as fast|launch.*(problem|target)|launch.*meeting.*(problem|target)", q)
        if performance_query and category == "Performance":
            score[i] += 0.15
    ranking = np.argsort(-score)
    selected, counts = [], {}
    for index in ranking:
        item = items[index]
        key = item["document_id"] or item["id"]
        if score[index] < 0.06 or counts.get(key, 0) >= 2:
            continue
        counts[key] = counts.get(key, 0) + 1
        selected.append({**item, "score": round(float(score[index]), 3)})
        if len(selected) == 4:
            break
    return selected, mode


def align_citations(answer, evidence):
    """Lexical evidence alignment, not a semantic guarantee; sources remain visible."""
    if not answer or len(answer) < 40:
        return None
    segments = [re.sub(r"\[\d+\]", "", line).strip()
                for line in re.split(r"\n+", answer) if len(line.strip()) > 12]
    output = []
    for segment in segments:
        vectorizer = TfidfVectorizer(stop_words="english")
        try:
            matrix = vectorizer.fit_transform([e["text"] for e in evidence] + [segment])
        except ValueError:
            return None
        scores = cosine_similarity(matrix[-1:], matrix[:-1])[0]
        def terms(value):
            words = set(re.findall(r"[a-z]{3,}", value.lower())) - ENGLISH_STOP_WORDS
            return {w[:5] if len(w) > 5 else w for w in words}
        query_terms = terms(segment)
        coverage = np.array([len(query_terms & terms(e["text"])) / max(1, len(query_terms)) for e in evidence])
        combined = 0.4 * scores + 0.6 * coverage
        best = int(np.argmax(combined))
        # Short statements still need matching content terms, not just shared company names.
        if combined[best] < 0.25 or coverage[best] < 0.3:
            if len(segment.split()) < 10:
                continue
            return None
        source_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", evidence[best]["text"]))
        if not set(re.findall(r"\b\d+(?:\.\d+)?\b", segment)).issubset(source_numbers):
            return None
        output.append(f"{segment} [{best+1}]")
    return "\n\n".join(output) if output else None


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    audience: str = "Team lead"
    previous_question: str = Field(default="", max_length=1500)


@app.post("/api/chat/reset")
def reset_chat(request: Request, user=Depends(user_session)):
    token = hashlib.sha256(request.cookies.get("qufo_session", "").encode()).hexdigest()
    with db() as c:
        c.execute("DELETE FROM chat_context WHERE session_token=? AND user_id=?", (token, user["id"]))
    return {"ok": True}


@app.post("/api/chat")
def chat(body: Question, request: Request, user=Depends(user_session)):
    if body.audience not in AUDIENCES:
        raise HTTPException(422, "Invalid audience.")
    token = hashlib.sha256(request.cookies.get("qufo_session", "").encode()).hexdigest()
    with db() as c:
        saved = c.execute("SELECT * FROM chat_context WHERE session_token=? AND user_id=?", (token, user["id"])).fetchone()
    visible_docs = accessible("docs", user)
    visible_records = accessible("records", user)
    context_ids = json.loads(saved["document_ids"]) if saved else []
    previous = body.previous_question or (saved["previous_question"] if saved else "")
    scoped, topic = chat_engine.resolve_scope(body.question, visible_docs, context_ids)
    resolved_ids = [d["id"] for d in scoped]
    response = chat_engine.answer_intent(body.question, visible_docs, visible_records, context_ids)
    if response is None:
        question = body.question
        is_followup = bool(re.search(r"\b(it|they|those|that|this|more|also|why|how so)\b", question, re.I))
        if is_followup and previous:
            question = previous[:500] + "\nFollow-up: " + question
        if topic and (is_followup or len(body.question.split()) < 7):
            question = f"Topic: {topic}. " + question
        evidence, retrieval = retrieve(question, user, resolved_ids if scoped else None)
        if not evidence:
            response = {"answer": "I couldn't find supporting information in the records you can access. "
                        "The collection may not cover this question; tell me which project or add a relevant source.",
                        "citations": [], "mode": "Insufficient evidence", "retrieval": retrieval, "notice": ""}
        else:
            answer, error = None, False
            try:
                answer = ai.generate(question, evidence, body.audience)
            except Exception:
                error = True
            answer = align_citations(answer, evidence[:2])
            if answer:
                mode = "AI synthesis · verify against evidence"
                evidence = evidence[:2]
            else:
                answer = "\n\n".join(f"{e['text']} [{i+1}]" for i, e in enumerate(evidence))
                mode = "Source excerpts"
            response = {"answer": answer, "citations": evidence, "mode": mode, "retrieval": retrieval,
                        "notice": "The language model could not complete this request; source excerpts are shown." if error else ""}
    used = [e["document_id"] for e in response["citations"] if e.get("document_id")]
    retained = sorted(set(resolved_ids or used))
    if retained:
        with db() as c:
            c.execute("INSERT OR REPLACE INTO chat_context VALUES(?,?,?,?)",
                      (token, user["id"], json.dumps(retained), body.question))
    response["topic"] = topic or ""
    return response


def report(user, period="all", audience="Team lead", start="", end=""):
    docs, records = accessible("docs", user), accessible("records", user)
    today = datetime.now(IST).date()
    if period in {"daily", "weekly"}:
        start = (today - timedelta(days=0 if period == "daily" else 6)).isoformat()
        end = today.isoformat()
    if start:
        docs = [d for d in docs if start <= d["source_date"] <= (end or "9999")]
        records = [r for r in records if start <= r["created"][:10] <= (end or "9999")]
    ranked = sorted(records, key=lambda r: (r["pinned"], {"Critical": 3, "High": 2, "Normal": 1}[r["priority"]]), reverse=True)
    highlights = [{"title": r["title"], "text": r["body"], "id": r["id"], "type": "record",
                   "reason": "Pinned by contributor" if r["pinned"] else f"Recorded priority: {r['priority']}"} for r in ranked[:4]]
    highlights += [{"title": d["title"], "text": " ".join(re.split(r"(?<=[.!?])\s+", d["text"])[:2]),
                    "id": d["id"], "type": "document", "reason": f"{d['category']} · source dated {d['source_date']}"}
                   for d in sorted(docs, key=lambda d: (
                       {"Team lead": {"Architecture": 3, "Milestone": 4},
                        "Employees": {"Architecture": 4, "Security": 3},
                        "Investors": {"Performance": 4, "Milestone": 3},
                        "Clients": {"Milestone": 4, "Security": 3},
                        "Public": {"Milestone": 4, "Performance": 3}}[audience].get(d["category"], 1),
                       d["source_date"]), reverse=True)[:max(0, 4-len(highlights))]]
    timeline = [{"date": d["source_date"], "title": d["title"], "id": d["id"], "type": "document"} for d in docs]
    timeline += [{"date": r["due"] or r["created"][:10], "title": r["title"], "id": r["id"], "type": "record"} for r in records]
    focus = {"Team lead": "Delivery, blockers, decisions, and recorded priorities.",
             "Employees": "Work updates, requirements, deadlines, and relevant technical context.",
             "Investors": "Documented milestones, business context, and recorded costs. No speculative ROI.",
             "Clients": "Documented capabilities, delivery milestones, and limitations.",
             "Public": "Source-attributed developments suitable for a reviewer to consider for sharing."}[audience]
    return {"audience": audience, "focus": focus, "period": period, "start": start, "end": end,
            "generated": now(), "highlights": highlights, "timeline": sorted(timeline, key=lambda t: t["date"]),
            "tasks": [r for r in ranked if r["kind"] == "Task"], "issues": [r for r in ranked if r["kind"] == "Issue"],
            "decisions": [r for r in ranked if r["kind"] in {"Decision", "Requirement", "Research", "Point"}],
            "completed": [r for r in ranked if r["status"] in {"Completed", "Resolved"}],
            "pinned": [r for r in ranked if r["pinned"]],
            "hours": sum(r["hours"] for r in records), "cost": sum(r["cost"] for r in records),
            "has_time": any(r["hours"] > 0 for r in records), "has_cost": any(r["cost"] > 0 for r in records),
            "document_findings": [{**fact, "id": d["id"], "title": d["title"], "type": "document"}
                                  for d in docs for fact in extract_facts(d["text"])],
            "doc_count": len(docs), "record_count": len(records),
            "categories": {category: sum(d["category"] == category for d in docs) for category in sorted({d["category"] for d in docs})}}


def save_report(user, period, audience):
    result = report(user, period, audience)
    with db() as c:
        c.execute("INSERT INTO reports VALUES(?,?,?,?,?,?)", (secrets.token_hex(12), user["id"], period, audience, now(), json.dumps(result)))
    return result


@app.get("/api/report")
def get_report(period: str = "all", audience: str = "Team lead", start: str = "", end: str = "", user=Depends(user_session)):
    if audience not in AUDIENCES or period not in {"all", "daily", "weekly", "custom"}:
        raise HTTPException(422, "Invalid report selection.")
    if period == "custom" and (not start or not end):
        raise HTTPException(422, "Select both a start and end date for a custom report.")
    validate_date(start, optional=True)
    validate_date(end, optional=True)
    if start and end and start > end:
        raise HTTPException(422, "The start date must precede the end date.")
    return report(user, period, audience, start, end)


@app.get("/api/report-history")
def report_history(user=Depends(user_session)):
    with db() as c:
        rows = c.execute("SELECT id,period,audience,created FROM reports WHERE user_id=? ORDER BY created DESC LIMIT 20",
                         (user["id"],)).fetchall()
    return [dict(r) for r in rows]


class ExportRequest(BaseModel):
    audience: str
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    record_ids: list[str] = Field(default_factory=list, max_length=100)
    approved: bool = False


@app.post("/api/exports")
def export_report(body: ExportRequest, user=Depends(user_session)):
    if user["role"] not in {"lead", "admin"}:
        raise HTTPException(403, "A team lead or administrator must approve external exports.")
    if body.audience not in AUDIENCES or not body.approved:
        raise HTTPException(422, "Review the selected material and approve this export.")
    docs = {d["id"]: d for d in accessible("docs", user)}
    records = {r["id"]: r for r in accessible("records", user)}
    if not (body.document_ids or body.record_ids):
        raise HTTPException(422, "Select at least one item to export.")
    if any(uid not in docs for uid in body.document_ids) or any(uid not in records for uid in body.record_ids):
        raise HTTPException(404, "Some selected material is unavailable.")
    text = f"# QUFO · {body.audience} briefing\n\nApproved by {user['name']} · {now()}\n\n"
    for uid in body.document_ids:
        d = docs[uid]
        text += f"## {d['title']}\n\n{d['text']}\n\nSource: {d['url'] or d['filename']} · {d['source_date']}\n\n"
        provenance = d.get("provenance", {})
        if provenance.get("kind") == "official_documentation":
            upstream = f"https://github.com/{provenance['repository']}/blob/{provenance['revision']}"
            text += ("Attribution: Microsoft and contributors. Documentation license: "
                     "CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/). "
                     "Search-text changes: front matter and comments removed; image markup replaced by alt text. "
                     f"Original revision: {provenance['revision']}. "
                     f"Embedded code examples: MIT; see {upstream}/LICENSE-CODE.\n\n")
    for uid in body.record_ids:
        r = records[uid]
        text += f"## {r['title']}\n\n{r['body']}\n\nStatus: {r['status']} · Priority: {r['priority']} · Owner: {r['owner']}\n\n"
    with db() as c:
        c.execute("INSERT INTO exports VALUES(?,?,?,?,?)", (secrets.token_hex(12), user["id"], now(), body.audience, text))
    return Response(text, media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=QUFO-briefing.md"})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
