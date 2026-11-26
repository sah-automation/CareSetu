"""ai-engineering-standards A7: AI-gateway tracing gate - fixture tests.

Feeds throwaway Python files to ``scripts.check_ai_tracing`` and asserts the
gate flags a concrete method on an AI-boundary ``MOD-005`` class that skips
Langfuse tracing, while passing the ``@observe`` form, the ``langfuse``
client-reference form, abstract stubs, ``_private`` helpers, ``@property``
accessors, and non-boundary classes. Also asserts the real repo is clean and
that ``main`` falls back to the tracked intake tree when given no files.
"""

import subprocess
from pathlib import Path

import pytest
from scripts.check_ai_tracing import (
    AiTracingViolation,
    _tracked_intake_files,
    check_ai_tracing,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

GATEWAY_UNTRACED = (
    "class GeminiGateway:\n"
    "    async def transcribe(self, audio_ref: str) -> str:\n"
    "        return await self._call_provider(audio_ref)\n"
)
GATEWAY_OBSERVED = (
    "from langfuse.decorators import observe\n"
    "\n"
    "class GeminiGateway:\n"
    '    @observe(name="ai_transcribe")\n'
    "    async def transcribe(self, audio_ref: str) -> str:\n"
    "        return await self._call_provider(audio_ref)\n"
)
GATEWAY_CLIENT_REF = (
    "class GeminiGateway:\n"
    "    async def transcribe(self, audio_ref: str) -> str:\n"
    "        langfuse = get_langfuse_client('', '', '')\n"
    "        return await self._call_provider(audio_ref)\n"
)
GATEWAY_STUB = (
    "from typing import Protocol\n"
    "class AIGateway(Protocol):\n"
    "    async def transcribe(self, audio_ref: str) -> str: ...\n"
)
NON_GATEWAY = "class IntakeFacade:\n    def submit_intake(self) -> None:\n        return None\n"
PRIVATE_HELPER = (
    "from langfuse.decorators import observe\n"
    "class NvidiaProvider:\n"
    '    @observe(name="ai_structure")\n'
    "    async def structure(self, transcript: str) -> str:\n"
    "        return await self._call_provider(transcript)\n"
    "    async def _call_provider(self, raw: str) -> str:\n"
    "        return raw\n"
)
PROPERTY_ACCESSOR = (
    "class GeminiGateway:\n"
    "    @property\n"
    "    def model_name(self) -> str:\n"
    "        return 'gemini-2.0-flash'\n"
)
FULLY_TRACED_SOURCE = (
    "from langfuse.decorators import observe\n"
    "\n"
    "class GeminiGateway:\n"
    '    @observe(name="ai_transcribe")\n'
    "    async def transcribe(self, audio_ref: str) -> str:\n"
    "        return audio_ref\n"
    "    async def structure(self, transcript: str) -> str:\n"
    "        langfuse = get_langfuse_client('pk', 'sk', 'host')\n"
    "        langfuse.score(name='confidence', value=0.9)\n"
    "        return transcript\n"
)


def _write(root: Path, name: str, content: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _methods(violations: tuple[AiTracingViolation, ...]) -> list[str]:
    return [violation.method for violation in violations]


def _tracked_repo_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    files = [
        repo_root / raw.decode("utf-8", "replace") for raw in result.stdout.split(b"\x00") if raw
    ]
    return [path for path in files if path.is_file()]


def test_traced_gateway_passes(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "decorated.py", GATEWAY_OBSERVED)]) == ()


def test_client_reference_passes(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "client_ref.py", GATEWAY_CLIENT_REF)]) == ()


def test_untraced_gateway_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "untraced.py", GATEWAY_UNTRACED)

    violations = check_ai_tracing([path])
    assert len(violations) == 1
    assert violations[0].path == path
    assert violations[0].method == "transcribe"
    assert violations[0].class_name == "GeminiGateway"


def test_abstract_stub_port_passes(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "ports.py", GATEWAY_STUB)]) == ()


def test_non_gateway_class_passes(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "facade.py", NON_GATEWAY)]) == ()


def test_private_helper_is_not_flagged(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "helpers.py", PRIVATE_HELPER)]) == ()


def test_property_accessor_is_not_flagged(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "props.py", PROPERTY_ACCESSOR)]) == ()


def test_every_method_is_traced_in_mixed_file(tmp_path: Path) -> None:
    assert check_ai_tracing([_write(tmp_path, "mixed.py", FULLY_TRACED_SOURCE)]) == ()


def test_non_python_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text(GATEWAY_UNTRACED, encoding="utf-8")

    assert check_ai_tracing([path]) == ()


def test_repo_intake_tree_is_clean() -> None:
    assert check_ai_tracing(_tracked_intake_files(REPO_ROOT)) == ()


def test_main_with_no_files_falls_back_to_tracked_intake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    dirty = _write(repo, "apps/backend/modules/intake/llm_gateway.py", GATEWAY_UNTRACED)
    subprocess.run(["git", "add", dirty.relative_to(repo).as_posix()], cwd=repo, check=True)
    monkeypatch.chdir(repo)

    assert main([]) == 1

    fixed = _write(repo, "apps/backend/modules/intake/llm_gateway.py", GATEWAY_OBSERVED)
    subprocess.run(["git", "add", fixed.relative_to(repo).as_posix()], cwd=repo, check=True)
    assert main([]) == 0
