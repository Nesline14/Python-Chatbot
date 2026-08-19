"""
Python Beginner Learning Assistant
-----------------------------------
A memory-based chatbot built with Flask that helps Python beginners.
It uses a local Ollama model (llama3.2:latest) to generate answers,
SQLite (db.sqlite) to remember conversation history and basic user
info (name, skill level, topics learned) across messages, and a small
JSON knowledge base (data.json) covering core beginner Python topics.

Run:
    cd session3
    pip install flask requests
    ollama pull llama3.2:latest
    ollama serve
    python app.py

Then open http://127.0.0.1:5000 in your browser.

db.sqlite does NOT need to exist beforehand — init_db() creates it and
all required tables automatically on startup if they are missing.
"""

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, g, jsonify, render_template, request, session

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite"
DATA_PATH = BASE_DIR / "data.json"

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "llama3.2:latest"

MEMORY_TURNS = 8  # number of previous user+assistant pairs to recall

app = Flask(__name__)
app.secret_key = "python-beginner-assistant-dev-secret"  # change in production

# --------------------------------------------------------------------------
# Knowledge base (data.json)
# --------------------------------------------------------------------------
try:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        PYTHON_TOPICS = json.load(f).get("python_topics", [])
except (FileNotFoundError, json.JSONDecodeError):
    PYTHON_TOPICS = []


def find_relevant_topics(user_message: str, limit: int = 2):
    """Simple keyword-based lookup of relevant topics in data.json."""
    msg = user_message.lower()
    scored = []
    for topic in PYTHON_TOPICS:
        score = sum(1 for kw in topic.get("keywords", []) if kw in msg)
        if topic["topic"].lower() in msg:
            score += 2
        if score > 0:
            scored.append((score, topic))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:limit]]


