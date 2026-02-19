#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "openai",
#     "python-dotenv",
# ]
# ///
"""
codex_modoki - ローカルファイル操作AIエージェント
Claude Code / Codex 風の対話型エージェント。
OpenAI gpt-4.1-mini の function calling を使い、
ファイル読み書き・ディレクトリ操作・コマンド実行を自然言語で行う。

Windows / macOS / Linux 対応。
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import difflib
import json
import mimetypes
import os
import platform
import glob as glob_mod
import re
import subprocess
import sys
import time
import threading
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# .env ファイルから環境変数を読み込む（既存の環境変数は上書きしない）
load_dotenv()

# stdin/stdout を UTF-8 に強制（Windows / 一部環境での文字化け対策）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

# ─────────────────────────────────────────────
# カラー出力
# ─────────────────────────────────────────────

_NO_COLOR = os.environ.get("NO_COLOR") or not sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _dim(t: str) -> str:
    return _c("2", t)


def _bold(t: str) -> str:
    return _c("1", t)


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _magenta(t: str) -> str:
    return _c("35", t)


# ─────────────────────────────────────────────
# スピナー
# ─────────────────────────────────────────────

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    """API呼び出し中に回転するインジケーターを表示する。"""

    def __init__(self, message: str = "thinking"):
        self._message = message
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if _GUI_MODE:
            _emit({"type": "status", "message": self._message, "ephemeral": True})
            return
        if _NO_COLOR or not sys.stdout.isatty():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if _GUI_MODE:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if not _NO_COLOR and sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            frame = _SPINNER_FRAMES[idx % len(_SPINNER_FRAMES)]
            sys.stdout.write(f"\r  {_cyan(frame)} {_dim(self._message)}")
            sys.stdout.flush()
            idx += 1
            self._stop_event.wait(0.08)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


# ─────────────────────────────────────────────
# GUI モード (Electron IPC)
# ─────────────────────────────────────────────

_GUI_MODE: bool = False

# 確認ダイアログの同期用
_confirm_events: dict = {}   # id -> threading.Event
_confirm_results: dict = {}  # id -> bool
_confirm_lock = threading.Lock()


def _emit(obj: dict) -> None:
    """GUI モード時に JSON Lines を stdout に書き出す。"""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ─────────────────────────────────────────────
# 設定ファイル
# ─────────────────────────────────────────────

_CONFIG_DIR = Path.home() / ".codex_modoki"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "model": "gpt-4.1-mini",
    "timeout": 30,
    "auto_confirm": False,
    "max_context_messages": 200,
    "compact_keep_recent": 10,
    "auto_context": True,
    "auto_context_max_files": 50,
}


def _load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            config.update(user_cfg)
        except Exception:
            pass
    return config


def _save_config(config: dict) -> None:
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────
# 初回自動コンテキスト収集
# ─────────────────────────────────────────────


def _collect_project_context(max_files: int = 50) -> str:
    """CWD のプロジェクト構造を収集してテキストにする。"""
    cwd = os.getcwd()
    parts = [f"## プロジェクトコンテキスト (自動収集)\n作業ディレクトリ: {cwd}\n"]

    # git 情報
    try:
        git_status = subprocess.run(
            "git status --short", shell=True, capture_output=True,
            text=True, timeout=5, cwd=cwd,
        )
        if git_status.returncode == 0:
            branch = subprocess.run(
                "git branch --show-current", shell=True, capture_output=True,
                text=True, timeout=5, cwd=cwd,
            )
            parts.append(f"### Git")
            parts.append(f"ブランチ: {branch.stdout.strip()}")
            status_text = git_status.stdout.strip()
            if status_text:
                parts.append(f"変更ファイル:\n{status_text[:500]}")
            else:
                parts.append("変更なし (clean)")
    except Exception:
        pass

    # ディレクトリツリー (浅め)
    parts.append("\n### ディレクトリ構造")
    file_count = 0
    tree_lines = []
    for root, dirs, files in os.walk(cwd):
        # 除外ディレクトリ
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".")
            and d not in ("node_modules", "__pycache__", "venv", ".venv", "dist", "build", ".git")
        ]
        depth = root.replace(cwd, "").count(os.sep)
        if depth > 3:
            continue
        indent = "  " * depth
        dir_name = os.path.basename(root) or "."
        tree_lines.append(f"{indent}{dir_name}/")
        for f_name in sorted(files):
            if f_name.startswith("."):
                continue
            file_count += 1
            if file_count <= max_files:
                tree_lines.append(f"{indent}  {f_name}")
        if file_count > max_files:
            tree_lines.append(f"  ... (他 {file_count - max_files}+ ファイル)")
            break
    parts.append("\n".join(tree_lines[:200]))

    # README 読み込み
    for readme_name in ("README.md", "README.txt", "README", "readme.md"):
        readme_path = os.path.join(cwd, readme_name)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, "r", encoding="utf-8") as f:
                    readme_content = f.read(2000)
                parts.append(f"\n### {readme_name} (先頭2000文字)")
                parts.append(readme_content)
            except Exception:
                pass
            break

    # 主要設定ファイルの存在チェック
    config_files = [
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "Makefile", "Dockerfile", "docker-compose.yml",
        ".env.example", "requirements.txt", "setup.py", "setup.cfg",
    ]
    found = [f for f in config_files if os.path.isfile(os.path.join(cwd, f))]
    if found:
        parts.append(f"\n### 検出された設定ファイル")
        parts.append(", ".join(found))

    return "\n".join(parts)


# ─────────────────────────────────────────────
# システムプロンプト
# ─────────────────────────────────────────────


def _build_system_prompt(config: dict, project_context: str = "") -> str:
    prompt = f"""\
あなたはローカルマシン上で動作する万能アシスタントエージェントです。
ユーザーの指示に従い、提供されたツールを使ってファイルの読み書き、
ディレクトリの一覧表示、ファイル検索、シェルコマンドの実行などを行います。

## 環境情報
- OS: {platform.system()} {platform.release()} ({platform.machine()})
- Python: {platform.python_version()}
- 作業ディレクトリ: {os.getcwd()}
- ホームディレクトリ: {Path.home()}
- 使用モデル: {config.get("model", "gpt-4.1-mini")}

## 行動指針（重要）
1. **まず調べてから行動する**: ファイルを編集する前に、必ず read_file や grep で現在の内容を確認してください。
2. **段階的に作業する**: 大きなタスクは小さなステップに分解し、各ステップの結果を確認しながら進めてください。
3. **エラーが出たら自分でリトライする**: ツール実行でエラーが出た場合は原因を分析し、別のアプローチを試みてください。ユーザーに聞く前に少なくとも2回は自力で解決を試みてください。
4. **コンテキストを活用する**: プロジェクト構造、既存コードのパターン、使われているフレームワークを理解してから作業してください。
5. **変更は最小限に**: edit_file で部分編集を優先し、write_file での全体書き換えは新規ファイル作成時のみ使ってください。
6. **確認してから報告する**: ファイルを書き込んだ後は read_file で正しく書き込まれたか確認してください。コマンド実行後は exit code を確認してください。

## ルール
- ファイルパスに ~ が含まれる場合は展開して使ってください。
- ツールの実行結果をもとに、分かりやすく回答してください。
- エラーが発生した場合は、原因と対処法を説明してください。
- OS が Windows の場合、コマンドは cmd.exe / PowerShell 向けの構文を使ってください。
  OS が macOS / Linux の場合、bash / zsh 向けの構文を使ってください。
