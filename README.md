# digital_twin_me

A small **Gradio** chat app that uses **OpenAI** function calling to role-play a fixed persona (“digital twin”) using a text summary and LinkedIn PDF as context. Optional **Discord** notifications record lead capture and unanswered questions.

---

## Application (`app.py`)

The program lives in [`app.py`](app.py). This section describes how it behaves end to end.

### Purpose

Visitors chat in a browser. The model answers as a named person (currently **Calistus Igwilo**, set in code in `Me.__init__`) using:

- A long-form **summary** from `me/summary.txt`
- **LinkedIn profile text** extracted from `me/linkedin.pdf` via PyPDF

The assistant is instructed to stay in character, sound professional, nudge people toward email contact, and use tools when appropriate.

### Stack

| Piece | Role |
|--------|------|
| [Gradio](https://www.gradio.app/) | `gr.ChatInterface` with `type="messages"` — chat UI and HTTP server |
| [OpenAI API](https://platform.openai.com/docs) | `OpenAI()` client; chat completions with **tools** |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Loads `.env` at startup (`load_dotenv(override=True)`) |
| [requests](https://requests.readthedocs.io/) | `POST` to Discord webhook when tools run |
| [pypdf](https://pypdf.readthedocs.io/) | Reads `me/linkedin.pdf` and concatenates per-page text |

### Startup and data loading

1. Environment variables are loaded from `.env`.
2. If `DISCORD_WEBHOOK_URL` is set, a short log line confirms it; otherwise the app logs that it was not found.
3. When you run the module, it constructs a single `Me` instance. In `Me.__init__`:
   - `OpenAI()` is created (expects **`OPENAI_API_KEY`** in the environment — standard SDK behavior).
   - `me/linkedin.pdf` is read; all pages are text-extracted and concatenated into `self.linkedin`.
   - `me/summary.txt` is read into `self.summary`.

If either file is missing or unreadable, startup fails before the UI is served.

### Chat flow (`Me.chat`)

For each user message, Gradio passes `(message, history)` where `history` follows the **messages** format (role/content pairs).

1. Build `messages`: system prompt (from `system_prompt()`), then `history`, then the new user message.
2. Loop:
   - Call `openai.chat.completions.create` with **`gpt-4o-mini`**, `messages`, and `tools`.
   - If `finish_reason == "tool_calls"`, execute each tool via `handle_tool_call`, append the assistant message and tool results to `messages`, and repeat.
   - Otherwise treat the turn as finished and return `response.choices[0].message.content`.

`handle_tool_call` resolves function names against **module-level** Python functions in `globals()` (same names as the tool definitions). Each result is sent back as a `tool` role message with JSON `content`.

### OpenAI tools (function calling)

Two tools are registered:

| Tool | When the model is told to use it | Effect |
|------|----------------------------------|--------|
| `record_user_details` | User gave an email / interested in contact | `email` (required), optional `name`, `notes` → Discord message via `push()` |
| `record_unknown_question` | Model cannot answer (including trivial or off-topic) | `question` → Discord message via `push()` |

Schemas match OpenAI’s function-calling JSON: `record_user_details` requires `email`; both disallow extra properties.

`push()` sends `{"content": message}` as form data to `DISCORD_WEBHOOK_URL`. **Configure the webhook in production:** if tools run while `DISCORD_WEBHOOK_URL` is unset, `requests.post` would be called with `None` as the URL (avoid that by setting the variable or disabling tool paths in your fork).

### System prompt (`Me.system_prompt`)

The system message tells the model it is acting as the configured name on “the website,” to use the summary and LinkedIn text, to be professional, to **record unknown questions** with `record_unknown_question`, and to **steer toward email** and use `record_user_details` when appropriate. The summary and LinkedIn body are appended as markdown-style sections.

### Gradio server (`if __name__ == "__main__"`)

After `Me()` is constructed, the app launches:

```text
gr.ChatInterface(me.chat, type="messages").launch(
    server_name=...,
    server_port=...,
)
```

| Variable | Default | Meaning |
|----------|---------|---------|
| `GRADIO_SERVER_NAME` | `0.0.0.0` | Bind address (`0.0.0.0` allows Docker/host port mapping) |
| `GRADIO_SERVER_PORT` | `7860` | Port inside the process |
| `CLOUD_SERVER_IP` | (empty) | If set, prints a hint: `http://<ip>:<port>/` (firewall/reverse proxy still apply) |

### Environment variables used by `app.py`

| Variable | Required | Used for |
|----------|----------|----------|
| `OPENAI_API_KEY` | Yes (for real API calls) | OpenAI client authentication |
| `DISCORD_WEBHOOK_URL` | Recommended if you use tools | Incoming webhook URL for `push()` |
| `GRADIO_SERVER_NAME` | No | Bind address |
| `GRADIO_SERVER_PORT` | No | App listen port |
| `CLOUD_SERVER_IP` | No | Startup URL hint only |

Other keys in `.env` (e.g. Pushover) are ignored by this file unless you extend the code.

### Required files (besides `app.py`)

| Path | Role |
|------|------|
| `me/summary.txt` | Persona/context summary injected into the system prompt |
| `me/linkedin.pdf` | LinkedIn export (or similar PDF); text is extracted for context |

The `me/` directory in the repo also contains YAML profile data; **`app.py` does not load those files** — only `summary.txt` and `linkedin.pdf`.

### Customizing the twin

- **Name and framing:** change `self.name` (and any copy in `system_prompt`) in `Me`.
- **Model:** change the `model="gpt-4o-mini"` argument in `chat`.
- **Context sources:** adjust paths or loaders in `Me.__init__`.

### Local run

```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Place me/summary.txt and me/linkedin.pdf; copy .env with OPENAI_API_KEY (and optional DISCORD_WEBHOOK_URL)
python app.py
```

Open the URL Gradio prints (by default `http://127.0.0.1:7860` when binding locally).

---

## Docker (cloud server)

Set `CLOUD_SERVER_IP` in `.env` to your server’s public IP or hostname (used for a startup URL hint). The app listens on `0.0.0.0:7860` inside the container.

```bash
docker build -t digital-twin-me .
docker run --rm -p 7860:7860 --env-file .env digital-twin-me
```

Or with Compose (recommended on the server):

```bash
docker compose up -d --build
```

Optional: set `GRADIO_PUBLISH_PORT` in `.env` or the shell to change the host port (defaults to `7860`).

Ensure `me/linkedin.pdf` and `me/summary.txt` exist on the host before build (they are copied into the image).

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

App secrets (`OPENAI_API_KEY`, etc.) stay only in the server’s `.env`, not in GitHub, unless you add a separate workflow step to manage them.
