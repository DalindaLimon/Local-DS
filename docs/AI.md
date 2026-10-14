# Ask AI (LLM server)

Every post and Short can be sent to **your own LLM server** with one tap: *Summarize*, *Fact-check*, *Explain*, or
a free question. The answer streams in as it is generated. Nothing goes to a cloud AI unless you point it at one.

Code: [app/ai.py](../app/ai.py) (prompt, context, LLM calls) and [app/api_ai.py](../app/api_ai.py) (routes);
frontend `openAsk()` in [app/static/app.js](../app/static/app.js).

- [Connect a server](#connect-a-server)
- [What the model sees](#what-the-model-sees)
- [How accurate is it?](#how-accurate-is-it)
- [Settings](#settings)
- [Troubleshooting](#troubleshooting)

---

## Connect a server

Local DS speaks the **OpenAI-compatible chat API** (`POST <base>/chat/completions` with streaming, and
`GET <base>/models`). Almost every local LLM server offers it:

| Server | `LLM_BASE_URL` | `LLM_MODEL` example |
|---|---|---|
| [Ollama](https://ollama.com) | `http://<host>:11434/v1` | `llama3.1:8b`, `qwen2.5:14b`, `gemma2:9b` |
| llama.cpp `llama-server` | `http://<host>:8080/v1` | the name passed with `--alias` (or any string) |
| LM Studio (server mode) | `http://<host>:1234/v1` | the model identifier shown in LM Studio |
| vLLM | `http://<host>:8000/v1` | the served model name |
| A hosted API (OpenAI, OpenRouter, …) | its base URL | its model name, plus `LLM_API_KEY` |

1. Make the server reachable **from the Local DS container**. For Ollama on another machine (e.g. an AI box on
   your LAN), start it listening on the network: `OLLAMA_HOST=0.0.0.0 ollama serve` (or set it in its systemd
   unit), and pull a model: `ollama pull llama3.1:8b`.
2. Add to `.env`:

   ```
   LLM_BASE_URL=http://192.168.1.50:11434/v1
   LLM_MODEL=llama3.1:8b
   # LLM_API_KEY=only-if-your-server-needs-one
   ```

3. `docker compose up -d`.
4. **More → Admin → Ask AI → Test connection.** It lists the server's models and checks that `LLM_MODEL` is one
   of them.

The ✨ button then appears on every feed card, in the reader view, in Reels (*Ask*), in Past Shorts and in
Your activity. Without `LLM_BASE_URL` and `LLM_MODEL` the buttons are hidden.

**Server on the same host as Docker?** Inside the container, `localhost` is the container itself. Use the host's
LAN IP, or add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service in a
`docker-compose.override.yml` and use `http://host.docker.internal:11434/v1`.

The LLM server address comes from the admin's `.env`, not from users, so it may be on a private network. That's
why it is called directly and not through the SSRF filter (`urlsafe.safe_get`) that every user-supplied URL
goes through.

## What the model sees

`build_messages()` in `ai.py` sends two messages:

1. A **system prompt** with the rules: be accurate, never invent facts, numbers, quotes or sources; say plainly when
   unsure; keep "what the post claims" apart from "what is well established"; mention that it can't browse and has
   a knowledge cutoff; say when it only saw an excerpt; answer in the question's language; plain text.
2. A **user message** with the post's type, title, source, author, publish date, link, today's date, the post
   text (from the feed, sanitized to plain text), and the task:

| Button | Task |
|---|---|
| Summarize | a few bullet points + why it might matter |
| Fact-check | list the main claims; rate each as consistent with established knowledge, disputed/uncertain, or likely false, with reasons; point out missing context, loaded wording, clickbait; say what to verify elsewhere |
| Explain | background and context needed to understand it |
| Your question | your text (with a preset, the question is added to it) |

**The linked article:** feeds often contain only an excerpt. When the post text is shorter than 2000
characters and the post has a link, the server fetches that page (through the SSRF-safe `safe_get`, 10 s timeout,
3 MB max), extracts the readable text (`<article>`/`<main>` paragraphs, without scripts, menus, headers and
footers) and adds it. Reddit and YouTube pages are skipped (Reddit would rate-limit; YouTube pages have no
useful text). The answer header says *"read the linked page"* when this happened. Turn it off with
`LLM_FETCH_ARTICLE=false`.

**Shorts:** only the title, channel and link are available, not what is said in the video, and the prompt tells
the model so.

Everything sent is limited to `LLM_MAX_CONTEXT_CHARS` (12 000 characters, roughly 3 000 tokens) so small local
models with short context windows still work.

Answers are not stored on the server. The page keeps the last answer per item until you reload.

## How accurate is it?

The quality depends on the model. The prompt pushes hard against making things up, but any LLM can still be
wrong, and it **cannot look things up**: it only knows what it was trained on plus the text it is given. Use
*Fact-check* to spot claims worth checking, not as the final word. Bigger models (14B+) are noticeably better at
fact-checking than 7–8B ones.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | empty | OpenAI-compatible base URL, usually ending in `/v1`. Empty = Ask AI off |
| `LLM_MODEL` | empty | Model name as the server knows it |
| `LLM_API_KEY` | empty | Sent as `Authorization: Bearer …` if set |
| `LLM_TIMEOUT` | `180` | Seconds to wait for the first token / between tokens |
| `LLM_MAX_CONTEXT_CHARS` | `12000` | Max characters of post + article text sent to the model |
| `LLM_FETCH_ARTICLE` | `true` | Fetch the linked page when the feed text is short |

## Troubleshooting

| Symptom | Fix |
|---|---|
| No ✨ button | `LLM_BASE_URL` or `LLM_MODEL` is empty; restart after editing `.env`; reload the page |
| *"Could not reach the LLM server"* | Wrong IP/port, server only listening on localhost (`OLLAMA_HOST=0.0.0.0`), firewall, or `localhost` used from inside Docker |
| *"Model 'x' is not on the server"* | Use a name from the list the test shows (`ollama list`) |
| *"did not answer within 180 s"* | The model is too big for the hardware or still loading; try a smaller model or raise `LLM_TIMEOUT` |
| HTTP 404 from the server | The base URL probably lacks `/v1` |
| Answers in the wrong language | Ask your question in the language you want; small models sometimes ignore it |
| Answer stops halfway with *[AI error: …]* | The server dropped the connection (crash, out of memory); check its logs |