- ファイル内容の検索には grep ツールを使ってください。
- Python のパッケージ管理には pip ではなく uv を使ってください。
  - パッケージ追加: `uv add <package>`
  - スクリプト実行: `uv run python script.py`
  - 仮想環境作成: `uv venv`
  - プロジェクト初期化: `uv init`
  - pip install の代わりに `uv add` または `uv pip install` を使ってください。
- **Pythonコードのサンドボックス実行**: 計算やデータ処理など安全なPythonコードを実行したい場合は `run_python_sandbox` ツールを使ってください。
  - サンドボックスでは os, sys, subprocess, open() 等の危険な操作は禁止されています。
  - タイムアウトは最大60秒、メモリは256MBに制限されています。
  - ファイル操作やネットワーク通信が必要な場合は `run_command` ツールを使ってください。
  - 何かうまくいかなかった場合の原因調査やデータ分析に積極的に活用してください。
"""
    # スキル一覧をシステムプロンプトに追加
    skills = _skill_registry.list_skills()
    if skills:
        prompt += "\n## 利用可能なスキル\n"
        prompt += "以下のスキルが利用可能です。適切な場面では run_skill ツールを使って実行してください。\n\n"
        for s in skills:
            prompt += f"- **{s.name}**: {s.description}\n"
        prompt += "\n"

    if project_context:
        prompt += f"\n{project_context}\n"

    return prompt


# ─────────────────────────────────────────────
# Agent Skills
# ─────────────────────────────────────────────


class SkillInfo:
    __slots__ = ("name", "description", "path", "source")

    def __init__(self, name: str, description: str, path: Path, source: str):
        self.name = name
        self.description = description
        self.path = path
        self.source = source


def _parse_skill_md(path: Path) -> Optional[dict]:
    """SKILL.md をパースし、name/description/body を返す。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end < 0:
        return None

    frontmatter = text[3:end].strip()
    body = text[end + 3:].strip()

    meta: dict = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()

    name = meta.get("name")
    description = meta.get("description", "")
    if not name:
        return None

    return {"name": name, "description": description, "body": body}


