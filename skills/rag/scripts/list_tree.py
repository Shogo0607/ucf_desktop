#!/usr/bin/env python3
"""
database/ ディレクトリの再帰的ツリー表示。
agent.py の run_command から呼び出して、一発でディレクトリ構造を把握する。

Usage:
    uv run python scripts/list_tree.py [directory] [--max-depth N]

Example:
    uv run python skills/rag/scripts/list_tree.py database/
    uv run python skills/rag/scripts/list_tree.py database/冷蔵庫 --max-depth 3
"""

import os
import sys
import argparse


def build_tree(directory, max_depth=5, current_depth=0):
    """Build tree structure as list of (depth, name, is_dir) tuples."""
    entries = []
    try:
        items = sorted(os.listdir(directory), key=str.lower)
    except (PermissionError, FileNotFoundError):
        return entries

    # Filter hidden files
    items = [item for item in items if not item.startswith('.')]

    for item in items:
        full_path = os.path.join(directory, item)
        is_dir = os.path.isdir(full_path)

        # Skip PDF files
        if not is_dir and item.lower().endswith('.pdf'):
            continue

        entries.append((current_depth, item, is_dir, full_path))

        if is_dir and current_depth < max_depth:
            entries.extend(build_tree(full_path, max_depth, current_depth + 1))

    return entries


def render_tree(entries):
    """Render tree entries with box-drawing characters."""
    if not entries:
        return "(empty)"

    lines = []
    # Group by depth to determine last-child status
    for i, (depth, name, is_dir, full_path) in enumerate(entries):
        # Find if this is the last entry at this depth within its parent
        is_last = True
        for j in range(i + 1, len(entries)):
            if entries[j][0] < depth:
                break
            if entries[j][0] == depth:
                is_last = False
                break

        # Build prefix
        prefix = ""
        for d in range(depth):
            # Check if there are more entries at this ancestor depth
            has_more = False
            for j in range(i + 1, len(entries)):
                if entries[j][0] < d:
                    break
                if entries[j][0] == d:
                    has_more = True
                    break
            prefix += "│   " if has_more else "    "

        connector = "└── " if is_last else "├── "
        suffix = "/" if is_dir else ""
        lines.append(f"{prefix}{connector}{name}{suffix}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Directory tree listing")
    parser.add_argument("directory", nargs="?", default="database",
                        help="Directory to list (default: database)")
    parser.add_argument("--max-depth", type=int, default=5,
                        help="Maximum depth (default: 5)")
    args = parser.parse_args()

    target = args.directory
    if not os.path.exists(target):
        print(f"Error: '{target}' not found.")
        sys.exit(1)

    print(f"{target}/")
    entries = build_tree(target, max_depth=args.max_depth)
    print(render_tree(entries))

    # Summary
    file_count = sum(1 for e in entries if not e[2])
    dir_count = sum(1 for e in entries if e[2])
    print(f"\n({dir_count} directories, {file_count} files)")


if __name__ == "__main__":
    main()
