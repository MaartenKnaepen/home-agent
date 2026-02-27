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

        # Monkey-patch request_media — the community version over-complicates
        # the request by looking for a "services" key that doesn't exist.
        # Jellyseerr just needs mediaId + mediaType (+seasons for TV).
        def _simple_request_media(
            self: JellyseerrClient,
            media_id: int,
            media_type: str,
            is_4k: bool = False,
            seasons: str | list[int] = "all",
        ) -> dict:
            payload: dict = {"mediaId": media_id, "mediaType": media_type}
            if is_4k:
                payload["is4k"] = True
            if media_type == "tv":
                payload["seasons"] = seasons
            return self.request("POST", "request", json=payload)

        JellyseerrClient.request_media = _simple_request_media  # type: ignore[assignment]

        # Replace the MCP request_media tool to support seasons parameter
        mcp._tool_manager.remove_tool("request_media")

        @mcp.tool(description=(
            "Request a movie or TV series on Jellyseerr. "
            "For TV series, specify which seasons to request: 'all' for everything, "
            "or a list of season numbers like [1, 2, 3]."
        ))
        def request_media(
            media_id: int,
            media_type: str,
            seasons: str | list[int] = "all",
        ) -> dict:
            assert _srv._client is not None
            return _srv._client.request_media(
                media_id=media_id,
                media_type=media_type,
                seasons=seasons,
            )

        # Disable MCP's DNS rebinding protection so Docker service-name
        # Host headers (e.g. Host: jellyseerr-mcp) are accepted
        from mcp.server.transport_security import TransportSecuritySettings
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

        # Remove raw_request tool — too dangerous and causes model confusion
        try:
            mcp._tool_manager.remove_tool("raw_request")
            print("Removed raw_request tool from MCP server")
        except Exception as e:
            print(f"Could not remove raw_request tool: {e}")

        app = mcp.sse_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        import asyncio
        asyncio.run(run_mcp(transport=args.transport, port=args.port))
