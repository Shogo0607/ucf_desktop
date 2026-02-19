#!/usr/bin/env python3
"""スキルのディレクトリ構造を初期化するスクリプト。

Usage:
    python3 init_skill.py <skill-name> --path <output-directory>
    python3 init_skill.py <skill-name>  # デフォルトは ./skills/

Examples:
    python3 init_skill.py deploy-helper --path skills/
    python3 init_skill.py code-review --path ~/.ucf_desktop/skills/
"""

import argparse
import sys
from pathlib import Path


def sanitize_name(name: str) -> str:
    """スキル名をディレクトリ名として安全な形式に変換する。"""
    return "".join(c for c in name if c.isalnum() or c in "-_").strip("-_")


def init_skill(name: str, base_path: str) -> None:
    safe_name = sanitize_name(name)
    if not safe_name:
        print(f"[error] 無効なスキル名: {name}", file=sys.stderr)
        sys.exit(1)

    base = Path(base_path)
    skill_dir = base / safe_name

    if skill_dir.exists():
        print(f"[error] ディレクトリが既に存在します: {skill_dir}", file=sys.stderr)
        sys.exit(1)

    # ディレクトリ作成
    skill_dir.mkdir(parents=True)
    (skill_dir / "scripts").mkdir()

    # SKILL.md テンプレート生成
    skill_md = f"""---
name: {safe_name}
description: TODO: このスキルがいつトリガーされるべきかを記述する
---

# {safe_name}

TODO: エージェントへの指示をここに記述する。
"""
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    print(f"[ok] スキルを初期化しました: {skill_dir}")
    print(f"  - {skill_dir}/SKILL.md")
    print(f"  - {skill_dir}/scripts/")
    print()
    print("次のステップ:")
    print(f"  1. {skill_dir}/SKILL.md の description を編集")
    print(f"  2. {skill_dir}/SKILL.md の本文に指示を記述")
    print(f"  3. 必要に応じて scripts/ にスクリプトを追加")


def main():
    parser = argparse.ArgumentParser(description="スキルのディレクトリ構造を初期化する")
    parser.add_argument("name", help="スキル名 (kebab-case)")
    parser.add_argument("--path", default="skills/", help="出力先ディレクトリ (デフォルト: skills/)")
    args = parser.parse_args()
    init_skill(args.name, args.path)


if __name__ == "__main__":
    main()
