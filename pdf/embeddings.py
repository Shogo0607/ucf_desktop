"""Embedding 生成とセマンティック検索モジュール。

OpenAI text-embedding-3-small を使用してページ単位のベクトルを生成し、
コサイン類似度によるセマンティック検索を提供する。
"""

import math
from typing import List, Dict, Any
from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


def _build_embedding_text(page: dict) -> str:
    """ページデータからembedding用テキストを構築する。

    summary + metadata(topics, keywords, section_header) を連結。
    content全文ではなく要約+メタデータで高精度・低コストを実現。
    """
    parts = []
    summary = page.get("summary", "")
    if summary:
        parts.append(summary)

    metadata = page.get("metadata", {})
    topics = metadata.get("topics", [])
    if topics:
        parts.append(" ".join(topics))
    keywords = metadata.get("keywords", [])
    if keywords:
        parts.append(" ".join(keywords))
    section = metadata.get("section_header", "")
    if section:
        parts.append(section)

    # メタデータがない場合はsummaryのみ（マイグレーション前の互換性）
    if not parts:
        content = page.get("content", "")
        if content:
            parts.append(content[:500])

    return " ".join(parts)


def generate_embeddings(
    client: OpenAI,
    pages_data: List[Dict[str, Any]],
    model: str = EMBEDDING_MODEL,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """全ページのembeddingを一括生成する。

    Returns:
        {
            "model": str,
            "dimensions": int,
            "pages": [{"page": int, "text_embedded": str, "embedding": List[float]}]
        }
    """
    texts = []
    page_numbers = []
    for page in pages_data:
        text = _build_embedding_text(page)
        texts.append(text)
        page_numbers.append(page["page"])

    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        for item in response.data:
            all_embeddings.append(item.embedding)

    pages_output = []
    for idx, page_num in enumerate(page_numbers):
        pages_output.append({
            "page": page_num,
            "text_embedded": texts[idx],
            "embedding": all_embeddings[idx],
        })

    return {
        "model": model,
        "dimensions": len(all_embeddings[0]) if all_embeddings else EMBEDDING_DIMENSIONS,
        "pages": pages_output,
    }


def embed_query(client: OpenAI, query: str, model: str = EMBEDDING_MODEL) -> List[float]:
    """検索クエリのembeddingを生成する。"""
    response = client.embeddings.create(model=model, input=[query])
    return response.data[0].embedding


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """2つのベクトルのコサイン類似度を計算する（Pure Python実装）。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_search(
    query_embedding: List[float],
    embeddings_data: Dict[str, Any],
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """embeddingのコサイン類似度でページを検索する。

    Returns:
        スコア降順の [{page, score, text_embedded}, ...]
    """
    results = []
    for page_entry in embeddings_data.get("pages", []):
        score = cosine_similarity(query_embedding, page_entry["embedding"])
        results.append({
            "page": page_entry["page"],
            "score": score,
            "text_embedded": page_entry.get("text_embedded", ""),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
