#!/usr/bin/env python3
"""
xlsb ファイルを読み込み、内容を表示するツール。
デフォルトではヘッダーは9行目・B列から開始し、9〜11行目の3行で
マルチ行ヘッダー（結合セル対応）を構成する前提。
--header-row / --header-rows / --start-col で変更可能。

Usage:
    # シート一覧を表示
    uv run python skills/P1/scripts/read_xlsb.py sheets <xlsb_file>

    # シートの内容を表示（デフォルト: 最初のシート）
    uv run python skills/P1/scripts/read_xlsb.py read <xlsb_file> [--sheet SHEET] [--limit LIMIT]

    # ヘッダー一覧を表示
    uv run python skills/P1/scripts/read_xlsb.py headers <xlsb_file> [--sheet SHEET]

    # キーワード検索
    uv run python skills/P1/scripts/read_xlsb.py search <xlsb_file> <keyword> [--sheet SHEET]

    # 統計情報を表示
    uv run python skills/P1/scripts/read_xlsb.py info <xlsb_file> [--sheet SHEET]

    # ヘッダー位置を変更（例: 1行目A列から、ヘッダー1行のみ）
    uv run python skills/P1/scripts/read_xlsb.py read <xlsb_file> --header-row 1 --header-rows 1 --start-col A
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from pyxlsb import open_workbook


# デフォルトのヘッダー開始位置（9行目 = index 8, B列 = index 1）
DEFAULT_HEADER_ROW = 8
DEFAULT_HEADER_ROWS = 3  # 9〜11行目の3行でヘッダーを構成
DEFAULT_START_COL = 1


def _col_letter_to_index(col: str) -> int:
    """列文字（A, B, C, ...）を 0-indexed の数値に変換する。"""
    col = col.upper()
    result = 0
    for c in col:
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


def _build_merged_headers(header_rows_data: list[list], num_cols: int) -> list[str]:
    """マルチ行ヘッダーを結合セル対応で1行のヘッダーに統合する。

    結合セル処理:
    1. 各行を横方向に前方埋め（水平結合セル対応）
    2. 各列を縦方向に前方埋め（垂直結合セル対応）
    3. 各列の値を重複排除して " | " で結合
    """
    n_rows = len(header_rows_data)

    # 各行の長さを num_cols に揃える
    grid = []
    for row in header_rows_data:
        padded = row[:num_cols] if len(row) >= num_cols else row + [None] * (num_cols - len(row))
        grid.append(padded)

    # 1. 横方向の前方埋め（水平結合セル対応）
    for r in range(n_rows):
        for c in range(1, num_cols):
            if grid[r][c] is None and grid[r][c - 1] is not None:
                grid[r][c] = grid[r][c - 1]

    # 2. 縦方向の前方埋め（垂直結合セル対応）
    for c in range(num_cols):
        for r in range(1, n_rows):
            if grid[r][c] is None and grid[r - 1][c] is not None:
                grid[r][c] = grid[r - 1][c]

    # 3. 各列で行の値を重複排除して結合
    headers = []
    for c in range(num_cols):
        parts = []
        for r in range(n_rows):
            val = grid[r][c]
            text = str(val).strip() if val is not None else ""
            if text and text not in parts:
                parts.append(text)
        headers.append(" | ".join(parts) if parts else "")

    # 重複ヘッダー名を回避
    final = []
    seen = {}
    for name in headers:
        if name in seen:
            seen[name] += 1
            final.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            final.append(name)

    return final


def _read_sheet(
    xlsb_path: str,
    sheet: str | None = None,
    header_row: int = DEFAULT_HEADER_ROW,
    header_rows: int = DEFAULT_HEADER_ROWS,
    start_col: int = DEFAULT_START_COL,
) -> pd.DataFrame:
    """xlsb ファイルからシートを DataFrame として読み込む。

    マルチ行ヘッダー（結合セル）に対応。
    header_row から header_rows 行分をヘッダーとして読み込み、
    結合セルを前方埋めで補完して1行のヘッダーに統合する。
    """
    path = Path(xlsb_path)
    if not path.exists():
        print(f"エラー: ファイル '{xlsb_path}' が見つかりません。")
        sys.exit(1)

    rows = []
    with open_workbook(str(path)) as wb:
        sheet_name = sheet if sheet else wb.sheets[0]
        with wb.get_sheet(sheet_name) as ws:
            for row in ws.rows():
                rows.append([cell.v for cell in row])

    header_end = header_row + header_rows
    if len(rows) <= header_row:
        print(f"エラー: データが不十分です（{len(rows)}行しかありません、ヘッダー行: {header_row + 1}）。")
        sys.exit(1)

    # ヘッダー行を取得（指定列以降、複数行）
    header_rows_data = [row[start_col:] for row in rows[header_row:header_end]]

    # 最大列数を決定
    num_cols = max(len(r) for r in header_rows_data) if header_rows_data else 0
    if num_cols == 0:
        print("エラー: ヘッダー行にデータがありません。")
        sys.exit(1)

    # マルチ行ヘッダーを統合
    headers = _build_merged_headers(header_rows_data, num_cols)

    # データ行（ヘッダー群の次の行から）
    data_rows = []
    for row in rows[header_end:]:
        row_data = row[start_col:]
        # 行の長さをヘッダーに合わせる
        if len(row_data) < len(headers):
            row_data.extend([None] * (len(headers) - len(row_data)))
        elif len(row_data) > len(headers):
            row_data = row_data[:len(headers)]
        data_rows.append(row_data)

    df = pd.DataFrame(data_rows, columns=headers)

    # 完全に空の行を除外
    df = df.dropna(how="all")

    return df


def cmd_sheets(xlsb_path: str):
    """シート一覧を表示する。"""
    path = Path(xlsb_path)
    if not path.exists():
        print(f"エラー: ファイル '{xlsb_path}' が見つかりません。")
        sys.exit(1)

    with open_workbook(str(path)) as wb:
        print(f"=== シート一覧: {path.name} ===\n")
        for i, name in enumerate(wb.sheets, 1):
            print(f"  {i}. {name}")
        print(f"\n合計: {len(wb.sheets)} シート")


def cmd_headers(xlsb_path: str, sheet: str | None = None, header_row: int = DEFAULT_HEADER_ROW, header_rows: int = DEFAULT_HEADER_ROWS, start_col: int = DEFAULT_START_COL):
    """ヘッダー一覧を表示する。"""
    df = _read_sheet(xlsb_path, sheet, header_row, header_rows, start_col)
    row_start = header_row + 1
    row_end = header_row + header_rows
    col_letter = chr(ord("A") + start_col)
    print(f"=== ヘッダー一覧（{row_start}〜{row_end}行目, {col_letter}列〜） ===\n")
    for i, col in enumerate(df.columns, 1):
        non_null = df[col].notna().sum()
        print(f"  {i:3d}. {col}  ({non_null} 件のデータ)")
    print(f"\n合計: {len(df.columns)} 列, {len(df)} 行")


def cmd_read(xlsb_path: str, sheet: str | None = None, limit: int = 50, header_row: int = DEFAULT_HEADER_ROW, header_rows: int = DEFAULT_HEADER_ROWS, start_col: int = DEFAULT_START_COL):
    """シートの内容を表示する。"""
    df = _read_sheet(xlsb_path, sheet, header_row, header_rows, start_col)

    total = len(df)
    display_df = df.head(limit)

    print(f"=== データ内容（{total} 行中 先頭 {min(limit, total)} 行） ===\n")

    # 各列の最大幅を計算（表示用）
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 200)
    print(display_df.to_string(index=False))

    if total > limit:
        print(f"\n... 残り {total - limit} 行（--limit で表示数を変更可能）")


def cmd_search(xlsb_path: str, keyword: str, sheet: str | None = None, header_row: int = DEFAULT_HEADER_ROW, header_rows: int = DEFAULT_HEADER_ROWS, start_col: int = DEFAULT_START_COL):
    """キーワードでデータを検索する。"""
    df = _read_sheet(xlsb_path, sheet, header_row, header_rows, start_col)

    keyword_lower = keyword.lower()
    mask = df.apply(
        lambda row: row.astype(str).str.lower().str.contains(keyword_lower, na=False).any(),
        axis=1,
    )
    results = df[mask]

    if results.empty:
        print(f"「{keyword}」に一致するデータが見つかりませんでした。")
        return

    print(f"=== 「{keyword}」の検索結果: {len(results)} 件 ===\n")
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 40)
    pd.set_option("display.width", 200)
    print(results.to_string(index=False))


def cmd_info(xlsb_path: str, sheet: str | None = None, header_row: int = DEFAULT_HEADER_ROW, header_rows: int = DEFAULT_HEADER_ROWS, start_col: int = DEFAULT_START_COL):
    """データの統計情報を表示する。"""
    df = _read_sheet(xlsb_path, sheet, header_row, header_rows, start_col)

    print(f"=== データ情報 ===\n")
    print(f"  行数: {len(df)}")
    print(f"  列数: {len(df.columns)}")
    print(f"\n--- 列ごとの情報 ---\n")

    for col in df.columns:
        non_null = df[col].notna().sum()
        dtype = df[col].dtype
        unique = df[col].nunique()
        print(f"  {col}")
        print(f"    型: {dtype}, 非空: {non_null}, ユニーク値: {unique}")

        # 数値列の場合は基本統計
        if pd.api.types.is_numeric_dtype(df[col]) and non_null > 0:
            print(f"    最小: {df[col].min()}, 最大: {df[col].max()}, 平均: {df[col].mean():.2f}")
        # 文字列列の場合はサンプル
        elif non_null > 0:
            samples = df[col].dropna().head(3).tolist()
            sample_str = ", ".join(str(s)[:30] for s in samples)
            print(f"    サンプル: {sample_str}")
        print()


def main():
    parser = argparse.ArgumentParser(description="xlsb ファイル読み込みツール")
    parser.add_argument(
        "command",
        choices=["sheets", "read", "headers", "search", "info"],
        help="実行するコマンド",
    )
    parser.add_argument("xlsb_file", help="xlsb ファイルのパス")
    parser.add_argument("keyword", nargs="?", help="検索キーワード（search コマンド用）")
    parser.add_argument("--sheet", default=None, help="シート名（省略時は最初のシート）")
    parser.add_argument("--limit", type=int, default=50, help="表示行数（read コマンド用、デフォルト: 50）")
    parser.add_argument(
        "--header-row", type=int, default=9,
        help="ヘッダー開始行番号（1-indexed、デフォルト: 9）",
    )
    parser.add_argument(
        "--header-rows", type=int, default=3,
        help="ヘッダーを構成する行数（デフォルト: 3、つまり9〜11行目）",
    )
    parser.add_argument(
        "--start-col", default="B",
        help="開始列（A, B, C, ...、デフォルト: B）",
    )

    args = parser.parse_args()

    # 1-indexed → 0-indexed
    header_row = args.header_row - 1
    header_rows = args.header_rows
    start_col = _col_letter_to_index(args.start_col)

    if args.command == "sheets":
        cmd_sheets(args.xlsb_file)
    elif args.command == "headers":
        cmd_headers(args.xlsb_file, args.sheet, header_row, header_rows, start_col)
    elif args.command == "read":
        cmd_read(args.xlsb_file, args.sheet, args.limit, header_row, header_rows, start_col)
    elif args.command == "search":
        if not args.keyword:
            print("検索キーワードを指定してください。")
            sys.exit(1)
        cmd_search(args.xlsb_file, args.keyword, args.sheet, header_row, header_rows, start_col)
    elif args.command == "info":
        cmd_info(args.xlsb_file, args.sheet, header_row, header_rows, start_col)


if __name__ == "__main__":
    main()
