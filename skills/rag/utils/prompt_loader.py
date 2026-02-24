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
}


class PromptLoader:
    def __init__(self):
        self._prompts = dict(_DEFAULT_PROMPTS)

    def get_prompt(self, key: str) -> str:
        env_val = os.environ.get(key)
        if env_val:
            return env_val
        return self._prompts.get(key, "")
