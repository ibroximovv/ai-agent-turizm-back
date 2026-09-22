"""An in-memory Open WebUI, served through httpx.MockTransport.

Only the endpoints the backend calls exist, with the behaviour of Open WebUI
0.11.3 that matters to us: deleting a file unlinks it from every KB, deleting a
KB leaves its files behind but strips it from every model, and a file linked
before its extraction finished is rejected.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx


class FakeOwui:
    def __init__(self) -> None:
        self.kbs: dict[str, dict[str, Any]] = {}
        self.files: dict[str, dict[str, Any]] = {}
        self.models: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self._ids = itertools.count(1)

    # -- seeding helpers ---------------------------------------------------

    def add_kb(self, name: str, kb_id: str | None = None) -> str:
        kb_id = kb_id or f"kb-{next(self._ids)}"
        self.kbs[kb_id] = {
            "id": kb_id,
            "name": name,
            "description": "",
            "files": [],
            "access_grants": [],
        }
        return kb_id

    def add_model(self, model_id: str, **fields: Any) -> dict[str, Any]:
        model = {
            "id": model_id,
            "base_model_id": "turizm_router.avto",
            "name": model_id,
            "params": {"system": "", "function_calling": "native"},
            "meta": {"knowledge": [], "toolIds": ["ofis_saqlash_tool"]},
            "access_grants": [],
            "is_active": True,
        }
        model.update(fields)
        self.models[model_id] = model
        return model

    def knowledge_ids(self, model_id: str) -> list[str]:
        return [k["id"] for k in self.models[model_id]["meta"].get("knowledge") or []]

    # -- transport ---------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        body = (
            json.loads(request.content)
            if request.content
            and method != "GET"
            and (request.headers.get("content-type", "").startswith("application/json"))
            else None
        )

        if path == "/api/v1/knowledge/" and method == "GET":
            return _ok({"items": list(self.kbs.values()), "total": len(self.kbs)})
        if path == "/api/v1/knowledge/create":
            kb_id = self.add_kb(body["name"])
            self.kbs[kb_id].update(
                description=body.get("description", ""),
                access_grants=body.get("access_grants") or [],
            )
            return _ok(self.kbs[kb_id])
        if path.startswith("/api/v1/knowledge/"):
            return self._knowledge(request, path.removeprefix("/api/v1/knowledge/"), body)
        if path == "/api/v1/files/" and method == "POST":
            file_id = f"file-{next(self._ids)}"
            processed = request.url.params.get("process_in_background") == "false"
            self.files[file_id] = {"id": file_id, "processed": processed}
            return _ok({"id": file_id, "filename": "doc.md"})
        if path.startswith("/api/v1/files/") and method == "DELETE":
            file_id = path.removeprefix("/api/v1/files/")
            self.files.pop(file_id, None)
            for kb in self.kbs.values():
                kb["files"] = [f for f in kb["files"] if f != file_id]
            return _ok({"message": "deleted"})
        if path == "/api/v1/models/list":
            return _ok({"items": list(self.models.values()), "total": len(self.models)})
        if path == "/api/v1/models/model" and method == "GET":
            model = self.models.get(request.url.params["id"])
            return _ok(model) if model else httpx.Response(404, json={"detail": "not found"})
        if path == "/api/v1/models/create":
            if body["id"] in self.models:
                return httpx.Response(401, json={"detail": "taken"})
            self.models[body["id"]] = {"access_grants": [], **body}
            return _ok(self.models[body["id"]])
        if path == "/api/v1/models/model/update":
            if body["id"] not in self.models:
                return httpx.Response(401, json={"detail": "not found"})
            grants = body.get("access_grants")
            model = {**body, "access_grants": self.models[body["id"]]["access_grants"]}
            if grants is not None:
                model["access_grants"] = grants
            self.models[body["id"]] = model
            return _ok(model)
        if path == "/api/v1/models/model/delete":
            return _ok(self.models.pop(body["id"], None) is not None)
        return httpx.Response(404, json={"detail": f"unexpected {method} {path}"})

    def _knowledge(self, request: httpx.Request, rest: str, body) -> httpx.Response:
        kb_id, _, action = rest.partition("/")
        kb = self.kbs.get(kb_id)
        if kb is None:
            return httpx.Response(400, json={"detail": "not found"})
        if not action and request.method == "GET":
            return _ok(kb)
        if action == "files":
            page = int(request.url.params.get("page", 1))
            chunk = kb["files"][(page - 1) * 30 : page * 30]
            return _ok({"items": [{"id": f} for f in chunk], "total": len(kb["files"])})
        if action == "file/add":
            file = self.files.get(body["file_id"])
            if file is None or not file["processed"]:
                return httpx.Response(400, json={"detail": "empty content"})
            kb["files"].append(body["file_id"])
            return _ok(kb)
        if action == "access/update":
            kb["access_grants"] = body["access_grants"]
            return _ok(kb)
        if action == "delete":
            del self.kbs[kb_id]
            for model in self.models.values():
                meta = model["meta"]
                meta["knowledge"] = [k for k in meta.get("knowledge") or [] if k["id"] != kb_id]
            return _ok(True)
        return httpx.Response(404, json={"detail": f"unexpected knowledge/{rest}"})


def _ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)
