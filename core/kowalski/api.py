"""Optional debug REST API on 127.0.0.1 (FastAPI; lazy imports)."""

from __future__ import annotations

import json


def build_app(service):
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel

    app = FastAPI(title="kow-core debug API")

    class AskBody(BaseModel):
        prompt: str
        conversation_id: str | None = None

    class ConfirmBody(BaseModel):
        approved: bool

    @app.get("/healthz")
    async def healthz():
        return service.status()

    @app.get("/tools")
    async def tools():
        return service.list_tools()

    @app.post("/ask")
    async def ask(body: AskBody):
        async def stream():
            async for event in service.ask(body.prompt, body.conversation_id):
                yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/confirm/{request_id}")
    async def confirm(request_id: str, body: ConfirmBody):
        return {"ok": service.confirm(request_id, body.approved)}

    return app


async def serve_api(service, port: int = 8377) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(build_app(service), host="127.0.0.1", port=port, log_level="warning")
    )
    await server.serve()
