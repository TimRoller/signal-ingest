from fastapi import FastAPI

app = FastAPI(title="signal-ingest / mcp_server", version="0.0.0")


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
