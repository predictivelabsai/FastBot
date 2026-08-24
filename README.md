# FastBot

FastBot is a full-Python, server-rendered interpretation of
[CopilotKit OpenBot](https://github.com/CopilotKit/openbot): governed AI coworkers with durable
channels, visible activity, explicit policy, and an audit trail.

The application follows the FastHTML pattern used by the sister repositories. LangGraph is the
primary agent runtime, xAI Grok is the default model, and AG-UI is the protocol boundary. Text,
tools, state, errors, and generative UI stream from the server as SSE events—there is no React build.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
chmod +x scripts/dev.sh
scripts/dev.sh
```

The launcher uses `XAI_API_KEY` from the environment or inherits it from an ignored sister-repo
`.env` without printing or copying the secret. Open <http://127.0.0.1:5012>.

## Validate

```bash
.venv/bin/ruff check .
.venv/bin/pytest
```

The canonical endpoint is `POST /api/agui`; FastHTML chat uses the same runtime through
`POST /api/chat`. See [architecture](docs/architecture.md) for the contract and roadmap.
