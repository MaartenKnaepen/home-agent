from __future__ import annotations

import os
import sys

MIN_PYTHON_VERSION = (3, 10)


def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON_VERSION:
        sys.exit(
            f"Python {MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]} or higher is required."
        )


if __name__ == "__main__":
    _check_python_version()
    import argparse
    import uvicorn
    from jellyseerr_mcp.server import mcp, run as run_mcp

    parser = argparse.ArgumentParser(description="Jellyseerr MCP Server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse"],
        help="Transport protocol to use (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", 8000)),
        help="Port to serve SSE on (default: $PORT or 8000)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        # Run uvicorn directly with host validation disabled so Docker
        # service-name Host headers (e.g. Host: jellyseerr-mcp) are accepted
        from jellyseerr_mcp.server import load_config, JellyseerrClient
        import jellyseerr_mcp.server as _srv

        config = load_config()
        _srv._client = JellyseerrClient(config)

        # Disable MCP's DNS rebinding protection so Docker service-name
        # Host headers (e.g. Host: jellyseerr-mcp) are accepted
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

        app = mcp.sse_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        import asyncio
        asyncio.run(run_mcp(transport=args.transport, port=args.port))
