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

    # セマンティック検索（embedding類似度による検索）
    uv run python skills/rag/scripts/search_json.py semantic "質問文" [--dir database] [--top-k 5]

    # ハイブリッド検索（セマンティック + キーワード検索の統合）
    uv run python skills/rag/scripts/search_json.py hybrid "質問文" [--dir database] [--top-k 5]
"""

import json
import math
import os
import re
import sys
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加（pdf モジュールの参照用）
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(Path(_PROJECT_ROOT) / ".env")

SUPPORTED_EXTENSIONS = {".json", ".md", ".csv", ".txt"}


def _load_embedding_model() -> str:
    """config.json から embedding_model を読み取る。"""
    config_path = Path(_PROJECT_ROOT) / ".ucf_desktop" / "config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("embedding_model", "text-embedding-3-small")
    except Exception:
        return "text-embedding-3-small"


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
            # _embeddings.json は通常のJSON検索から除外
            if f.name.endswith("_embeddings.json"):
                continue
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

                # metadataのkeywordsがあればそれも含める
                metadata = entry.get("metadata", {})
                meta_kws = metadata.get("keywords", [])

                kws = _extract_keywords(summary)
                all_kws = sorted(set(kws) | set(meta_kws))
                total_keywords.update(all_kws)
                if all_kws:
                    print(f"  Page {page}: {', '.join(all_kws)}")
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
                # embeddingの有無を確認
                emb_path = f.parent / f"{f.stem}_embeddings.json"
                emb_marker = " [embedding有]" if emb_path.exists() else ""
                print(f"  {rel}  ({page_count} ページ){emb_marker}")
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


# ─── scoring helpers ─────────────────────────────

def _score_keyword_match(text: str, terms: list[str]) -> float:
    """テキストと検索語のマッチスコアを計算する（0.0-1.0）。

    TF-IDFライクなスコアリング:
    - 出現回数（TF）に対数減衰を適用
    - 文書長の逆数で正規化（短い文書でのヒットを優遇）
    - 部分一致にも半分のスコアを付与
    """
    if not terms:
        return 0.0

    text_lower = text.lower()
    total_score = 0.0

    for term in terms:
        term_lower = term.lower()
        if term_lower in text_lower:
            count = text_lower.count(term_lower)
            tf_score = 1.0 + math.log(count) if count > 0 else 0.0
            doc_len_factor = 1.0 / (1.0 + math.log(1 + len(text_lower) / 500))
            total_score += tf_score * doc_len_factor
        else:
            overlap = _partial_match_score(text_lower, term_lower)
            total_score += overlap * 0.5

    max_possible = len(terms)
    return min(total_score / max_possible, 1.0)


def _partial_match_score(text: str, term: str) -> float:
    """部分一致スコアを計算する（サブストリング検索）。"""
    if len(term) < 2:
        return 0.0

    best = 0.0
    for n in range(len(term), 1, -1):
        for start in range(len(term) - n + 1):
            sub = term[start:start + n]
            if sub in text:
                ratio = n / len(term)
                best = max(best, ratio)
                break
        if best > 0:
            break
    return best


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
            # スコアを計算
            summary_score = _score_keyword_match(entry.get("summary", ""), terms)
            content_score = _score_keyword_match(entry.get("content", ""), terms)

            metadata = entry.get("metadata", {})
            meta_text = " ".join(metadata.get("keywords", []) + metadata.get("topics", []))
            meta_score = _score_keyword_match(meta_text, terms) if meta_text else 0.0

            combined_score = summary_score * 0.4 + content_score * 0.3 + meta_score * 0.3

            hit_in_summary = all(term in summary for term in terms)
            results.append({
                "file": str(f),
                "type": "json",
                "page": entry.get("page", "?"),
                "summary": entry.get("summary", ""),
                "hit_in_summary": hit_in_summary,
                "score": round(combined_score, 4),
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
        score = _score_keyword_match(content, terms)

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
            "score": round(score, 4),
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

    # スコア降順でソート
    results.sort(key=lambda r: -r.get("score", 0))

    print(f"「{keywords}」の検索結果: {len(results)} 件\n")
    for r in results:
        loc = "summary" if r.get("hit_in_summary") else "content"
        score = r.get("score", 0)
        if r["type"] == "json":
            print(f"  [score:{score:.3f} {r['type']}:{loc}] {r['file']} - Page {r['page']}")
        else:
            print(f"  [score:{score:.3f} {r['type']}] {r['file']}")
        print(f"    抜粋: {r['summary'][:200]}")
        print()


# ─── semantic search ─────────────────────────────

def cmd_semantic_search(query: str, directory: str, top_k: int = 5):
    """セマンティック検索（embedding類似度による検索）。"""
    from openai import OpenAI
    from pdf.embeddings import embed_query, semantic_search

    client = OpenAI()
    emb_model = _load_embedding_model()
    query_embedding = embed_query(client, query, model=emb_model)

    base = Path(directory)
    json_files = find_files(directory, {".json"})
    all_results = []

    for f in json_files:
        emb_path = f.parent / f"{f.stem}_embeddings.json"
        if not emb_path.exists():
            continue

        try:
            with open(emb_path, "r", encoding="utf-8") as fh:
                emb_data = json.load(fh)
        except Exception:
            continue

        # サマリーマップを構築
        try:
            with open(f, "r", encoding="utf-8") as fh:
                main_data = json.load(fh)
            summary_map = {p["page"]: p.get("summary", "") for p in main_data}
        except Exception:
            summary_map = {}

        results = semantic_search(query_embedding, emb_data, top_k=top_k)
        for r in results:
            all_results.append({
                "file": str(f),
                "type": "json",
                "page": r["page"],
                "summary": summary_map.get(r["page"], ""),
                "score": round(r["score"], 4),
            })

    all_results.sort(key=lambda x: -x["score"])
    all_results = all_results[:top_k]

    if not all_results:
        print(f"「{query}」に一致するページが見つかりませんでした。")
        print("(embeddingファイルが存在しない可能性があります。uv run python -m pdf.migration --dir database を実行してください)")
        return

    print(f"「{query}」のセマンティック検索結果: {len(all_results)} 件\n")
    for r in all_results:
        print(f"  [score: {r['score']:.4f}] {r['file']} - Page {r['page']}")
        print(f"    抜粋: {r['summary'][:200]}")
        print()


# ─── hybrid search ───────────────────────────────

def cmd_hybrid_search(query: str, directory: str, top_k: int = 5,
                      semantic_weight: float = 0.6, keyword_weight: float = 0.4):
    """ハイブリッド検索（セマンティック + キーワード検索の統合）。"""
    from openai import OpenAI
    from pdf.embeddings import embed_query, cosine_similarity

    client = OpenAI()
    emb_model = _load_embedding_model()

    terms = query.lower().split()
    json_files = find_files(directory, {".json"})

    # 全ページのスコアを集約
    page_scores = {}  # key: (file, page) -> {summary, semantic, keyword}

    # 1. キーワード検索
    for f in json_files:
        keyword_results = _search_json_file(f, terms)
        for r in keyword_results:
            key = (r["file"], r["page"])
            if key not in page_scores:
                page_scores[key] = {"summary": r["summary"], "semantic": 0.0, "keyword": 0.0}
            page_scores[key]["keyword"] = r.get("score", 0.0)

    # 2. セマンティック検索
    query_embedding = embed_query(client, query, model=emb_model)
    for f in json_files:
        emb_path = f.parent / f"{f.stem}_embeddings.json"
        if not emb_path.exists():
            continue

        try:
            with open(emb_path, "r", encoding="utf-8") as fh:
                emb_data = json.load(fh)
        except Exception:
            continue

        try:
            with open(f, "r", encoding="utf-8") as fh:
                main_data = json.load(fh)
            summary_map = {p["page"]: p.get("summary", "") for p in main_data}
        except Exception:
            summary_map = {}

        for page_entry in emb_data.get("pages", []):
            score = cosine_similarity(query_embedding, page_entry["embedding"])
            key = (str(f), page_entry["page"])
            if key not in page_scores:
                page_scores[key] = {
                    "summary": summary_map.get(page_entry["page"], ""),
                    "semantic": 0.0,
                    "keyword": 0.0,
                }
            page_scores[key]["semantic"] = score

    # 3. テキストファイルのキーワード検索も統合
    text_files = [f for f in find_files(directory) if f.suffix != ".json"]
    for f in text_files:
        text_results = _search_text_file(f, terms)
        for r in text_results:
            key = (r["file"], r["page"])
            if key not in page_scores:
                page_scores[key] = {"summary": r["summary"], "semantic": 0.0, "keyword": 0.0}
            page_scores[key]["keyword"] = r.get("score", 0.0)

    # 4. スコア統合
    results = []
    for (file, page), scores in page_scores.items():
        combined = scores["semantic"] * semantic_weight + scores["keyword"] * keyword_weight
        if combined > 0.01:
            results.append({
                "file": file,
                "page": page,
                "summary": scores["summary"],
                "score": round(combined, 4),
                "semantic_score": round(scores["semantic"], 4),
                "keyword_score": round(scores["keyword"], 4),
            })

    results.sort(key=lambda x: -x["score"])
    results = results[:top_k]

    if not results:
        print(f"「{query}」に一致するページが見つかりませんでした。")
        return

    print(f"「{query}」のハイブリッド検索結果: {len(results)} 件\n")
    for r in results:
        print(f"  [score: {r['score']:.4f} (sem:{r['semantic_score']:.3f} kw:{r['keyword_score']:.3f})] {r['file']} - Page {r['page']}")
        print(f"    抜粋: {r['summary'][:200]}")
        print()


# ─── get_page ───────────────────────────────────

def cmd_get_page(json_file: str, page_num: int, directory: str):
    """指定した JSON ファイルの指定ページの全文 (content) を出力する。"""
    target = Path(json_file)
    if not target.is_absolute():
        candidates = list(Path(directory).rglob(json_file))
        candidates = [c for c in candidates if not c.name.endswith("_embeddings.json")]
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

            # メタデータがあれば表示
            metadata = entry.get("metadata", {})
            if metadata:
                topics = metadata.get("topics", [])
                keywords = metadata.get("keywords", [])
                if topics:
                    print(f"Topics: {', '.join(topics)}")
                if keywords:
                    print(f"Keywords: {', '.join(keywords)}")
                print()

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
        candidates = [c for c in candidates if not c.name.endswith("_embeddings.json")]
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
    parser.add_argument("command",
                        choices=["list", "search", "get_page", "summaries",
                                 "read_file", "keywords", "semantic", "hybrid"],
                        help="実行するコマンド")
    parser.add_argument("args", nargs="*", help="コマンド引数")
    parser.add_argument("--dir", default="database",
                        help="検索対象ディレクトリ (default: database)")
    parser.add_argument("--top-k", type=int, default=5,
                        help="返す結果の最大数 (default: 5)")
    parser.add_argument("--semantic-weight", type=float, default=0.6,
                        help="ハイブリッド検索のセマンティック重み (default: 0.6)")
    parser.add_argument("--keyword-weight", type=float, default=0.4,
                        help="ハイブリッド検索のキーワード重み (default: 0.4)")

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
    elif args.command == "semantic":
        if not args.args:
            print("検索クエリを指定してください。")
            sys.exit(1)
        cmd_semantic_search(" ".join(args.args), directory, top_k=args.top_k)
    elif args.command == "hybrid":
        if not args.args:
            print("検索クエリを指定してください。")
            sys.exit(1)
        cmd_hybrid_search(
            " ".join(args.args), directory,
            top_k=args.top_k,
            semantic_weight=args.semantic_weight,
            keyword_weight=args.keyword_weight,
        )


if __name__ == "__main__":
    main()
