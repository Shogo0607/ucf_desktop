"""
PDF 処理パイプライン用プロンプトを管理する。
環境変数 or デフォルト値からプロンプトを取得する。
"""

import os

_DEFAULT_PROMPTS = {
    "PDF_EXTRACTION_SYSTEM_PROMPT": (
        "あなたはPDFページの画像をMarkdownに変換する専門家です。\n"
        "画像に含まれるテキスト、表、リストなどを忠実にMarkdown形式で出力してください。\n"
        "レイアウトや構造をできる限り保持し、見出しレベルも適切に設定してください。\n"
        "画像内の図やチャートは [図: 説明] の形式で記述してください。\n"
        "出力はMarkdownのみとし、余計な説明は加えないでください。"
    ),
    "PDF_EXTRACTION_PAGE_INSTRUCTIONS": (
        "このページの内容をMarkdown形式に変換してください。"
    ),
    "SUMMARY_SYSTEM_PROMPT": (
        "あなたはドキュメントの要約を作成する専門家です。\n"
        "与えられたMarkdownテキストを読み、そのページの内容を簡潔に要約してください。\n"
        "出力は必ず以下のJSON形式で返してください:\n"
        '{"summary": "このページの内容の要約（2-3文）"}\n'
        "JSONのみを出力し、余計なテキストは含めないでください。"
    ),
    "METADATA_EXTRACTION_PROMPT": (
        "あなたはドキュメントのメタデータを抽出する専門家です。\n"
        "与えられたMarkdownテキストを読み、以下のJSON形式で情報を抽出してください:\n"
        "{\n"
        '  "summary": "このページの内容の要約（2-3文）",\n'
        '  "topics": ["トピック1", "トピック2", ...],\n'
        '  "keywords": ["キーワード1", "キーワード2", ...],\n'
        '  "section_header": "このページが属するセクション名",\n'
        '  "page_type": "cover|toc|instruction|specification|troubleshooting|maintenance|safety|other"\n'
        "}\n\n"
        "topicsは3-5個の主要トピック、keywordsは5-10個の検索用キーワード"
        "（製品名、技術用語、機能名、数値を含む）を抽出してください。\n"
        "JSONのみを出力し、余計なテキストは含めないでください。"
    ),
}


class PromptLoader:
    def __init__(self):
        self._prompts = dict(_DEFAULT_PROMPTS)

    def get_prompt(self, key: str) -> str:
        env_val = os.environ.get(key)
        if env_val:
            return env_val
        return self._prompts.get(key, "")
