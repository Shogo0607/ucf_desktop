#!/usr/bin/env python3
"""
database/ 内のファイルを横断検索するツール。
対応形式: JSON（PDF由来）、Markdown、CSV、テキスト

Usage:
    # ファイル一覧を表示（JSON / md / csv / txt）
    uv run python skills/rag/scripts/search_json.py list [--dir database]

    # 全ファイルからキーワード検索（複数キーワードはスペース区切りでAND検索）
    uv run python skills/rag/scripts/search_json.py search "キーワード" [--dir database]

    # 特定の JSON ファイルから指定ページの全文を取得
    uv run python skills/rag/scripts/search_json.py get_page "file.json" 3 [--dir database]

    # 特定の JSON ファイルの全サマリーを一覧表示
    uv run python skills/rag/scripts/search_json.py summaries "file.json" [--dir database]

    # 任意のテキストファイル（md/csv/txt）の内容を表示
    uv run python skills/rag/scripts/search_json.py read_file "path/to/file.md" [--dir database]

    # 全ファイルのサマリーからキーワードを抽出して一覧表示
    uv run python skills/rag/scripts/search_json.py keywords [--dir database]
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path

SUPPORTED_EXTENSIONS = {".json", ".md", ".csv", ".txt"}


def find_files(directory: str, extensions: set = None) -> list[Path]:
    """database/ 内のファイルを再帰的に検索する。"""
    if extensions is None:
        extensions = SUPPORTED_EXTENSIONS
    base = Path(directory)
    if not base.exists():
        return []
    files = []
    for f in sorted(base.rglob("*")):
        if f.is_file() and f.suffix.lower() in extensions and not f.name.startswith("."):
            files.append(f)
    return files


def find_json_files(directory: str) -> list[Path]:
    return find_files(directory, {".json"})


# ─── keywords extraction ────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """テキストから検索用キーワードを抽出する。

    形態素解析器なしで動作するため、以下のパターンで抽出する:
    1. 漢字熟語（2〜8文字の漢字連続）
    2. カタカナ語（2文字以上）
    3. 「お〜」で始まる和語（例: お手入れ）
    4. 句読点区切りの短いフレーズ
    """
    if not text:
        return []

    keywords = set()

    # 1. 漢字の連続（2〜8文字）— 日本語の技術用語の大半をカバー
    for m in re.finditer(r'[\u4e00-\u9fff]{2,8}', text):
        keywords.add(m.group())

    # 2. カタカナの連続（2文字以上、長音記号を含む）
    for m in re.finditer(r'[\u30a0-\u30ffー]{2,}', text):
        keywords.add(m.group())

    # 3. 「お」+ひらがな/漢字 パターン（例: お手入れ、おそうじ）
    for m in re.finditer(r'お[\u3040-\u309f\u4e00-\u9fff]{2,6}', text):
        kw = re.sub(r'[のがはをにでともやへ]+$', '', m.group())
        if len(kw) >= 3:
            keywords.add(kw)

    # 4. 句読点・括弧で区切った短いフレーズ（漢字+かな混在の複合語を拾う）
    for phrase in re.split(r'[。、．，「」（）【】\n・]', text):
        phrase = phrase.strip()
        # 短すぎる・長すぎるフレーズは除外
        if 3 <= len(phrase) <= 12:
            # ひらがなだけのフレーズは除外
            if not re.search(r'[\u4e00-\u9fff\u30a0-\u30ff]', phrase):
                continue
            # 「この〜」「その〜」で始まるフレーズは除外
            if re.match(r'^(この|その|あの|それ|これ|あれ)', phrase):
                continue
            keywords.add(phrase)

    # 汎用すぎる語・文末表現を除外
    stopwords = {
        'されて', 'しています', 'ています', 'について', 'において',
        'における', 'として', 'ために', 'それぞれ', 'これら',
        'そのため', 'できます', 'ありません', 'ください', 'おります',
        'このページ', 'されています', 'また', 'および', 'さらに',
        'ただし', 'なお', 'ほか', 'ことが', 'ものが',
        '説明', '記載', '案内', 'ページ',
    }
    keywords -= stopwords

    return sorted(kw for kw in keywords if 2 <= len(kw) <= 12)


def cmd_keywords(directory: str):
    """全ファイルのサマリーからキーワードを抽出し、ページごとに一覧表示する。
    エージェントがこの一覧からクエリに最適なキーワードを選定して search に渡す。"""
    files = find_files(directory)
    if not files:
        print("対応ファイルが見つかりません。")
        return

    base = Path(directory)
    total_keywords = set()

    for f in files:
        if f.suffix == ".json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            if not isinstance(data, list):
                continue

            rel = f.relative_to(base)
            print(f"=== {rel} ===")
            for entry in data:
                summary = entry.get("summary", "")
                page = entry.get("page", "?")
                kws = _extract_keywords(summary)
                total_keywords.update(kws)
                if kws:
                    print(f"  Page {page}: {', '.join(kws)}")
            print()
        else:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    content = fh.read(1000)
            except Exception:
                continue
            rel = f.relative_to(base)
            kws = _extract_keywords(content)
            total_keywords.update(kws)
            if kws:
                print(f"=== {rel} ===")
                print(f"  {', '.join(kws[:30])}")
                print()

    print(f"--- 全キーワード数: {len(total_keywords)} ---")


# ─── list ───────────────────────────────────────

def cmd_list(directory: str):
    """ファイル一覧を表示する。JSONはページ数も表示。"""
    files = find_files(directory)
    if not files:
        print("対応ファイルが見つかりません。")
        return

    json_files = [f for f in files if f.suffix == ".json"]
    md_files = [f for f in files if f.suffix == ".md"]
    csv_files = [f for f in files if f.suffix == ".csv"]
    txt_files = [f for f in files if f.suffix == ".txt"]

    base = Path(directory)

    if json_files:
        print(f"=== JSON ファイル ({len(json_files)} 件) ===\n")
        for f in json_files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                page_count = len(data) if isinstance(data, list) else 0
                rel = f.relative_to(base)
                print(f"  {rel}  ({page_count} ページ)")
            except Exception as e:
                print(f"  {f.name}  (読み込みエラー: {e})")
        print()

    if md_files:
        print(f"=== Markdown ファイル ({len(md_files)} 件) ===\n")
        for f in md_files:
            rel = f.relative_to(base)
            size = f.stat().st_size
            print(f"  {rel}  ({size:,} bytes)")
        print()

    if csv_files:
        print(f"=== CSV ファイル ({len(csv_files)} 件) ===\n")
        for f in csv_files:
            rel = f.relative_to(base)
            print(f"  {rel}")
        print()

    if txt_files:
        print(f"=== テキストファイル ({len(txt_files)} 件) ===\n")
        for f in txt_files:
            rel = f.relative_to(base)
            print(f"  {rel}")
        print()

    total = len(files)
    print(f"合計: {total} ファイル (JSON: {len(json_files)}, MD: {len(md_files)}, CSV: {len(csv_files)}, TXT: {len(txt_files)})")


# ─── search ─────────────────────────────────────

def _search_json_file(f: Path, terms: list[str]) -> list[dict]:
    """JSON ファイル内を検索する。"""
    results = []
    try:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return results

    if not isinstance(data, list):
        return results

    for entry in data:
        summary = entry.get("summary", "").lower()
        content = entry.get("content", "").lower()
        text = summary + " " + content

        if all(term in text for term in terms):
            hit_in_summary = all(term in summary for term in terms)
            results.append({
                "file": str(f),
                "type": "json",
                "page": entry.get("page", "?"),
                "summary": entry.get("summary", ""),
                "hit_in_summary": hit_in_summary,
            })
    return results


def _search_text_file(f: Path, terms: list[str]) -> list[dict]:
    """テキストファイル（md/csv/txt）内を検索する。"""
    results = []
    try:
        with open(f, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception:
        return results

    if all(term in content.lower() for term in terms):
        # 最初にヒットした行の前後を抜粋
        lines = content.split("\n")
        snippet = ""
        for i, line in enumerate(lines):
            if any(term in line.lower() for term in terms):
                start = max(0, i - 1)
                end = min(len(lines), i + 3)
                snippet = "\n".join(lines[start:end])
                break

        results.append({
            "file": str(f),
            "type": f.suffix.lstrip("."),
            "page": "-",
            "summary": snippet[:200] if snippet else content[:200],
            "hit_in_summary": True,
        })
    return results


def cmd_search(keywords: str, directory: str):
    """全ファイルからキーワード検索する。"""
    files = find_files(directory)
    if not files:
        print("対応ファイルが見つかりません。")
        return

    terms = keywords.lower().split()
    results = []

    for f in files:
        if f.suffix == ".json":
            results.extend(_search_json_file(f, terms))
        else:
            results.extend(_search_text_file(f, terms))

    if not results:
        print(f"「{keywords}」に一致するファイルが見つかりませんでした。")
        return

    # JSON の summary ヒットを優先
    results.sort(key=lambda r: (
        r["type"] != "json",
        not r.get("hit_in_summary", False),
        r["file"],
        str(r["page"]),
    ))

    print(f"「{keywords}」の検索結果: {len(results)} 件\n")
    for r in results:
        loc = "summary" if r.get("hit_in_summary") else "content"
        if r["type"] == "json":
            print(f"  [{r['type']}:{loc}] {r['file']} - Page {r['page']}")
        else:
            print(f"  [{r['type']}] {r['file']}")
        print(f"    抜粋: {r['summary'][:200]}")
        print()


# ─── get_page ───────────────────────────────────

def cmd_get_page(json_file: str, page_num: int, directory: str):
    """指定した JSON ファイルの指定ページの全文 (content) を出力する。"""
    target = Path(json_file)
    if not target.is_absolute():
        candidates = list(Path(directory).rglob(json_file))
        if not candidates:
            print(f"ファイル '{json_file}' が見つかりません。")
            return
        target = candidates[0]

    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"ファイル読み込みエラー: {e}")
        return

    if not isinstance(data, list):
        print("不正な JSON 形式です。")
        return

    for entry in data:
        if entry.get("page") == page_num:
            print(f"=== {target.name} - Page {page_num} ===\n")
            print(f"Summary: {entry.get('summary', '')}\n")
            print(f"--- Content ---\n")
            print(entry.get("content", "(空)"))
            return

    print(f"Page {page_num} が '{target.name}' に見つかりません。")
    print(f"利用可能なページ: {[e.get('page') for e in data]}")


# ─── summaries ──────────────────────────────────

def cmd_summaries(json_file: str, directory: str):
    """指定した JSON ファイルの全ページのサマリー一覧を表示する。"""
    target = Path(json_file)
    if not target.is_absolute():
        candidates = list(Path(directory).rglob(json_file))
        if not candidates:
            print(f"ファイル '{json_file}' が見つかりません。")
            return
        target = candidates[0]

    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"ファイル読み込みエラー: {e}")
        return

    if not isinstance(data, list):
        print("不正な JSON 形式です。")
        return

    print(f"=== {target.name} 全ページサマリー ({len(data)} ページ) ===\n")
    for entry in data:
        page = entry.get("page", "?")
        summary = entry.get("summary", "(要約なし)")
        print(f"  Page {page}: {summary}")
    print()


# ─── read_file ──────────────────────────────────

def cmd_read_file(file_path: str, directory: str):
    """テキストファイル（md/csv/txt）の内容を表示する。"""
    target = Path(file_path)
    if not target.is_absolute():
        candidates = list(Path(directory).rglob(file_path))
        if not candidates:
            # ファイル名だけでも検索
            name_only = Path(file_path).name
            candidates = list(Path(directory).rglob(name_only))
        if not candidates:
            print(f"ファイル '{file_path}' が見つかりません。")
            return
        target = candidates[0]

    try:
        with open(target, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception as e:
        print(f"ファイル読み込みエラー: {e}")
        return

    print(f"=== {target} ===\n")
    print(content)


# ─── main ───────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="database/ 横断検索ツール")
    parser.add_argument("command", choices=["list", "search", "get_page", "summaries", "read_file", "keywords"],
                        help="実行するコマンド")
    parser.add_argument("args", nargs="*", help="コマンド引数")
    parser.add_argument("--dir", default="database",
                        help="検索対象ディレクトリ (default: database)")

    args = parser.parse_args()
    directory = args.dir

    if args.command == "list":
        cmd_list(directory)
    elif args.command == "search":
        if not args.args:
            print("検索キーワードを指定してください。")
            sys.exit(1)
        cmd_search(" ".join(args.args), directory)
    elif args.command == "get_page":
        if len(args.args) < 2:
            print("Usage: get_page <json_file> <page_number>")
            sys.exit(1)
        cmd_get_page(args.args[0], int(args.args[1]), directory)
    elif args.command == "summaries":
        if not args.args:
            print("JSON ファイル名を指定してください。")
            sys.exit(1)
        cmd_summaries(args.args[0], directory)
    elif args.command == "read_file":
        if not args.args:
            print("ファイルパスを指定してください。")
            sys.exit(1)
        cmd_read_file(args.args[0], directory)
    elif args.command == "keywords":
        cmd_keywords(directory)


if __name__ == "__main__":
    main()
