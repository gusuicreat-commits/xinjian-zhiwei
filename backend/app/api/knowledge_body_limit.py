"""Bound import and edit bodies before FastAPI JSON parsing, even without Content-Length."""

import asyncio
import re

from starlette.responses import JSONResponse


class KnowledgeBodyLimit:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.path = re.compile(
            re.escape(settings.api_v1_prefix) + r"/knowledge/sources/[^/]+/documents/(file|text)/?$"
        )

        self.edit_path = re.compile(
            re.escape(settings.api_v1_prefix) + r"/knowledge/chunks/[^/]+/?$"
        )

    async def __call__(self, scope, receive, send):
        match = self.path.fullmatch(scope.get("path", ""))
        is_import = scope.get("method") == "POST" and match
        is_edit = scope.get("method") == "PATCH" and self.edit_path.fullmatch(scope.get("path", ""))
        if scope["type"] != "http" or not (is_import or is_edit):
            return await self.app(scope, receive, send)
        budget = self.settings.knowledge_request_metadata_bytes + (
            4 * ((self.settings.knowledge_max_file_bytes + 2) // 3)
            if is_import and match[1] == "file"
            else self.settings.knowledge_max_document_chars * 12
        )

        async def reject(status, code):
            await JSONResponse({"detail": {"code": code}}, status_code=status)(scope, receive, send)

        headers = dict(scope.get("headers", []))
        if headers.get(b"content-encoding", b"identity").lower() != b"identity":
            return await reject(415, "KNOWLEDGE_ENCODING_UNSUPPORTED")
        try:
            length = int(headers[b"content-length"]) if b"content-length" in headers else None
        except ValueError:
            return await reject(400, "INVALID_CONTENT_LENGTH")
        if length is not None and (length < 0 or length > budget):
            return await reject(413, "KNOWLEDGE_REQUEST_TOO_LARGE")
        body = bytearray()
        deadline = asyncio.get_running_loop().time() + 30
        while True:
            try:
                message = await asyncio.wait_for(
                    receive(), timeout=max(0, deadline - asyncio.get_running_loop().time())
                )
            except TimeoutError:
                return await reject(408, "KNOWLEDGE_UPLOAD_TIMEOUT")
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > budget:
                return await reject(413, "KNOWLEDGE_REQUEST_TOO_LARGE")
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
