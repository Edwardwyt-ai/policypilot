"""Pure-ASGI request tracing, including streamed responses and threadpool work."""

from tau2.utils.telemetry import _get_backend, current_ids, observe, remote_parent


class TelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or _get_backend() is None:
            return await self.app(scope, receive, send)
        with remote_parent(scope.get("headers", [])):
            with observe("http.request", metadata={"method": scope["method"]}) as span:

                async def traced_send(message):
                    if message["type"] == "http.response.start":
                        code = message["status"]
                        span.update(metadata={"http_status": code}, failed=code >= 500)
                        ids = current_ids()
                        if ids:
                            message = {
                                **message,
                                "headers": [
                                    *message.get("headers", []),
                                    (b"x-trace-id", ids["trace_id"].encode()),
                                ],
                            }
                    await send(message)

                try:
                    await self.app(scope, receive, traced_send)
                finally:
                    route = scope.get("route")
                    if route is not None:
                        span.update(
                            metadata={"route": getattr(route, "path", "unknown")}
                        )
