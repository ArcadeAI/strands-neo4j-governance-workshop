"""The gate: Bowser Capital's control plane, served for Arcade to call.

    uv run gate                 # serves http://127.0.0.1:8742, policies from gate/policies/

Arcade Cloud calls it on every Bank tool listing and call, and on the outbound tools a policy
names, so it needs a public HTTPS address: run `ngrok http 8742` (or any tunnel) next to it and
register the three URLs it prints as a Contextual Access webhook extension in the Arcade
dashboard (docs/modules/02-payments.md).

Every hook request must carry `Authorization: Bearer $GATE_TOKEN`, the token you also give
Arcade when you create the extension. With no GATE_TOKEN the gate refuses to start.
"""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bank_gate.audit import AuditLog
from bank_gate.directory import Directory
from bank_gate.hooks import CHECK_FAILED, Hooks
from bank_gate.policy import DEFAULT_POLICY, Policy, load_policy

DEFAULT_PORT = 8742


def create_app(policy: Policy, directory: Directory, token: str, audit: AuditLog | None = None) -> FastAPI:
    if not token:
        raise ValueError("the gate needs a bearer token; set GATE_TOKEN")
    hooks = Hooks(policy, directory, audit or AuditLog())
    app = FastAPI(title="Bowser Capital control plane", docs_url=None, redoc_url=None)
    app.state.hooks = hooks

    def bearer(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}"
        if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    async def body(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="the body is not JSON") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="the body is not a JSON object")
        return payload

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "code": CHECK_FAILED})

    @app.post("/hooks/access", dependencies=[Depends(bearer)])
    async def access(request: Request):
        payload = await body(request)
        try:
            return hooks.access(payload)
        except Exception as exc:  # noqa: BLE001 - an access hook that cannot decide must not allow
            hooks.audit.record(hook="access", outcome="denied", user_id=str(payload.get("user_id", "-")), detail=f"error: {exc}")
            return JSONResponse(status_code=503, content={"error": "the control plane could not read the graph", "code": CHECK_FAILED})

    @app.post("/hooks/pre", dependencies=[Depends(bearer)])
    async def pre(request: Request):
        payload = await body(request)
        try:
            return hooks.pre(payload)
        except Exception as exc:  # noqa: BLE001 - fail closed with a reason the agent can pass on
            hooks.audit.record(hook="pre", outcome="denied", user_id="-", detail=f"error: {exc}")
            return {"code": CHECK_FAILED, "error_message": "DENIED: the bank's control plane could not check this call, so it did not run."}

    @app.post("/hooks/post", dependencies=[Depends(bearer)])
    async def post(request: Request):
        payload = await body(request)
        try:
            return hooks.post(payload)
        except Exception as exc:  # noqa: BLE001 - an output that could not be checked does not reach the model
            hooks.audit.record(hook="post", outcome="denied", user_id="-", detail=f"error: {exc}")
            return {"code": CHECK_FAILED, "error_message": "The bank's control plane could not check this result, so it was withheld."}

    @app.get("/hooks/health")
    async def health():
        if directory.ping():
            return {"status": "healthy"}
        return JSONResponse(status_code=503, content={"status": "unhealthy"})

    @app.get("/audit", dependencies=[Depends(bearer)])
    async def audit_rows(limit: int = 100):
        return {"rows": hooks.audit.recent(limit)}

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn
    from dotenv import find_dotenv, load_dotenv

    from bank_gate.directory import Neo4jDirectory

    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(prog="gate", description="Serve Bowser Capital's contextual access hooks.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("GATE_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=os.environ.get("GATE_HOST", "127.0.0.1"))
    parser.add_argument("--policy", default=os.environ.get("GATE_POLICY", str(DEFAULT_POLICY)))
    args = parser.parse_args(argv)

    token = os.environ.get("GATE_TOKEN", "").strip()
    if not token:
        sys.exit("GATE_TOKEN is not set. Generate one (`openssl rand -hex 32`), put it in .env, and give Arcade the same value.")
    policy = load_policy(args.policy)
    directory = Neo4jDirectory.from_env()
    audit = AuditLog(Path(os.environ.get("GATE_AUDIT_LOG", ".gate/audit.jsonl")))
    app = create_app(policy, directory, token, audit)

    public = os.environ.get("GATE_PUBLIC_URL", "").strip().rstrip("/") or "https://<your-tunnel-host>"
    print(f"Policy: {args.policy} ({len(policy.rules)} rules, toolkit {policy.toolkit})", file=sys.stderr)
    print(f"Tunnel: ngrok http {args.port}   (then set GATE_PUBLIC_URL in .env to the https address it gives you)", file=sys.stderr)
    print("Register these in Arcade, Contextual Access, one webhook extension, Bearer = GATE_TOKEN, fail closed:", file=sys.stderr)
    for point in ("access", "pre", "post"):
        print(f"  {point:<6} {public}/hooks/{point}", file=sys.stderr)
    print(f"  health {public}/hooks/health", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
