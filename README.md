# wise-mem
A local memory and context store for agents.

## Stack
- FastAPI
- Pydantic
- Typer
- Loguru

## Run
```bash
uv sync
uv run wise-mem
```

## API
`GET /health` returns:

```json
{"status": "ok", "app": "wise-mem"}
```
