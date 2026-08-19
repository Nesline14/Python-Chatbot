# Python Beginner Learning Assistant

A memory-based chatbot built with Flask that helps Python beginners learn
core concepts. It runs on a local **Ollama** model (`llama3.2:latest`),
remembers conversation history and basic learner info (name, skill level,
topics discussed) per browser session in **SQLite**, and grounds its
answers in a small Python knowledge base (`data.json`).

## Project structure

```
session3/
├── app.py                 # Flask backend, memory + Ollama integration
├── data.json              # Beginner Python knowledge base
├── db.sqlite              # SQLite database (memory, auto-created)
├── requirements.txt       # Python dependencies
├── README.md
└── templates/
    └── index.html         # Landing page + floating chat widget
```

## How it works

1. **Frontend** (`templates/index.html`) — Landing page with a heading,
   description, and clickable example questions. A floating 🤖 icon in the
   bottom-right corner opens the **Python Assistant 🐍** chat window, which
   shows a welcome message, a typing indicator ("Python Assistant is
   typing..."), and lets you send messages with Enter or the send button.
2. **Backend** (`app.py`):
   - Uses a Flask session cookie to track a `session_id` per browser, with
     no login required.
   - Matches the user's message against `data.json` with simple keyword
     matching to pull in relevant topic explanations/examples.
   - Picks up basic learner info from the message (name, self-reported
     skill level, topics asked about) and stores it in `user_profile`.
   - Pulls recent conversation turns for that session out of
     `conversations` — this is the chatbot's memory.
   - Builds a system prompt (tutor instructions + learner profile +
     knowledge-base context + conversation history + new message) and
     sends it to Ollama's `/api/chat` endpoint using `llama3.2:latest`.
   - Saves the new turn back into `db.sqlite` and returns the reply as
     JSON.
3. **Knowledge base** (`data.json`) — Covers Variables, Data Types, Lists,
   Tuples, Dictionaries, Sets, Conditions, Loops, Functions, Classes and
   Objects, File Handling, Exception Handling, Modules, and Basic Python
   Programs — each with a `description` and a short code `example`.

## Setup

### 1. Install and start Ollama

Download from [ollama.com](https://ollama.com), then pull the model:

```bash
ollama pull llama3.2:latest
ollama serve
```

`ollama serve` needs to be running before you start the chatbot — the
backend calls it at `http://localhost:11434/api/chat`.

### 2. Install Python dependencies

From inside the `session3/` folder:

```bash
pip install -r requirements.txt
```

`sqlite3` is part of Python's standard library, so no separate install is
needed for it.

### 3. Run the app

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

`db.sqlite` is created automatically on first run if it doesn't already
exist — `init_db()` creates the `conversations` and `user_profile` tables
at startup. You can keep the pre-initialized file shipped with this
project or delete it and let the app regenerate a fresh, empty one.

## API endpoints

| Method | Route    | Purpose                                             |
|--------|----------|------------------------------------------------------|
| GET    | `/`      | Renders the landing page + chat widget                |
| POST   | `/chat`  | Sends a message, returns the tutor's reply as JSON     |

**`POST /chat`** request body:
```json
{ "message": "What is a variable in Python?" }
```

Response:
```json
{
  "reply": "...",
  "matched_topics": ["Variables"]
}
```

If the message is empty, or Ollama isn't reachable, or the model isn't
installed, the endpoint returns a clear error/explanatory message instead
of crashing.

## Customizing

- **Add Python topics** — append new entries to `data.json` following the
  existing structure (`topic`, `keywords`, `description`, `example`).
- **Change the model** — edit `MODEL_NAME` in `app.py`.
- **Adjust memory depth** — edit `MEMORY_TURNS` in `app.py` (defaults to
  the last 8 exchanges per session).
- **Styling** — all widget and page styling lives in
  `templates/index.html` (`<style>` block), no separate CSS file.

## Troubleshooting

- **"I can't reach the Ollama server"** — make sure `ollama serve` is
  running and that `llama3.2:latest` has been pulled (`ollama list` to
  check).
- **"The model doesn't seem to be installed"** — run
  `ollama pull llama3.2:latest`.
- **Chat doesn't remember earlier messages** — this relies on the Flask
  session cookie; make sure cookies aren't being blocked by the browser,
  and that `db.sqlite` isn't being deleted between requests.
- **Port already in use** — change `app.run(debug=True, port=5000)` in
  `app.py` to a free port.
