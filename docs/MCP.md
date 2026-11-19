# The MCP server

`mcp_server.py` offers Podcast Compass to AI clients through the
[Model Context Protocol](https://modelcontextprotocol.io). A client such as Claude Desktop
starts it as a subprocess and talks to it over stdio, so there is no port and no network
listener. It uses the same parsing, retrieval, prompts and quote checks as the web app,
from the `podcast_compass` package.

It is written against version 2 of the official Python SDK (`mcp==2.3.0`), where the
server class is `MCPServer` (it was called `FastMCP` in version 1).

## Tools

| Tool | What it does | API requests |
|---|---|---|
| `load_transcript(text)` | Parses and segments a transcript (plain text, WebVTT or SubRip) and returns a `transcript_id` | None |
| `search_transcript(transcript_id, query, k=5)` | The `k` segments closest in meaning to the query, best first, with each segment's own text | 1, plus indexing the first time |
| `ask_podcast(transcript_id, question)` | An answer from the retrieved segments only, with verified citations, or "not in the transcript" | Up to 5, plus indexing the first time |
| `generate_quiz(transcript_id)` | 5-8 questions; any whose quote is not in its cited segment is removed | Up to 3 |

Indexing embeds every segment once per transcript: one request per 100 segments.

Every result is structured JSON with a declared output schema. Every quote has been checked
to appear in the segment it cites, and every `start` time is read from the subtitle cues;
plain-text transcripts have `start: null` and a `notice` saying why.

### Inputs and limits

- `text` is at most 150,000 characters and must have at least 250 words, the same limits
  as the web app.
- `query` and `question` are at most 300 characters. The question is sanitised and passed
  to the model inside a block labelled as data, as revision instructions are in the app.
- `k` is between 1 and 10.
- The server keeps the five most recently loaded transcripts in memory and nothing on disk.
- It counts requests against its own daily limit of 400, reserved before each call and
  settled afterwards, like the app.

### Errors

A failed call returns an MCP tool error whose text starts with a code:

| Code | Meaning |
|---|---|
| `invalid_input` | The transcript or question was rejected; the message says why |
| `unknown_transcript` | The id was never loaded, or has been evicted |
| `not_configured` | `GEMINI_API_KEY` is missing or was rejected |
| `quota_exceeded` | The server's daily limit or the provider's free tier is used up |
| `provider_error` | The model or the search model failed after retries |
| `unverifiable` | No generated quiz question could be confirmed against the transcript |

Arguments that break the input schema (too long, `k` out of range) are rejected by the SDK
before the tool runs.

## Running it

```bash
python -m pip install -r requirements.txt -r requirements-mcp.txt
```

Set `GEMINI_API_KEY` in the environment the server starts in. `load_transcript` works
without it.

### MCP Inspector

The Inspector is a browser UI for calling a server's tools by hand. It needs Node.js.

The Inspector does not pass your shell's environment on to the server it starts, so the
key goes in with `-e`. Loading it from `.env` first keeps it out of your shell history.

```bash
# macOS, Linux or WSL
set -a; source .env; set +a
npx @modelcontextprotocol/inspector -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  .venv/bin/python mcp_server.py
```

```powershell
# Windows PowerShell, with the key already in $env:GEMINI_API_KEY
npx @modelcontextprotocol/inspector -e GEMINI_API_KEY=$env:GEMINI_API_KEY `
  .\.venv\Scripts\python.exe mcp_server.py
```

Without the key, `load_transcript` still works and the other tools return a
`not_configured` error.

It prints a local URL. Open it, press **Connect**, open **Tools**, and run the tools.
For `load_transcript`, switch on **Edit as JSON** and pass the file as a JSON string,
because the plain text box joins lines together and a subtitle file needs its line
breaks. This prints the arguments for the example episode:

```bash
python -c "import json; print(json.dumps({'text': open('samples/sample_episode.vtt', encoding='utf-8').read()}))"
```

Then use the returned `transcript_id` with the other tools.

### Claude Desktop

Add the server to Claude Desktop's configuration file, `claude_desktop_config.json`
(**Settings → Developer → Edit Config** opens it), then restart Claude Desktop. Use
absolute paths. This file stays on your machine; never commit a copy with a key in it.

```json
{
  "mcpServers": {
    "podcast-compass": {
      "command": "C:\\path\\to\\Podcast-Compass\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\Podcast-Compass\\mcp_server.py"],
      "env": { "GEMINI_API_KEY": "your-key-here" }
    }
  }
}
```

On macOS or Linux the paths look like `/path/to/Podcast-Compass/.venv/bin/python` and
`/path/to/Podcast-Compass/mcp_server.py`.

Then ask Claude something like: *"Load the transcript in this file with podcast-compass,
then ask it what the hosts say about water."*

## Tests

`tests/test_mcp_server.py` drives the server through the SDK's in-memory client, which
speaks the real protocol to the real server object, with the model and the embeddings
replaced by fakes. No test makes a network request.
