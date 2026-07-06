from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path

import requests

from app.models import PartSpec, SearchResult
from app.settings import APP_DIR


@dataclass(frozen=True)
class DeepSeekMacroSuggestion:
    body_code: str
    notes: str
    model: str


def load_env(path: Path = APP_DIR / ".env") -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
        return
    except Exception:
        pass

    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class DeepSeekMacroAssistant:
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-pro",
        base_url: str = "https://api.deepseek.com",
        timeout: int = 45,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "DeepSeekMacroAssistant | None":
        load_env()
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return None
        timeout_raw = os.environ.get("DEEPSEEK_TIMEOUT", "45").strip()
        try:
            timeout = int(timeout_raw)
        except ValueError:
            timeout = 45
        return cls(
            api_key=api_key,
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com",
            timeout=timeout,
        )

    def suggest_body(
        self,
        spec: PartSpec,
        rag_results: tuple[SearchResult, ...],
        deterministic_body: str,
    ) -> DeepSeekMacroSuggestion | None:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior FreeCAD Python macro engineer. Return only JSON. "
                        "Generate only the geometry body for an existing macro. The surrounding "
                        "macro already imports math, FreeCAD as App, Part, Vector and defines "
                        "cut_cylinder, safe_fillet and safe_chamfer. Your body must assign a valid "
                        "Part shape to a variable named shape. Do not save, export, read files, "
                        "import modules, access os/sys/subprocess, network, eval, exec, open, or dunder names."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Create a robust FreeCAD Part body for this parsed CAD prompt.",
                            "part_spec": spec.to_dict(),
                            "rag_context": [
                                {
                                    "title": result.title,
                                    "url": result.url,
                                    "text": result.text[:900],
                                }
                                for result in rag_results[:5]
                            ],
                            "fallback_body": deterministic_body,
                            "return_schema": {
                                "body_code": "Python code string. Must create variable shape.",
                                "notes": "Short Portuguese explanation of geometry strategy.",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 2400,
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            content = message.get("content") or message.get("reasoning_content", "")
            parsed = self._parse_json_object(content)
            body_code = str(parsed.get("body_code", "")).strip()
            notes = str(parsed.get("notes", "")).strip()
            if not body_code:
                return None
            self._validate_body(body_code)
            return DeepSeekMacroSuggestion(body_code=body_code, notes=notes, model=self.model)
        except Exception as exc:
            return DeepSeekMacroSuggestion(
                body_code="",
                notes=f"DeepSeek indisponivel ou resposta recusada; usando gerador local. Motivo: {exc}",
                model=self.model,
            )

    def review_spec(
        self,
        spec: PartSpec,
        rag_results: tuple[SearchResult, ...],
        deterministic_body: str,
    ) -> DeepSeekMacroSuggestion:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior FreeCAD and mechanical CAD reviewer. Return only JSON. "
                        "Do not rewrite geometry. Review the parsed CAD spec and deterministic FreeCAD body. "
                        "The local parser/validator is authoritative for dimensions."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "Review whether this parsed spec and deterministic macro strategy match the user's CAD intent. Answer in Portuguese.",
                            "part_spec": spec.to_dict(),
                            "rag_context": [
                                {"title": result.title, "url": result.url, "text": result.text[:700]}
                                for result in rag_results[:5]
                            ],
                            "deterministic_body": deterministic_body[:2500],
                            "return_schema": {
                                "notes": "Short Portuguese review. Mention corrections such as typos, thread metadata, hole count and bolt-circle radius.",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.0,
            "max_tokens": 900,
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
            content = message.get("content") or message.get("reasoning_content", "")
            parsed = self._parse_json_object(content)
            notes = str(parsed.get("notes", "")).strip()
            return DeepSeekMacroSuggestion(body_code="", notes=notes or "DeepSeek revisou o spec; sem ajustes geometricos.", model=self.model)
        except Exception as exc:
            return DeepSeekMacroSuggestion(
                body_code="",
                notes=f"DeepSeek indisponivel para revisao; usando gerador local validado. Motivo: {exc}",
                model=self.model,
            )

    def _parse_json_object(self, content: str) -> dict[str, object]:
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.lower().startswith("json"):
                content = content[4:].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start : end + 1])
            raise

    def _validate_body(self, code: str) -> None:
        tree = ast.parse(code)
        banned_names = {
            "open",
            "exec",
            "eval",
            "compile",
            "__import__",
            "globals",
            "locals",
            "vars",
            "getattr",
            "setattr",
            "delattr",
            "os",
            "sys",
            "subprocess",
            "socket",
            "requests",
            "shutil",
            "pathlib",
            "builtins",
        }
        banned_nodes = (
            ast.Import,
            ast.ImportFrom,
            ast.With,
            ast.AsyncWith,
            ast.Try,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Lambda,
            ast.Global,
            ast.Nonlocal,
            ast.Delete,
        )
        creates_shape = False
        for node in ast.walk(tree):
            if isinstance(node, banned_nodes):
                raise ValueError(f"node not allowed: {type(node).__name__}")
            if isinstance(node, ast.Name):
                if node.id in banned_names or "__" in node.id:
                    raise ValueError(f"name not allowed: {node.id}")
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("_") or "__" in node.attr:
                    raise ValueError(f"attribute not allowed: {node.attr}")
            if isinstance(node, ast.Assign):
                creates_shape = creates_shape or any(
                    isinstance(target, ast.Name) and target.id == "shape"
                    for target in node.targets
                )
            if isinstance(node, ast.AnnAssign):
                creates_shape = creates_shape or (
                    isinstance(node.target, ast.Name) and node.target.id == "shape"
                )
        if not creates_shape:
            raise ValueError("body_code must assign variable 'shape'")
        compile(code, "<deepseek-body>", "exec")
