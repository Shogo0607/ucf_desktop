#!/usr/bin/env python3
"""
既存の分析済みJSONにメタデータとembeddingを追加するマイグレーションスクリプト。
Vision API の再実行は不要で、既存の content フィールドからLLMでメタデータを抽出する。

Usage:
    # メタデータ + embedding を一括生成
    uv run python -m pdf.migration --dir database

    # メタデータのみ
    uv run python -m pdf.migration --dir database --metadata-only

    # embeddingのみ
    uv run python -m pdf.migration --dir database --embeddings-only
"""

import json
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def migrate_metadata(json_path: Path, client: OpenAI, model: str = "gpt-4.1-mini"):
    """既存JSONにメタデータを追加する（Vision API再実行不要）。"""
    from pdf.document_processor import _markdown_to_metadata

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return

    modified = False
    for entry in data:
        # 既にmetadataがある場合はスキップ
        if "metadata" in entry and entry["metadata"].get("keywords"):
            continue

        content = entry.get("content", "")
        if not content:
            continue

        page = entry.get("page", "?")
        sys.stderr.write(f"  Generating metadata for page {page}...\n")
        sys.stderr.flush()

        try:
            result = _markdown_to_metadata(client, model, content)
            entry["metadata"] = {
                "topics": result.get("topics", []),
                "keywords": result.get("keywords", []),
                "section_header": result.get("section_header", ""),
                "page_type": result.get("page_type", "other"),
            }
            # summaryが空なら更新
            if not entry.get("summary") and result.get("summary"):
                entry["summary"] = result["summary"]
            modified = True
        except Exception as e:
            sys.stderr.write(f"  Error on page {page}: {e}\n")

    if modified:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        sys.stderr.write(f"  Updated {json_path}\n")


def migrate_embeddings(json_path: Path, client: OpenAI):
    """既存JSONからembeddingを生成する。"""
    from pdf.embeddings import generate_embeddings
    from pdf.file_manager import save_embeddings

    emb_path = json_path.parent / f"{json_path.stem}_embeddings.json"
    if emb_path.exists():
        sys.stderr.write(f"  Embeddings already exist: {emb_path}\n")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return

    sys.stderr.write(f"  Generating embeddings for {len(data)} pages...\n")
    sys.stderr.flush()

    try:
        embeddings_data = generate_embeddings(client, data)
        save_embeddings(embeddings_data, emb_path)
        sys.stderr.write(f"  Saved: {emb_path}\n")
    except Exception as e:
        sys.stderr.write(f"  Error generating embeddings: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="既存JSONのマイグレーション")
    parser.add_argument("--dir", default="database",
                        help="検索対象ディレクトリ (default: database)")
    parser.add_argument("--metadata-only", action="store_true",
                        help="メタデータ追加のみ実行")
    parser.add_argument("--embeddings-only", action="store_true",
                        help="embedding生成のみ実行")
    parser.add_argument("--model", default="gpt-4.1-mini",
                        help="メタデータ抽出用モデル (default: gpt-4.1-mini)")
    args = parser.parse_args()

    client = OpenAI()
    base = Path(args.dir)
    json_files = sorted(base.rglob("*.json"))
    json_files = [f for f in json_files if not f.name.endswith("_embeddings.json")]

    if not json_files:
        sys.stderr.write(f"No JSON files found in {base}\n")
        return

    sys.stderr.write(f"Found {len(json_files)} JSON file(s) to migrate.\n")

    for jf in json_files:
        sys.stderr.write(f"\nProcessing {jf}...\n")
        if not args.embeddings_only:
            migrate_metadata(jf, client, args.model)
        if not args.metadata_only:
            migrate_embeddings(jf, client)

    sys.stderr.write("\nMigration complete.\n")


if __name__ == "__main__":
    main()