class SkillRegistry:
    """スキルの発見・管理を行うレジストリ。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillInfo] = {}

    def scan(self) -> None:
        new_skills: dict[str, SkillInfo] = {}
        locations = [
            ("global", Path.home() / ".codex_modoki" / "skills"),
            ("project", Path.cwd() / "skills"),
        ]
        for source, base_dir in locations:
            if not base_dir.is_dir():
                continue
            for skill_dir in sorted(base_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.is_file():
                    continue
                parsed = _parse_skill_md(skill_md)
                if parsed is None:
                    continue
                new_skills[parsed["name"]] = SkillInfo(
                    name=parsed["name"],
                    description=parsed["description"],
                    path=skill_md,
                    source=source,
                )
        self._skills = new_skills

    def list_skills(self) -> list[SkillInfo]:
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        return self._skills.get(name)

    def load_instructions(self, name: str) -> str:
        skill = self._skills.get(name)
        if skill is None:
            return ""
        parsed = _parse_skill_md(skill.path)
        if parsed is None:
            return ""
        return parsed["body"]


_skill_registry = SkillRegistry()


# ─────────────────────────────────────────────
# ツール定義 (OpenAI function calling schema)
# ─────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "シェルコマンドを実行し、stdout と stderr を返す。"
            "OS に合わせたコマンドを使うこと。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "実行するコマンド文字列",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "コマンドを実行するディレクトリ（省略時は作業ディレクトリ）",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "タイムアウト秒数（省略時は設定値）",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "指定したファイルの内容を読み込んで返す。"
            "テキストファイルのみ対応。バイナリファイルの場合はエラーを返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "読み込むファイルのパス（~ 使用可）",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "ファイルのエンコーディング（省略時は utf-8）",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "読み込み開始行番号（0始まり、省略時は0）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "読み込む最大行数（省略時は全行）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "指定したパスにファイルを書き込む（全体置換）。"
            "ディレクトリが存在しない場合は自動作成する。"
            "既存ファイルの部分編集には edit_file を使うこと。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "書き込み先のファイルパス（~ 使用可）",
                    },
                    "content": {
                        "type": "string",
                        "description": "書き込む内容",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "ファイルのエンコーディング（省略時は utf-8）",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "既存ファイルの一部を書き換える。old_string を new_string に置換する。"
            "old_string はファイル内でユニークでなければならない。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "編集するファイルのパス（~ 使用可）",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "置換対象の文字列（ファイル内でユニークであること）",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "置換後の文字列",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "指定ディレクトリ内のファイルとフォルダの一覧を返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "一覧を取得するディレクトリのパス（省略時は作業ディレクトリ、~ 使用可）",
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "隠しファイル（. で始まるファイル）を表示するか（省略時は false）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "指定ディレクトリ以下で glob パターンにマッチするファイルを再帰検索する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "検索する glob パターン（例: '**/*.py', '**/*.txt'）",
                    },
                    "path": {
                        "type": "string",
                        "description": "検索の起点ディレクトリ（省略時は作業ディレクトリ、~ 使用可）",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "ファイルの内容を正規表現で検索する。指定ディレクトリ以下を再帰的に検索し、"
            "マッチした行をファイル名・行番号付きで返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "検索する正規表現パターン",
                    },
                    "path": {
                        "type": "string",
                        "description": "検索の起点（ファイルまたはディレクトリ、省略時は作業ディレクトリ、~ 使用可）",
                    },
                    "include": {
                        "type": "string",
                        "description": "対象ファイルの glob パターン（例: '*.py'）。省略時は全ファイル",
                    },
                    "ignore_case": {
                        "type": "boolean",
                        "description": "大文字小文字を無視するか（省略時は false）",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "ファイルまたはディレクトリのメタ情報（サイズ、更新日時、種別など）を返す。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "情報を取得するファイル/ディレクトリのパス（~ 使用可）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python_sandbox",
            "description": "Pythonコードをサンドボックス環境で安全に実行する。"
            "一時ファイルにコードを書き出し、制限付きサブプロセスで実行する。"
            "ファイル操作やネットワーク通信が必要な場合は run_command を使うこと。"
            "データ解析・計算・テキスト処理など安全なコードの実行に適している。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "実行するPythonコード",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "タイムアウト秒数（省略時は30秒、最大60秒）",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": "登録済みのスキルを実行する。スキルの指示をロードして会話コンテキストに注入し、"
            "その指示に従って作業を続行する。利用可能なスキルはシステムプロンプトに記載されている。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "実行するスキル名",
                    },
                    "arguments": {
                        "type": "string",
                        "description": "スキルに渡す追加引数やコンテキスト（任意）",
                    },
                },
                "required": ["name"],
            },
        },
    },
]

# ─────────────────────────────────────────────
# ツール実装
# ─────────────────────────────────────────────


def _resolve_path(path: str) -> str:
    """~ を展開し、絶対パスに解決する。"""
    return str(Path(os.path.expanduser(path)).resolve())


def tool_run_command(
    command: str, cwd: Optional[str] = None, timeout: Optional[int] = None
) -> str:
    if timeout is None:
        timeout = _ACTIVE_CONFIG.get("timeout", 30)
    work_dir = _resolve_path(cwd) if cwd else None
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
        )
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"[stderr]\n{result.stderr}")
        output_parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(output_parts)
    except subprocess.TimeoutExpired:
        return f"[error] コマンドがタイムアウトしました（{timeout}秒）"
    except Exception as e:
        return f"[error] {e}"


def tool_read_file(
    path: str,
    encoding: str = "utf-8",
    offset: int = 0,
    limit: Optional[int] = None,
) -> str:
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding=encoding) as f:
            lines = f.readlines()
        total = len(lines)
        selected = lines[offset:] if limit is None else lines[offset : offset + limit]
        content = "".join(selected)
        if len(content) > 100_000:
            content = content[:100_000] + f"\n\n[...truncated, total {len(content)} chars]"
        header = f"[{resolved}] ({total} lines total"
        if offset > 0 or limit is not None:
            end = offset + len(selected)
            header += f", showing lines {offset + 1}-{end}"
        header += ")\n"
        return header + content
    except UnicodeDecodeError:
        return f"[error] バイナリファイルまたはエンコーディング '{encoding}' で読み込めません: {resolved}"
    except FileNotFoundError:
        return f"[error] ファイルが見つかりません: {resolved}"
    except PermissionError:
        return f"[error] 読み取り権限がありません: {resolved}"
    except Exception as e:
        return f"[error] {e}"


def tool_write_file(path: str, content: str, encoding: str = "utf-8") -> str:
    resolved = _resolve_path(path)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding=encoding) as f:
            f.write(content)
        return f"ファイルを書き込みました: {resolved} ({len(content)} chars)"
    except Exception as e:
        return f"[error] {e}"


def tool_edit_file(path: str, old_string: str, new_string: str) -> str:
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return f"[error] ファイルが見つかりません: {resolved}"
    except Exception as e:
        return f"[error] {e}"

    count = content.count(old_string)
    if count == 0:
        return f"[error] 指定した文字列が見つかりません: {resolved}"
    if count > 1:
        return f"[error] 指定した文字列が {count} 箇所見つかりました。ユニークな文字列を指定してください: {resolved}"

    new_content = content.replace(old_string, new_string, 1)
    try:
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)
        # diff を生成して返す
        diff_text = _generate_diff(content, new_content, resolved)
        return f"ファイルを編集しました: {resolved}\n{diff_text}"
    except Exception as e:
        return f"[error] 書き込みに失敗しました: {e}"


def _generate_diff(old: str, new: str, filename: str) -> str:
    """unified diff を生成する。"""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{os.path.basename(filename)}",
        tofile=f"b/{os.path.basename(filename)}",
        lineterm="",
    )
    return "".join(diff)


def tool_list_directory(
    path: Optional[str] = None, show_hidden: bool = False
) -> str:
    resolved = _resolve_path(path) if path else os.getcwd()
    try:
        entries = os.listdir(resolved)
        if not show_hidden:
            entries = [e for e in entries if not e.startswith(".")]
        entries.sort(key=str.lower)

        lines = []
        for entry in entries:
            full = os.path.join(resolved, entry)
            if os.path.isdir(full):
                lines.append(f"  [DIR]  {entry}")
            else:
                try:
                    size = os.path.getsize(full)
                    lines.append(f"  [FILE] {entry}  ({_human_size(size)})")
                except OSError:
                    lines.append(f"  [FILE] {entry}")

        header = f"Directory: {resolved}  ({len(entries)} items)\n"
        return header + "\n".join(lines) if lines else header + "  (empty)"
    except FileNotFoundError:
        return f"[error] ディレクトリが見つかりません: {resolved}"
    except PermissionError:
        return f"[error] アクセス権限がありません: {resolved}"
    except Exception as e:
        return f"[error] {e}"


def tool_search_files(pattern: str, path: Optional[str] = None) -> str:
    base = _resolve_path(path) if path else os.getcwd()
    search_pattern = os.path.join(base, pattern)
    try:
        matches = glob_mod.glob(search_pattern, recursive=True)
        matches.sort()
        if not matches:
            return f"パターン '{pattern}' にマッチするファイルはありません（検索先: {base}）"
        result_lines = [
            f"検索結果: {len(matches)} 件（パターン: {pattern}, 検索先: {base}）\n"
        ]
        for m in matches[:200]:
            try:
                rel = os.path.relpath(m, base)
            except ValueError:
                rel = m
            if os.path.isdir(m):
                result_lines.append(f"  [DIR]  {rel}")
            else:
                result_lines.append(f"  [FILE] {rel}")
        if len(matches) > 200:
            result_lines.append(f"\n  ... 他 {len(matches) - 200} 件")
        return "\n".join(result_lines)
    except Exception as e:
        return f"[error] {e}"


def tool_grep(
    pattern: str,
    path: Optional[str] = None,
    include: Optional[str] = None,
    ignore_case: bool = False,
) -> str:
    base = _resolve_path(path) if path else os.getcwd()
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"[error] 正規表現エラー: {e}"

    results = []
    max_results = 200

    def _search_file(filepath: str) -> None:
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if len(results) >= max_results:
                        return
                    if regex.search(line):
                        try:
                            rel = os.path.relpath(filepath, base)
                        except ValueError:
                            rel = filepath
                        results.append(f"  {rel}:{i}: {line.rstrip()}")
        except (OSError, PermissionError):
            pass

    base_path = Path(base)
    if base_path.is_file():
        _search_file(str(base_path))
    else:
        glob_pattern = include or "*"
        for filepath in base_path.rglob(glob_pattern):
            if filepath.is_file():
                _search_file(str(filepath))
                if len(results) >= max_results:
                    break

    if not results:
        return f"パターン '{pattern}' にマッチする行はありません（検索先: {base}）"

    header = f"grep 結果: {len(results)} 件"
    if len(results) >= max_results:
        header += f"（上限 {max_results} 件に達しました）"
    header += f"（パターン: {pattern}, 検索先: {base}）\n"
    return header + "\n".join(results)


def tool_get_file_info(path: str) -> str:
    resolved = _resolve_path(path)
    try:
        stat = os.stat(resolved)
        p = Path(resolved)
        info = {
            "パス": resolved,
            "種別": "ディレクトリ" if p.is_dir() else "ファイル",
            "サイズ": _human_size(stat.st_size),
            "サイズ(bytes)": stat.st_size,
            "更新日時": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "作成日時": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "最終アクセス": datetime.fromtimestamp(stat.st_atime).isoformat(),
        }
        if p.is_file():
            info["拡張子"] = p.suffix or "(なし)"
        return json.dumps(info, ensure_ascii=False, indent=2)
    except FileNotFoundError:
        return f"[error] パスが見つかりません: {resolved}"
    except Exception as e:
        return f"[error] {e}"


def tool_run_python_sandbox(code: str, timeout: Optional[int] = None) -> str:
    """Pythonコードをサンドボックス環境で実行する。

    制限:
    - タイムアウト（デフォルト30秒、最大60秒）
    - ネットワークアクセス不可（import制限による簡易ブロック）
    - ファイル書き込み不可（一時ディレクトリ内のみ許可）
    - 危険なモジュールの import を禁止
    """
    if timeout is None:
        timeout = min(_ACTIVE_CONFIG.get("timeout", 30), 60)
    else:
        timeout = min(timeout, 60)

    # 危険な import / 操作をチェック
    forbidden_patterns = [
        r'\bimport\s+(?:os|sys|subprocess|shutil|signal|ctypes|socket|http|urllib|requests|pathlib)\b',
        r'\bfrom\s+(?:os|sys|subprocess|shutil|signal|ctypes|socket|http|urllib|requests|pathlib)\b',
        r'\b__import__\s*\(',
        r'\bexec\s*\(',
        r'\beval\s*\(',
        r'\bopen\s*\(',
        r'\bglobals\s*\(',
        r'\blocals\s*\(',
        r'\bgetattr\s*\(',
        r'\bsetattr\s*\(',
        r'\bdelattr\s*\(',
        r'\bcompile\s*\(',
        r'\bbreakpoint\s*\(',
    ]
    for pat in forbidden_patterns:
        match = re.search(pat, code)
        if match:
            return f"[sandbox error] 禁止された操作が含まれています: {match.group()}\nサンドボックスでは os, sys, subprocess, open() 等は使用できません。\nファイル操作が必要な場合は run_command ツールを使ってください。"

    # サンドボックスラッパーコードを生成
    wrapper = f'''\
import sys
import resource

# リソース制限 (Unix系のみ)
try:
    # CPU時間制限
    resource.setrlimit(resource.RLIMIT_CPU, ({timeout}, {timeout}))
    # メモリ制限 (256MB)
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    # ファイル生成サイズ制限 (1MB)
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    # プロセス数制限
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except (ValueError, AttributeError):
    pass  # Windows等で resource が使えない場合はスキップ

# 標準入力を閉じる
sys.stdin = open("/dev/null", "r")

# ユーザーコード実行
'''
    wrapper += code

    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="codex_sandbox_")
        script_path = os.path.join(tmp_dir, "sandbox_script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapper)

        # サブプロセスで実行（環境変数を最小限に制限）
        env = {
            "PATH": "/usr/bin:/usr/local/bin:/bin",
            "HOME": tmp_dir,
            "TMPDIR": tmp_dir,
            "LANG": "en_US.UTF-8",
        }

        result = subprocess.run(
            [sys.executable, "-u", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=tmp_dir,
            env=env,
        )

        output_parts = []
        if result.stdout:
            stdout = result.stdout
            if len(stdout) > 50_000:
                stdout = stdout[:50_000] + f"\n[...truncated, total {len(result.stdout)} chars]"
            output_parts.append(stdout)
        if result.stderr:
            stderr = result.stderr
            if len(stderr) > 10_000:
                stderr = stderr[:10_000] + f"\n[...truncated]"
            output_parts.append(f"[stderr]\n{stderr}")
        output_parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return f"[sandbox error] 実行がタイムアウトしました（{timeout}秒）"
    except Exception as e:
        return f"[sandbox error] {e}"
    finally:
        # 一時ディレクトリのクリーンアップ
        if tmp_dir:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} PB"


def tool_run_skill(name: str, arguments: str = "") -> str:
    """スキルの指示をロードしてツール結果として返す。"""
    skill = _skill_registry.get_skill(name)
    if skill is None:
        available = ", ".join(s.name for s in _skill_registry.list_skills())
        return f"[error] スキル '{name}' が見つかりません。利用可能: {available or 'なし'}"

    instructions = _skill_registry.load_instructions(name)
    if not instructions:
        return f"[error] スキル '{name}' の読み込みに失敗しました"

    result = f"[skill:{name}] 以下のスキル指示に従って作業してください。\n\n{instructions}"
    if arguments:
        result += f"\n\n## ユーザーからの追加指示\n{arguments}"
    # 指示が長すぎる場合は切り詰め
    if len(result) > 10000:
        result = result[:10000] + "\n\n[...指示が長すぎるため切り詰めました]"
    return result


# ─────────────────────────────────────────────
# ツールディスパッチ
# ─────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "run_command": tool_run_command,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
    "list_directory": tool_list_directory,
    "search_files": tool_search_files,
    "grep": tool_grep,
    "get_file_info": tool_get_file_info,
    "run_python_sandbox": tool_run_python_sandbox,
    "run_skill": tool_run_skill,
}

DESTRUCTIVE_TOOLS = {"run_command", "write_file", "edit_file"}

# 設定のグローバル参照（main で上書き）
_ACTIVE_CONFIG: dict = dict(DEFAULT_CONFIG)


def execute_tool(name: str, arguments: dict) -> str:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"[error] 不明なツール: {name}"
    try:
        return fn(**arguments)
    except Exception as e:
        return f"[error] ツール実行エラー ({name}): {e}"


# ─────────────────────────────────────────────
# ユーザー確認（diff 表示付き）
# ─────────────────────────────────────────────


def _colorize_diff(diff_text: str) -> str:
    """diff テキストを色付きにする。"""
    lines = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(_bold(line))
        elif line.startswith("@@"):
            lines.append(_cyan(line))
        elif line.startswith("+"):
            lines.append(_green(line))
        elif line.startswith("-"):
            lines.append(_red(line))
        else:
            lines.append(line)
    return "\n".join(lines)


def _preview_diff_for_edit(args: dict) -> str:
    """edit_file の確認時にプレビュー diff を生成する。"""
    path = args.get("path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            content = f.read()
        new_content = content.replace(old_string, new_string, 1)
        diff_text = _generate_diff(content, new_content, resolved)
        return _colorize_diff(diff_text)
    except Exception:
        # プレビューが生成できない場合は簡易表示
        return ""


def _ask_confirmation_gui(tool_name: str, args: dict) -> bool:
    """GUI モード: confirm_request を emit してレスポンスを待つ。"""
    confirm_id = str(uuid.uuid4())

    preview = ""
    if tool_name == "edit_file":
        try:
            path = args.get("path", "")
            old_str = args.get("old_string", "")
            new_str = args.get("new_string", "")
            resolved = _resolve_path(path)
            with open(resolved, "r", encoding="utf-8") as f:
                content = f.read()
            new_content = content.replace(old_str, new_str, 1)
            preview = _generate_diff(content, new_content, resolved)[:2000]
        except Exception:
            preview = ""

    event = threading.Event()
    with _confirm_lock:
        _confirm_events[confirm_id] = event
        _confirm_results[confirm_id] = False

    _emit({
        "type": "confirm_request",
        "id": confirm_id,
        "tool": tool_name,
        "args": args,
        "preview": preview,
    })

    event.wait(timeout=300)

    with _confirm_lock:
        result = _confirm_results.pop(confirm_id, False)
        _confirm_events.pop(confirm_id, None)
    return result


def _resolve_confirmation(confirm_id: str, approved: bool) -> None:
    """stdin スレッドから呼ばれる: 確認イベントを解決する。"""
    with _confirm_lock:
        _confirm_results[confirm_id] = approved
        event = _confirm_events.get(confirm_id)
    if event:
        event.set()


def _ask_confirmation(tool_name: str, args: dict) -> bool:
    """破壊的操作の実行前にユーザーに確認する。"""
    if _GUI_MODE:
        return _ask_confirmation_gui(tool_name, args)
    print()
    print(_yellow("  ⚠ 確認が必要な操作:"))
    if tool_name == "run_command":
        print(f"    コマンド: {_bold(args.get('command', ''))}")
        if args.get("cwd"):
            print(f"    ディレクトリ: {args['cwd']}")
    elif tool_name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        print(f"    ファイル書き込み: {_bold(path)}")
        print(f"    サイズ: {len(content)} chars")
    elif tool_name == "edit_file":
        print(f"    ファイル編集: {_bold(args.get('path', ''))}")
        diff_preview = _preview_diff_for_edit(args)
        if diff_preview:
            # diff が短ければ全部、長ければ先頭を表示
            diff_lines = diff_preview.splitlines()
            if len(diff_lines) > 20:
                print("\n".join(f"    {l}" for l in diff_lines[:20]))
                print(_dim(f"    ... (他 {len(diff_lines) - 20} 行)"))
            else:
                print("\n".join(f"    {l}" for l in diff_lines))
        else:
            old = args.get("old_string", "")
            new = args.get("new_string", "")
            preview_old = old[:80] + "..." if len(old) > 80 else old
            preview_new = new[:80] + "..." if len(new) > 80 else new
            print(f"    - {_red(repr(preview_old))}")
            print(f"    + {_green(repr(preview_new))}")

    try:
        answer = input(_yellow("  実行しますか? [Y/n] ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes")


# ─────────────────────────────────────────────
# 画像読み込み
# ─────────────────────────────────────────────

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _is_image_file(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTENSIONS


def _encode_image_to_data_url(path: str) -> Optional[str]:
    """画像ファイルを data URL に変換する。"""
    resolved = _resolve_path(path)
    if not os.path.isfile(resolved):
        return None
    suffix = Path(resolved).suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(suffix, "image/png")
    try:
        with open(resolved, "rb") as f:
            data = f.read()
        if len(data) > 20 * 1024 * 1024:  # 20MB 制限
            return None
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _build_image_message(path: str, user_text: str = "") -> Optional[dict]:
    """画像を含む user メッセージを構築する。"""
    data_url = _encode_image_to_data_url(path)
    if data_url is None:
        return None
    content = []
    if user_text:
        content.append({"type": "text", "text": user_text})
    content.append({
        "type": "image_url",
        "image_url": {"url": data_url},
    })
    return {"role": "user", "content": content}


# ─────────────────────────────────────────────
# コンテキスト管理
# ─────────────────────────────────────────────


def _estimate_tokens(messages: list) -> int:
    """雑なトークン数推定（1 token ≒ 4文字）。"""
    total = 0
    for m in messages:
        if isinstance(m, dict):
            content = m.get("content", "")
            if isinstance(content, str) and content:
                total += len(content) // 4
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            total += len(part.get("text", "")) // 4
                        elif part.get("type") == "image_url":
                            total += 1000  # 画像は概算
            for tc in m.get("tool_calls", []):
                if isinstance(tc, dict):
                    total += len(tc.get("function", {}).get("arguments", "")) // 4
        else:
            content = getattr(m, "content", "") or ""
            total += len(content) // 4
    return total


def _compact_messages(client: OpenAI, messages: list, config: dict) -> list:
    """会話を要約して圧縮する。"""
    keep_recent = config.get("compact_keep_recent", 10)
    if len(messages) <= keep_recent + 1:
        return messages

    system_msg = messages[0]
    old_messages = messages[1 : -keep_recent]
    recent_messages = messages[-keep_recent:]

    summary_parts = []
    for m in old_messages:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
        else:
            role = getattr(m, "role", "")
            content = getattr(m, "content", "") or ""
        if content and role in ("user", "assistant"):
            preview = content[:300]
            summary_parts.append(f"[{role}] {preview}")

    if not summary_parts:
        return messages

    summary_text = "\n".join(summary_parts)

    try:
        resp = client.chat.completions.create(
            model=config.get("model", "gpt-4.1-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "以下の会話履歴を簡潔に要約してください。重要な情報（ファイルパス、実行結果、ユーザーの意図）を保持してください。日本語で。",
                },
                {"role": "user", "content": summary_text},
            ],
            max_tokens=500,
        )
        summary = resp.choices[0].message.content or "(要約なし)"
    except Exception:
        summary = summary_text[:500] + "..."

    new_messages = [
        system_msg,
        {"role": "user", "content": f"[以前の会話の要約]\n{summary}"},
        {"role": "assistant", "content": "了解しました。以前の会話内容を把握しています。続けてください。"},
    ] + recent_messages

    return new_messages


def _auto_trim(messages: list, config: dict) -> list:
    max_msgs = config.get("max_context_messages", 200)
    if len(messages) <= max_msgs:
        return messages
    system_msg = messages[0]
    return [system_msg] + messages[-(max_msgs - 1) :]


# ─────────────────────────────────────────────
# チャットループ（ストリーミング + 並列ツール実行）
# ─────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


def _api_call_with_retry(client: OpenAI, **kwargs):
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            retryable = any(
                kw in err_str
                for kw in ("rate limit", "429", "500", "502", "503", "timeout", "connection")
            )
            if not retryable or attempt == MAX_RETRIES - 1:
                raise
            wait = RETRY_BACKOFF * (2 ** attempt)
            print(_dim(f"  ↻ リトライ ({attempt + 1}/{MAX_RETRIES}) {wait:.0f}秒後..."))
            time.sleep(wait)
    raise last_err  # type: ignore


def _execute_tools_parallel(
    tool_calls_data: list,
    auto_confirm: bool,
) -> list:
    """複数ツールを並列実行する。破壊的操作は直列で確認する。"""
    results = [None] * len(tool_calls_data)

    # 破壊的操作と安全な操作を分離
    safe_indices = []
    destructive_indices = []
    for i, tc_data in enumerate(tool_calls_data):
        fn_name = tc_data["function"]["name"]
        if fn_name in DESTRUCTIVE_TOOLS and not auto_confirm:
            destructive_indices.append(i)
        else:
            safe_indices.append(i)

    # 安全な操作は並列実行
    if safe_indices:
        def _run(idx: int) -> tuple:
            tc = tool_calls_data[idx]
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}
            return idx, fn_name, fn_args, execute_tool(fn_name, fn_args)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_run, i): i for i in safe_indices}
            for future in concurrent.futures.as_completed(futures):
                idx, fn_name, fn_args, result = future.result()
                results[idx] = (fn_name, fn_args, result)

    # 破壊的操作は直列で確認
    for i in destructive_indices:
        tc = tool_calls_data[i]
        fn_name = tc["function"]["name"]
        try:
            fn_args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            fn_args = {}

        if not _ask_confirmation(fn_name, fn_args):
            results[i] = (fn_name, fn_args, "[skipped] ユーザーがキャンセルしました")
        else:
            results[i] = (fn_name, fn_args, execute_tool(fn_name, fn_args))

    return results


def chat(
    client: OpenAI,
    messages: list,
    config: dict,
    auto_confirm: bool = False,
) -> str:
    """
    OpenAI API にストリーミングでメッセージを送り、ツール呼び出しがあれば実行して
    最終的なアシスタントの応答テキストを返す。
    """
    model = config.get("model", "gpt-4.1-mini")

    while True:
        spinner = Spinner("thinking...")
        spinner.start()
        stream = _api_call_with_retry(
            client,
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            stream=True,
        )

        collected_content = []
        collected_tool_calls: dict = {}
        first_text = True

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                if first_text:
                    spinner.stop()
                    if not _GUI_MODE:
                        print()
                    first_text = False
                if _GUI_MODE:
                    _emit({"type": "token", "content": delta.content})
                else:
                    sys.stdout.write(delta.content)
                    sys.stdout.flush()
                collected_content.append(delta.content)

            if delta.tool_calls:
                if first_text:
                    spinner.stop()
                    first_text = False
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "id": "",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = collected_tool_calls[idx]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments

        spinner.stop()
        full_content = "".join(collected_content)

        if not collected_tool_calls:
            if _GUI_MODE:
                _emit({"type": "assistant_done", "content": full_content})
            else:
                if full_content:
                    print()
            messages.append({"role": "assistant", "content": full_content})
            return full_content

        # assistant メッセージ構築
        tool_calls_list = []
        for idx in sorted(collected_tool_calls.keys()):
            tc = collected_tool_calls[idx]
            tool_calls_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })

        assistant_msg = {
            "role": "assistant",
            "content": full_content or None,
            "tool_calls": tool_calls_list,
        }
        messages.append(assistant_msg)

        # ツール呼び出し表示
        for tc_data in tool_calls_list:
            fn_name = tc_data["function"]["name"]
            try:
                fn_args = json.loads(tc_data["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}
            if _GUI_MODE:
                _emit({"type": "tool_call", "name": fn_name, "args": fn_args})
            else:
                args_preview = json.dumps(fn_args, ensure_ascii=False)
                if len(args_preview) > 120:
                    args_preview = args_preview[:120] + "..."
                print(f"\n  {_cyan('⚡')} {_bold(fn_name)}{_dim('(' + args_preview + ')')}")

        # 並列 / 直列でツール実行
        if len(tool_calls_list) > 1:
            results = _execute_tools_parallel(tool_calls_list, auto_confirm)
            for i, (tc_data, result_tuple) in enumerate(zip(tool_calls_list, results)):
                fn_name, fn_args, result = result_tuple
                status = "error" if result.startswith("[error]") else \
                         "skipped" if result.startswith("[skipped]") else "ok"
                if _GUI_MODE:
                    _emit({"type": "tool_result", "name": fn_name,
                           "result": result[:500], "status": status})
                else:
                    result_preview = result.replace("\n", " ")[:150]
                    if status != "ok":
                        print(f"  {_red('↳')} {_dim(fn_name + ': ' + result_preview)}")
                    else:
                        print(f"  {_green('↳')} {_dim(fn_name + ': ' + result_preview)}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_data["id"],
                    "content": result,
                })
        else:
            # 単一ツールの場合
            tc_data = tool_calls_list[0]
            fn_name = tc_data["function"]["name"]
            try:
                fn_args = json.loads(tc_data["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            if fn_name in DESTRUCTIVE_TOOLS and not auto_confirm:
                if not _ask_confirmation(fn_name, fn_args):
                    result = "[skipped] ユーザーがキャンセルしました"
                    if _GUI_MODE:
                        _emit({"type": "tool_result", "name": fn_name,
                               "result": result, "status": "skipped"})
                    else:
                        print(f"  {_yellow('↳')} {_dim(result)}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_data["id"],
                        "content": result,
                    })
                    continue
            result = execute_tool(fn_name, fn_args)
            status = "error" if result.startswith("[error]") else "ok"
            if _GUI_MODE:
                _emit({"type": "tool_result", "name": fn_name,
                       "result": result[:500], "status": status})
            else:
                result_preview = result.replace("\n", " ")[:150]
                if result.startswith("[error]"):
                    print(f"  {_red('↳')} {_dim(result_preview)}")
                else:
                    print(f"  {_green('↳')} {_dim(result_preview)}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc_data["id"],
                "content": result,
            })


# ─────────────────────────────────────────────
# スラッシュコマンド
# ─────────────────────────────────────────────

SLASH_COMMANDS = {}


def slash_command(name: str, description: str):
    def decorator(fn):
        SLASH_COMMANDS[name] = {"fn": fn, "desc": description}
        return fn
    return decorator


@slash_command("help", "利用可能なコマンドを表示")
def cmd_help(**_) -> None:
    print(f"\n{_bold('利用可能なコマンド:')}\n")
    for name, info in sorted(SLASH_COMMANDS.items()):
        print(f"  {_cyan('/' + name):24s} {info['desc']}")
    print(f"\n  {_dim('quit / exit / q')}           終了")
    print(f"  {_dim('複数行入力:')}               << で開始、>> で終了")
    print(f"  {_dim('画像を送る:')}               /image <path> [質問]")


@slash_command("clear", "会話履歴をクリア")
def cmd_clear(messages: list, **_) -> None:
    system_msg = messages[0]
    messages.clear()
    messages.append(system_msg)
    print(_green("  会話履歴をクリアしました。"))


@slash_command("compact", "会話履歴を要約して圧縮")
def cmd_compact(client: OpenAI, messages: list, config: dict, **_) -> None:
    before = len(messages)
    before_tokens = _estimate_tokens(messages)
    new = _compact_messages(client, messages, config)
    messages.clear()
    messages.extend(new)
    after_tokens = _estimate_tokens(messages)
    print(
        _green(
            f"  会話を圧縮しました: {before} → {len(messages)} メッセージ "
            f"(≈{before_tokens} → {after_tokens} tokens)"
        )
    )


@slash_command("history", "会話履歴のサマリーを表示")
def cmd_history(messages: list, **_) -> None:
    print(f"\n{_bold('会話履歴')} ({len(messages)} メッセージ, ≈{_estimate_tokens(messages)} tokens)\n")
    for i, m in enumerate(messages):
        if isinstance(m, dict):
            role = m.get("role", "?")
            content = m.get("content", "") or ""
            if isinstance(content, list):
                content = "[multimodal]"
        else:
            role = getattr(m, "role", "?")
            content = getattr(m, "content", "") or ""
        preview = str(content).replace("\n", " ")[:80]
        color_fn = {
            "system": _magenta,
            "user": _cyan,
            "assistant": _green,
            "tool": _dim,
        }.get(role, _dim)
        print(f"  {_dim(str(i)):>4s}  {color_fn(role):12s} {preview}")


@slash_command("tokens", "現在のトークン使用量の概算を表示")
def cmd_tokens(messages: list, config: dict, **_) -> None:
    est = _estimate_tokens(messages)
    print(f"  メッセージ数: {len(messages)}")
    print(f"  推定トークン数: ≈{est}")
    print(f"  コンテキスト上限: ≈128,000 tokens")
    usage_pct = min(100, est * 100 // 128000)
    bar_len = 30
    filled = bar_len * usage_pct // 100
    bar = "█" * filled + "░" * (bar_len - filled)
    color = _green if usage_pct < 60 else (_yellow if usage_pct < 85 else _red)
    print(f"  使用率: {color(f'{bar} {usage_pct}%')}")


@slash_command("autoconfirm", "自動確認モードを切り替え")
def cmd_autoconfirm(state: dict, config: dict, **_) -> None:
    state["auto_confirm"] = not state.get("auto_confirm", False)
    config["auto_confirm"] = state["auto_confirm"]
    mode = "ON" if state["auto_confirm"] else "OFF"
    color = _red if state["auto_confirm"] else _green
    print(color(f"  自動確認モード: {mode}"))


@slash_command("model", "使用モデルを変更 (例: /model gpt-4.1)")
def cmd_model(config: dict, state: dict, args: str = "", **_) -> None:
    if not args:
        print(f"  現在のモデル: {_bold(config.get('model', 'gpt-4.1-mini'))}")
        print(f"  変更: /model <モデル名>")
        print(f"  例: /model gpt-4.1")
        print(f"      /model gpt-4.1-mini")
        print(f"      /model gpt-4.1-nano")
        return
    new_model = args.strip()
    config["model"] = new_model
    print(_green(f"  モデルを変更しました: {_bold(new_model)}"))


@slash_command("config", "設定の表示・変更")
def cmd_config(config: dict, args: str = "", **_) -> None:
    if not args:
        print(f"\n{_bold('現在の設定:')}\n")
        for k, v in sorted(config.items()):
            default = DEFAULT_CONFIG.get(k)
            changed = " " + _yellow("(変更済み)") if v != default else ""
            print(f"  {_cyan(k):30s} {json.dumps(v, ensure_ascii=False)}{changed}")
        print(f"\n  設定ファイル: {_CONFIG_FILE}")
        print(f"  変更: /config <key> <value>")
        print(f"  保存: /config save")
        return

    parts = args.strip().split(None, 1)
    if parts[0] == "save":
        _save_config(config)
        print(_green(f"  設定を保存しました: {_CONFIG_FILE}"))
        return

    if len(parts) < 2:
        print(_red(f"  使い方: /config <key> <value>"))
        return

    key, val_str = parts
    if key not in DEFAULT_CONFIG:
        print(_red(f"  不明な設定キー: {key}"))
        return

    # 型に合わせて変換
    default_val = DEFAULT_CONFIG[key]
    try:
        if isinstance(default_val, bool):
            val = val_str.lower() in ("true", "1", "yes", "on")
        elif isinstance(default_val, int):
            val = int(val_str)
        else:
            val = val_str
        config[key] = val
        print(_green(f"  {key} = {json.dumps(val, ensure_ascii=False)}"))
    except ValueError:
        print(_red(f"  値の変換に失敗しました: {val_str}"))


@slash_command("image", "画像を送信して質問する (例: /image screenshot.png これは何？)")
def cmd_image(messages: list, client: OpenAI, config: dict, state: dict, args: str = "", **_) -> None:
    if not args:
        print(_red("  使い方: /image <画像パス> [質問テキスト]"))
        return

    parts = args.strip().split(None, 1)
    image_path = parts[0]
    question = parts[1] if len(parts) > 1 else "この画像を説明してください。"

    resolved = _resolve_path(image_path)
    if not os.path.isfile(resolved):
        print(_red(f"  ファイルが見つかりません: {resolved}"))
        return
    if not _is_image_file(resolved):
        print(_red(f"  対応していない画像形式です: {resolved}"))
        print(_dim(f"  対応形式: {', '.join(_IMAGE_EXTENSIONS)}"))
        return

    size = os.path.getsize(resolved)
    print(f"  {_cyan('📷')} {os.path.basename(resolved)} ({_human_size(size)})")

    img_msg = _build_image_message(resolved, question)
    if img_msg is None:
        print(_red("  画像の読み込みに失敗しました"))
        return

    messages.append(img_msg)
    try:
        chat(client, messages, config, auto_confirm=state.get("auto_confirm", False))
    except KeyboardInterrupt:
        print(_yellow("\n  中断しました。"))
    except Exception as e:
        print(f"\n{_red('[API error]')} {e}")
        messages.pop()


@slash_command("skills", "利用可能なスキル一覧を表示 (/skills reload で再読み込み)")
def cmd_skills(args: str = "", **_) -> None:
    if args.strip() == "reload":
        _skill_registry.scan()
        count = len(_skill_registry.list_skills())
        print(_green(f"  スキルを再読み込みしました: {count} 個"))
        return
    skills = _skill_registry.list_skills()
    if not skills:
        print(_dim("  スキルが見つかりません"))
        print(_dim(f"  グローバル: ~/.codex_modoki/skills/<name>/SKILL.md"))
        print(_dim(f"  プロジェクト: ./skills/<name>/SKILL.md"))
        return
    print(f"\n{_bold('利用可能なスキル:')}\n")
    for s in skills:
        source_tag = _dim(f"[{s.source}]")
        print(f"  {_cyan(s.name):30s} {s.description} {source_tag}")
    print(f"\n  {_dim('使い方: /skill <name> [arguments]')}")
    print(f"  {_dim('リロード: /skills reload')}")


@slash_command("skill", "スキルを実行する (例: /skill commit-message)")
def cmd_skill(messages: list, client: OpenAI, config: dict, state: dict, args: str = "", **_) -> None:
    if not args:
        print(_red("  使い方: /skill <name> [arguments]"))
        print(_dim("  /skills で一覧表示"))
        return

    parts = args.strip().split(None, 1)
    skill_name = parts[0]
    skill_args = parts[1] if len(parts) > 1 else ""

    skill = _skill_registry.get_skill(skill_name)
    if skill is None:
        print(_red(f"  スキル '{skill_name}' が見つかりません"))
        print(_dim("  /skills で一覧表示"))
        return

    instructions = _skill_registry.load_instructions(skill_name)
    if not instructions:
        print(_red(f"  スキル '{skill_name}' の読み込みに失敗しました"))
        return

    content = f"[スキル実行: {skill_name}]\n\n{instructions}"
    if skill_args:
        content += f"\n\n## 追加指示\n{skill_args}"

    messages.append({"role": "user", "content": content})
    print(f"  {_cyan('🔧')} スキル '{skill_name}' を実行中...")

    try:
        chat(client, messages, config, auto_confirm=state.get("auto_confirm", False))
    except KeyboardInterrupt:
        print(_yellow("\n  中断しました。"))
    except Exception as e:
        print(f"\n{_red('[API error]')} {e}")
        messages.pop()


# ─────────────────────────────────────────────
# 複数行入力
# ─────────────────────────────────────────────


def _read_multiline() -> str:
    print(_dim("  (複数行入力モード: >> で終了)"))
    lines = []
    while True:
        try:
            line = input(_dim("... "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip() == ">>":
            break
        lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# GUI メイン (Electron IPC)
# ─────────────────────────────────────────────

_chat_in_progress = threading.Event()


def gui_main():
    """GUI モードのメインループ: stdin から JSON を読み、chat() を呼ぶ。"""
    global _GUI_MODE, _ACTIVE_CONFIG
    _GUI_MODE = True

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _emit({"type": "error", "message": "OPENAI_API_KEY が設定されていません"})
        sys.exit(1)

    base_url = os.environ.get("OPENAI_BASE_URL")
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    config = _load_config()
    _ACTIVE_CONFIG = config
    state = {"auto_confirm": config.get("auto_confirm", False)}

    # スキルのスキャン
    _skill_registry.scan()

    # 初回自動コンテキスト収集
    project_context = ""
    if config.get("auto_context", True):
        _emit({"type": "status", "message": "プロジェクトコンテキストを収集中..."})
        try:
            project_context = _collect_project_context(
                max_files=config.get("auto_context_max_files", 50)
            )
        except Exception:
            pass

    system_prompt = _build_system_prompt(config, project_context)
    messages: list = [{"role": "system", "content": system_prompt}]

    # 初期情報を Electron に送信
    _emit({
        "type": "system_info",
        "model": config.get("model", "gpt-4.1-mini"),
        "cwd": os.getcwd(),
        "os": platform.system(),
        "has_context": bool(project_context),
        "skills": [
            {"name": s.name, "description": s.description, "source": s.source}
            for s in _skill_registry.list_skills()
        ],
    })

    # stdin 読み取りループ（メインスレッド）
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type")

        if msg_type == "confirm_response":
            _resolve_confirmation(msg["id"], msg.get("approved", False))

        elif msg_type == "user_message":
            content = msg.get("content", "").strip()
            if not content:
                continue

            if _chat_in_progress.is_set():
                _emit({"type": "error", "message": "処理中です。完了をお待ちください。"})
                continue

            messages_ref = messages  # 参照を保持
            messages_ref[:] = _auto_trim(messages_ref, config)
            messages_ref.append({"role": "user", "content": content})

            _chat_in_progress.set()

            def _run_chat(msgs=messages_ref):
                try:
                    chat(client, msgs, config,
                         auto_confirm=state.get("auto_confirm", False))
                except Exception as e:
                    _emit({"type": "error", "message": str(e)})
                    if msgs and msgs[-1].get("role") == "user":
                        msgs.pop()
                finally:
                    _chat_in_progress.clear()
                    _emit({"type": "chat_finished"})

            t = threading.Thread(target=_run_chat, daemon=True)
            t.start()

        elif msg_type == "command":
            cmd_name = msg.get("name", "")
            cmd_args = msg.get("args", "")
            if cmd_name == "clear":
                system_msg = messages[0]
                messages.clear()
                messages.append(system_msg)
                _emit({"type": "status", "message": "会話履歴をクリアしました"})
            elif cmd_name == "compact":
                new = _compact_messages(client, messages, config)
                messages.clear()
                messages.extend(new)
                _emit({"type": "status",
                       "message": f"会話を圧縮しました: {len(messages)} メッセージ"})
            elif cmd_name == "autoconfirm":
                state["auto_confirm"] = not state.get("auto_confirm", False)
                _emit({"type": "status",
                       "message": f"自動確認: {'ON' if state['auto_confirm'] else 'OFF'}"})
            elif cmd_name == "model" and cmd_args:
                config["model"] = cmd_args
                _emit({"type": "status", "message": f"モデル変更: {cmd_args}"})
            elif cmd_name == "skills":
                skills = _skill_registry.list_skills()
                _emit({
                    "type": "skills_list",
                    "skills": [
                        {"name": s.name, "description": s.description, "source": s.source}
                        for s in skills
                    ],
                })
            elif cmd_name == "skills_reload":
                _skill_registry.scan()
                skills = _skill_registry.list_skills()
                _emit({
                    "type": "skills_list",
                    "skills": [
                        {"name": s.name, "description": s.description, "source": s.source}
                        for s in skills
                    ],
                })
                _emit({"type": "status",
                       "message": f"スキルを再読み込みしました: {len(skills)} 個"})
            elif cmd_name == "run_skill" and cmd_args:
                parts = cmd_args.strip().split(None, 1)
                skill_name = parts[0]
                skill_extra = parts[1] if len(parts) > 1 else ""
                skill = _skill_registry.get_skill(skill_name)
                if skill is None:
                    _emit({"type": "error",
                           "message": f"スキル '{skill_name}' が見つかりません"})
                elif _chat_in_progress.is_set():
                    _emit({"type": "error", "message": "処理中です。完了をお待ちください。"})
                else:
                    instructions = _skill_registry.load_instructions(skill_name)
                    if not instructions:
                        _emit({"type": "error",
                               "message": f"スキル '{skill_name}' の読み込みに失敗しました"})
                    else:
                        content = f"[スキル実行: {skill_name}]\n\n{instructions}"
                        if skill_extra:
                            content += f"\n\n## 追加指示\n{skill_extra}"
                        messages.append({"role": "user", "content": content})
                        _chat_in_progress.set()

                        def _run_skill_chat(msgs=messages):
                            try:
                                chat(client, msgs, config,
                                     auto_confirm=state.get("auto_confirm", False))
                            except Exception as e:
                                _emit({"type": "error", "message": str(e)})
                            finally:
                                _chat_in_progress.clear()
                                _emit({"type": "chat_finished"})

                        t = threading.Thread(target=_run_skill_chat, daemon=True)
                        t.start()


# ─────────────────────────────────────────────
# メイン (CLI REPL)
# ─────────────────────────────────────────────


def main():
    global _ACTIVE_CONFIG

    parser = argparse.ArgumentParser(description="codex_modoki agent")
    parser.add_argument("--gui", action="store_true",
                        help="Electron GUI モードで起動 (stdio JSON Lines)")
    args = parser.parse_args()

    if args.gui:
        gui_main()
        return

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("エラー: 環境変数 OPENAI_API_KEY を設定してください。")
        print("  export OPENAI_API_KEY='sk-...'       (macOS/Linux)")
        print("  $env:OPENAI_API_KEY='sk-...'         (Windows PowerShell)")
        sys.exit(1)

    base_url = os.environ.get("OPENAI_BASE_URL")
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    config = _load_config()
    _ACTIVE_CONFIG = config

    state = {"auto_confirm": config.get("auto_confirm", False)}

    # スキルのスキャン
    _skill_registry.scan()
    skill_count = len(_skill_registry.list_skills())

    # 初回自動コンテキスト収集
    project_context = ""
    if config.get("auto_context", True):
        print(_dim("  プロジェクトコンテキストを収集中..."))
        try:
            project_context = _collect_project_context(
                max_files=config.get("auto_context_max_files", 50)
            )
        except Exception:
            pass

    system_prompt = _build_system_prompt(config, project_context)
    messages: list = [
        {"role": "system", "content": system_prompt},
    ]

    print("=" * 60)
    print(f"  {_bold('codex_modoki')} - ローカルファイル操作エージェント")
    print(f"  OS: {platform.system()} | CWD: {os.getcwd()}")
    print(f"  Model: {config.get('model', 'gpt-4.1-mini')}")
    if base_url:
        print(f"  Base URL: {base_url}")
    if project_context:
        print(f"  {_green('✓')} プロジェクトコンテキスト読み込み済み")
    if skill_count > 0:
        print(f"  {_green('✓')} スキル: {skill_count} 個読み込み済み (/skills で一覧)")
    print(f"  {_dim('/help でコマンド一覧 | quit で終了')}")
    print("=" * 60)

    while True:
        try:
            user_input = input(f"\n{_bold('>')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        if user_input == "<<":
            user_input = _read_multiline()
            if not user_input:
                continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        # スラッシュコマンド
        if user_input.startswith("/"):
            parts = user_input[1:].split(None, 1)
            cmd_name = parts[0].lower()
            cmd_args = parts[1] if len(parts) > 1 else ""
            if cmd_name in SLASH_COMMANDS:
                SLASH_COMMANDS[cmd_name]["fn"](
                    client=client,
                    messages=messages,
                    config=config,
                    state=state,
                    args=cmd_args,
                )
                continue
            else:
                print(_red(f"  不明なコマンド: /{cmd_name}  (/help で一覧表示)"))
                continue

        messages = _auto_trim(messages, config)
        messages.append({"role": "user", "content": user_input})

        try:
            chat(
                client,
                messages,
                config,
                auto_confirm=state.get("auto_confirm", False),
            )
        except KeyboardInterrupt:
            print(_yellow("\n  中断しました。"))
        except Exception as e:
            print(f"\n{_red('[API error]')} {e}")
            messages.pop()


if __name__ == "__main__":
    main()