def build_knowledge_context(topics):
    if not topics:
        return ""
    lines = ["Relevant knowledge-base entries you can use in your answer:"]
    for t in topics:
        lines.append(f"\n### {t['topic']}")
        lines.append(t["description"])
        lines.append("Example:\n" + t["example"])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Database (memory: conversation history + basic user profile)
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create db.sqlite and required tables if they don't already exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,            -- 'user' or 'assistant'
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profile (
            session_id TEXT PRIMARY KEY,
            name TEXT,
            skill_level TEXT,
            topics_learning TEXT,          -- comma-separated list
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_message(session_id: str, role: str, message: str):
    db = get_db()
    db.execute(
        "INSERT INTO conversations (session_id, role, message, created_at) VALUES (?, ?, ?, ?)",
        (session_id, role, message, datetime.utcnow().isoformat()),
    )
    db.commit()


def get_history(session_id: str, limit: int = MEMORY_TURNS * 2):
    db = get_db()
    rows = db.execute(
        "SELECT role, message FROM conversations WHERE session_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    rows = list(reversed(rows))  # chronological order
    return [{"role": r["role"], "content": r["message"]} for r in rows]


def get_profile(session_id: str):
    db = get_db()
    row = db.execute(
        "SELECT * FROM user_profile WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row:
        return dict(row)
    return {
        "session_id": session_id,
        "name": None,
        "skill_level": None,
        "topics_learning": "",
    }


def update_profile(session_id: str, **fields):
    """Upsert basic user info (name, skill_level, topics_learning)."""
    profile = get_profile(session_id)
    for key, value in fields.items():
        if value:
            if key == "topics_learning":
                existing = set(
                    t.strip() for t in (profile.get("topics_learning") or "").split(",") if t.strip()
                )
                existing.update(value)
                profile["topics_learning"] = ", ".join(sorted(existing))
            else:
                profile[key] = value

    db = get_db()
    db.execute(
        """
        INSERT INTO user_profile (session_id, name, skill_level, topics_learning, updated_at)
        VALUES (:session_id, :name, :skill_level, :topics_learning, :updated_at)
        ON CONFLICT(session_id) DO UPDATE SET
            name = excluded.name,
            skill_level = excluded.skill_level,
            topics_learning = excluded.topics_learning,
            updated_at = excluded.updated_at
        """,
        {
            "session_id": session_id,
            "name": profile.get("name"),
            "skill_level": profile.get("skill_level"),
            "topics_learning": profile.get("topics_learning") or "",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )
    db.commit()


NAME_PATTERN = re.compile(r"\bmy name is ([A-Za-z]+)\b", re.IGNORECASE)
SKILL_PATTERN = re.compile(r"\bi(?:'m| am) (?:a |an )?(beginner|intermediate|advanced|expert)\b", re.IGNORECASE)


def extract_profile_updates(user_message: str, matched_topics):
    """Very lightweight heuristics to capture name / skill level / topics."""
    updates = {}

    name_match = NAME_PATTERN.search(user_message)
    if name_match:
        updates["name"] = name_match.group(1).capitalize()

    skill_match = SKILL_PATTERN.search(user_message)
    if skill_match:
        updates["skill_level"] = skill_match.group(1).lower()

    if matched_topics:
        updates["topics_learning"] = [t["topic"] for t in matched_topics]

    return updates


def build_profile_context(profile):
    parts = []
    if profile.get("name"):
        parts.append(f"The user's name is {profile['name']}.")
    if profile.get("skill_level"):
        parts.append(f"The user's self-reported skill level is {profile['skill_level']}.")
    if profile.get("topics_learning"):
        parts.append(f"Topics this user has previously asked about: {profile['topics_learning']}.")
    if not parts:
        return ""
    return "What you know about this learner: " + " ".join(parts)


# --------------------------------------------------------------------------
# System prompt
# --------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are 'Python Assistant', a friendly tutor built specifically to help "
    "complete beginners learn Python. Always explain concepts in simple, "
    "plain language, avoid unnecessary jargon, and include a short, correct "
    "Python code example whenever it helps. You can help with variables, "
    "data types, lists, tuples, dictionaries, sets, conditions, loops, "
    "functions, classes and objects, file handling, exception handling, "
    "modules, and basic beginner programs. If the learner's message is "
    "unrelated to Python, gently steer the conversation back to helping "
    "them learn Python. Keep answers concise but complete, and encourage "
    "the learner as they go."
)


# --------------------------------------------------------------------------
# Ollama integration
# --------------------------------------------------------------------------
class OllamaError(Exception):
    pass


def call_ollama(messages):
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": MODEL_NAME, "messages": messages, "stream": False},
            timeout=120,
        )
    except requests.exceptions.ConnectionError as exc:
        raise OllamaError(
            "I can't reach the Ollama server. Please make sure Ollama is "
            "installed and running locally (`ollama serve`)."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise OllamaError("The request to Ollama timed out. Please try again.") from exc

    if resp.status_code == 404:
        raise OllamaError(
            f"The model '{MODEL_NAME}' doesn't seem to be installed. "
            f"Run `ollama pull {MODEL_NAME}` and try again."
        )
    if resp.status_code >= 400:
        raise OllamaError(f"Ollama returned an error (status {resp.status_code}).")

    try:
        data = resp.json()
    except ValueError as exc:
        raise OllamaError("Received an unexpected response from Ollama.") from exc

    content = data.get("message", {}).get("content", "").strip()
    if not content:
        raise OllamaError("Ollama returned an empty response. Please try again.")
    return content


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty."}), 400

    # Session-based memory: one session id per browser session cookie
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    matched_topics = []
    try:
        matched_topics = find_relevant_topics(user_message)
        knowledge_context = build_knowledge_context(matched_topics)

        profile_updates = extract_profile_updates(user_message, matched_topics)
        if profile_updates:
            update_profile(session_id, **profile_updates)
        profile = get_profile(session_id)
        profile_context = build_profile_context(profile)

        history = get_history(session_id)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if profile_context:
            messages.append({"role": "system", "content": profile_context})
        if knowledge_context:
            messages.append({"role": "system", "content": knowledge_context})
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        reply = call_ollama(messages)

    except OllamaError as exc:
        reply = str(exc)
    except sqlite3.Error:
        return jsonify({"error": "A database error occurred. Please try again."}), 500
    except Exception as exc:  # noqa: BLE001
        reply = f"Something unexpected went wrong: {exc}"

    # Persist the turn regardless of whether it was a successful model reply,
    # so the conversation stays coherent on the next message.
    try:
        save_message(session_id, "user", user_message)
        save_message(session_id, "assistant", reply)
    except sqlite3.Error:
        pass

    return jsonify(
        {
            "reply": reply,
            "matched_topics": [t["topic"] for t in matched_topics],
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)