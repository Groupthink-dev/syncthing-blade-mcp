"""Entry point for `python -m syncthing_mcp` and the `syncthing-blade-mcp` console script."""

import os
import sys


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()

    if transport == "streamable-http":
        _run_http()
    else:
        from syncthing_mcp.server import mcp

        mcp.run()


def _run_http() -> None:
    """Start the Streamable HTTP server with optional bearer-token auth."""
    from syncthing_mcp.server import mcp

    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()

    if token:
        import uvicorn

        from syncthing_mcp.auth import BearerAuthMiddleware

        app = mcp.streamable_http_app()
        app.add_middleware(BearerAuthMiddleware, token=token)

        print("Bearer-token authentication enabled", file=sys.stderr)
        print(f"Listening on {host}:{port} (streamable-http)", file=sys.stderr)
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        print(
            "WARNING: MCP_AUTH_TOKEN not set — server is unauthenticated",
            file=sys.stderr,
        )
        mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    main()
