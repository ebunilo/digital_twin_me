# My Digital Twin

A small **Gradio** chat app that uses **OpenAI** function calling to role-play a “digital twin” from **YAML profile documents** under `me/`. **Pushover** delivers notifications when someone leaves contact details or asks something the profile does not cover.

---

## Application (`app.py`)

The program lives in [`app.py`](app.py). This section describes how it behaves end to end.

### Purpose

Visitors chat in a browser. The model answers as the person described in your profile data:

- **Display name** comes from the YAML file whose root has `document_type: profile_summary` and a `name` field (e.g. [`me/profile_summary.yml`](me/profile_summary.yml)). If none is found, the app falls back to the string **`this person`**.
- **Context** is built from **every** `*.yml` / `*.yaml` file in `me/`: each file is loaded with `yaml.safe_load`, then dumped back as readable YAML text and concatenated into a single “structured profile documents” block in the system prompt.

There is **no PDF or plain-text summary file** in the current pipeline—the profile is entirely YAML on disk.

The assistant is told to treat those documents as the **sole source of truth**, stay in character, nudge toward email when it fits, and follow strict rules around **`record_unknown_question`** when an answer is not in the docs.

### Stack

| Piece | Role |
|--------|------|
| [Gradio](https://www.gradio.app/) | `gr.ChatInterface(me.chat)` — chat UI and HTTP server |
| [OpenAI API](https://platform.openai.com/docs) | `OpenAI()` client; chat completions with **tools** (`parallel_tool_calls=False`) |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Loads `.env` at startup (`load_dotenv(override=True)`) |
| [PyYAML](https://pyyaml.org/) | Loads and re-serializes profile files under `me/` |
| [requests](https://requests.readthedocs.io/) | `POST` to **Pushover** when tools run |

### Startup and data loading

1. Environment variables are loaded from `.env`.
2. Constructing `Me()` runs `_load_me_yaml_chunks(ME_DIR)` where `ME_DIR` is the `me/` folder next to `app.py`:
   - Collects `me/*.yml` and `me/*.yaml` (sorted).
   - Raises **`FileNotFoundError`** if there are no such files.
   - Sets **`self.name`** from the first dict with `document_type == "profile_summary"` and a non-empty `name` string; otherwise **`this person`**.
   - Sets **`self.structured_context`** to all files combined (each introduced by a `### filename` header), separated by horizontal rules.

### Chat flow (`Me.chat`)

`Me.chat` is a **generator**: Gradio’s **`ChatInterface`** treats it as a streaming handler and updates the assistant bubble as each prefix is yielded.

Gradio passes `(message, history)`. History is normalized with **`Me._history_to_messages`**: either already OpenAI-style `{"role","content"}` dicts, or legacy **`[user, assistant]`** pairs per turn.

1. Build `messages`: system prompt, prior turns, then the new user message.
2. Loop:
   - **`_stream_collect_one_completion`** calls `chat.completions.create(..., stream=True)` and reads the full stream for that round (tool-call deltas are merged by index before any JSON is parsed).
   - On **`tool_calls`**, run **`handle_tool_call`**, append the assistant message (with `tool_calls`) and tool results to `messages`, then repeat. **No text is yielded** during these rounds (they are usually tool-only).
   - On **`stop`** (or other non-tool finish), take the assembled assistant **`content`**, apply the **`_assistant_admits_missing_docs`** fallback if needed, then **`yield from _yield_stream_chunks`** so the reply appears progressively in the UI (the API response is buffered per round first so tool vs. text is unambiguous).
3. **Fallback:** If the model never called **`record_unknown_question`** but the final assistant text looks like “no information in the profile” (see **`_assistant_admits_missing_docs`** heuristics), the app calls **`record_unknown_question(user_question)`** once so you still get a Pushover ping.

### OpenAI tools (function calling)

| Tool | Role |
|------|------|
| `record_user_details` | After the user shares email (and optionally name/notes) |
| `record_unknown_question` | When the answer is not in the structured docs; the system prompt requires a tool-only turn first in that case |

Both invoke **`push(text)`**, which posts to Pushover’s **`messages.json`** API using **`PUSHOVER_TOKEN`** and **`PUSHOVER_USER`**. Set both in `.env` if you want notifications; otherwise tool calls may hit the API with empty credentials.

### System prompt (`Me.system_prompt`)

Instructs the model to act as **`self.name`**, use only the structured profile block as truth, follow **mandatory** `record_unknown_question` behavior when information is missing, and use **`record_user_details`** when steering toward contact by email.

### Gradio server (`if __name__ == "__main__"`)

```text
gr.ChatInterface(me.chat).launch()
```

Uses Gradio’s defaults for bind address and port (typically **`127.0.0.1:7860`** locally). For Docker or a cloud VM you usually need the UI to listen on all interfaces—e.g. **`launch(server_name="0.0.0.0", server_port=7860)`**—or equivalent reverse proxy setup.

### Environment variables used by `app.py`

| Variable | Required | Used for |
|----------|----------|----------|
| `OPENAI_API_KEY` | Yes (for real API calls) | OpenAI client authentication |
| `PUSHOVER_TOKEN` | For Pushover notifications | Pushover application token |
| `PUSHOVER_USER` | For Pushover notifications | Pushover user key |

### Required files (besides `app.py`)

| Path | Role |
|------|------|
| `me/*.yml` / `me/*.yaml` | At least one file; together they define the twin’s context. Prefer one `profile_summary` document with `name` for the persona label. |

### Customizing the twin

- **Name:** edit the `profile_summary` YAML (`name` / `document_type`) or change fallback logic in **`_load_me_yaml_chunks`**.
- **Model:** change `model="gpt-4o-mini"` in **`Me.chat`**.
- **Profile content:** add or edit YAML files under **`me/`** (loaded automatically by glob).

### Local run

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Ensure me/*.yml exist; set OPENAI_API_KEY and optional PUSHOVER_* in .env
python app.py
```

Open the URL Gradio prints.

---

## Docker (cloud server)

```bash
docker build -t digital-twin-me .
docker run --rm -p 7860:7860 --env-file .env digital-twin-me
```

Or with Compose:

```bash
docker compose up -d --build
```

The image copies the **`me/`** tree (including your YAML profile files). Ensure **`OPENAI_API_KEY`** (and Pushover keys if used) are supplied at runtime via **`--env-file`** or your orchestrator.

Optional: set **`GRADIO_PUBLISH_PORT`** in `.env` for Compose host port mapping (see [`docker-compose.yml`](docker-compose.yml)).

**Note:** If the app still uses Gradio’s default bind (`127.0.0.1`), port publishing from a container may not be reachable from the host until **`launch(server_name="0.0.0.0")`** is set in code or you terminate TLS/proxy in front.

---

## GitHub Actions deploy

On push to `main` (or **Run workflow** manually), [.github/workflows/deploy.yml](.github/workflows/deploy.yml) rsyncs the repo to the server and runs `docker compose up -d --build`. The server must already have Docker, Docker Compose, a clone-compatible directory at `DEPLOY_PATH`, and a `.env` file there (rsync excludes `.env` so it is never overwritten from CI).

Configure these in the repo’s **Settings → Secrets and variables → Actions**:

| Secret | Required | Description |
|--------|----------|-------------|
| `SSH_PRIVATE_KEY` | Yes | Private key for the deploy user (full PEM, including `BEGIN`/`END` lines). |
| `SSH_HOST` | Yes | Server hostname or IP (often the same value as `CLOUD_SERVER_IP` in server `.env`). |
| `SSH_USER` | Yes | SSH login user (e.g. `ubuntu`, `debian`). |
| `DEPLOY_PATH` | Yes | Absolute path on the server where the app lives (e.g. `/home/ubuntu/digital_twin_me`). No trailing slash. |
| `SSH_PORT` | No | SSH port if not `22`. |

App secrets (`OPENAI_API_KEY`, `PUSHOVER_*`, etc.) stay only in the server’s `.env`, not in GitHub, unless you add a separate workflow step to manage them.
