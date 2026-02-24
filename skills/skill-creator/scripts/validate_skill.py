#!/usr/bin/env python3
"""作成したスキルの構造を検証するスクリプト。

Usage:
    uv run python validate_skill.py <path/to/skill-folder>

Examples:
    uv run python validate_skill.py skills/deploy-helper
"""

import sys
from pathlib import Path


def validate_skill(skill_path: str) -> bool:
    skill_dir = Path(skill_path)
    errors = []
    warnings = []

    # 1. ディレクトリ存在チェック
    if not skill_dir.is_dir():
        print(f"[error] ディレクトリが見つかりません: {skill_dir}")
        return False

    # 2. SKILL.md 存在チェック
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append("SKILL.md が見つかりません")
    else:
        text = skill_md.read_text(encoding="utf-8")

        # 3. frontmatter チェック
        if not text.startswith("---"):
            errors.append("SKILL.md に YAML frontmatter がありません (--- で開始する必要があります)")
        else:
            end = text.find("---", 3)
            if end < 0:
                errors.append("SKILL.md の frontmatter が閉じられていません")
            else:
                frontmatter = text[3:end].strip()
                body = text[end + 3:].strip()

                # name チェック
                has_name = False
                has_desc = False
                for line in frontmatter.splitlines():
                    if ":" in line:
                        key = line.split(":")[0].strip()
                        val = line.split(":", 1)[1].strip()
                        if key == "name":
                            has_name = True
                            if not val:
                                errors.append("name が空です")
                            elif "TODO" in val:
                                warnings.append("name に TODO が残っています")
                        elif key == "description":
                            has_desc = True
                            if not val:
                                errors.append("description が空です")
                            elif "TODO" in val:
                                warnings.append("description に TODO が残っています")

                if not has_name:
                    errors.append("frontmatter に name がありません")
                if not has_desc:
                    errors.append("frontmatter に description がありません")

                # body チェック
                if not body:
                    warnings.append("SKILL.md の本文が空です")
                elif "TODO" in body:
                    warnings.append("SKILL.md の本文に TODO が残っています")

                # 行数チェック
                body_lines = len(body.splitlines()) if body else 0
                if body_lines > 500:
                    warnings.append(f"本文が {body_lines} 行あります (推奨: 500行以下)")

    # 4. 禁止ファイルチェック
    forbidden = ["README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md"]
    for f in forbidden:
        if (skill_dir / f).exists():
            warnings.append(f"不要なファイル: {f} (スキルには含めないでください)")

    # 5. scripts/ チェック
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        scripts = list(scripts_dir.iterdir())
        if not scripts:
            warnings.append("scripts/ ディレクトリが空です (不要なら削除してください)")

    # 結果出力
    print(f"スキル検証: {skill_dir}")
    print(f"{'=' * 50}")

    if not errors and not warnings:
        print("[ok] すべてのチェックに合格しました")
        return True

    for e in errors:
        print(f"  [error] {e}")
    for w in warnings:
        print(f"  [warn]  {w}")

    if errors:
        print(f"\n{len(errors)} 個のエラーがあります。修正してください。")
        return False
    else:
        print(f"\n{len(warnings)} 個の警告があります。確認してください。")
        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python validate_skill.py <path/to/skill-folder>")
        sys.exit(1)
    ok = validate_skill(sys.argv[1])
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
