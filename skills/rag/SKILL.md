---
name: rag
description: ユーザーが「データベースから調べて」「ドキュメントを検索して回答して」「RAGで質問」「ファイルから情報を探して」「database内の情報で回答して」「冷蔵庫を比較して」「PDFの内容を教えて」のようにdatabase/内の情報を使った調査・回答を求めたときに起動する。
---

# RAG Agent — ReAct 方式の自律探索

このスキルは **ReAct (Reasoning + Acting)** パターンで動作する。
database/ 内の **全ファイル**（JSON, Markdown, CSV, テキスト）を横断検索し、
ユーザーの質問に対して正確で詳細な回答を生成する。

## 対応ファイル形式

| 形式 | 説明 |
|---|---|
| `.json` | PDF から生成されたページデータ `[{page, summary, content, metadata}, ...]` |
| `_embeddings.json` | セマンティック検索用の埋め込みベクトル |
| `.md` | Markdown ドキュメント（旧形式 or 手動作成） |
| `.csv` | CSV データ（想定質問リスト等） |
| `.txt` | テキストファイル |

## 基本ルール

- 毎回のアクションの前に必ず `think` ツールで思考を記録する
- database/ 外のファイルは参照しない（ただし RAG追加フォルダが指定されている場合はそのフォルダも対象とする）
- ファイルに書かれていない情報は捏造しない
- **JSON の場合は content（全文）を取得してから回答する** — summary だけで回答しない
- **md/csv/txt の場合は read_file で全文を取得してから回答する**

## 複数フォルダ対応

ユーザーのメッセージに `[RAG追加フォルダ指定]` が含まれている場合、
指定された各フォルダも database/ と同様に検索対象として扱う。

- `--dir` オプションに各フォルダのパスを指定して search_json.py を実行する
- database/ に加えて追加フォルダそれぞれに対してもコマンドを実行する
- 例: 追加フォルダが `/Users/user/docs` の場合:
  ```
  uv run python {scripts}/search_json.py hybrid "質問文" --dir database
  uv run python {scripts}/search_json.py hybrid "質問文" --dir /Users/user/docs
  ```
- 出典カードにはフォルダパスを含めて表示する

## ReAct ループ

以下のループを **情報が十分に揃うまで繰り返す**（最大10回）。

### 1. Think（思考）

`think` ツールで現在の状況と次のアクションを宣言する:

```
think: "質問「冷蔵庫の温度設定方法」→ まずハイブリッド検索で関連ページを探す"
```

### 2. Act（行動）

思考に基づいてツールを実行する:

| 目的 | 使うツール |
|---|---|
| **ハイブリッド検索（第一選択）** | `run_command: uv run python {scripts}/search_json.py hybrid "質問文" --dir database` |
| **セマンティック検索（抽象的な質問向け）** | `run_command: uv run python {scripts}/search_json.py semantic "質問文" --dir database` |
| 全ファイル一覧の取得（JSON/md/csv/txt） | `run_command: uv run python {scripts}/search_json.py list --dir database` |
| キーワード一覧取得 | `run_command: uv run python {scripts}/search_json.py keywords --dir database` |
| キーワードで横断検索（全形式対応） | `run_command: uv run python {scripts}/search_json.py search "キーワード" --dir database` |
| JSON の全サマリー一覧 | `run_command: uv run python {scripts}/search_json.py summaries "ファイル名.json" --dir database` |
| JSON の特定ページ全文取得 | `run_command: uv run python {scripts}/search_json.py get_page "ファイル名.json" ページ番号 --dir database` |
| md/csv/txt ファイルの全文取得 | `run_command: uv run python {scripts}/search_json.py read_file "パス/ファイル名" --dir database` |
| ディレクトリ構造の把握 | `run_command: uv run python {scripts}/list_tree.py database/` |
| 正規表現で全文検索 | `grep: パターン（path: database/）` |

### 3. Observe（観察）

ツールの結果を見て判断する:

- **JSON で関連ページが見つかった** → `get_page` で全文を取得してからループ継続
- **md/csv/txt で関連ファイルが見つかった** → `read_file` で全文を取得してからループ継続
- **情報が見つからなかった** → 別の検索戦略に切り替え
- **十分な情報が揃った** → ループ終了、回答生成へ

## 検索戦略（重要）

### 1. ハイブリッド検索（推奨・第一選択）

**まずハイブリッド検索を使う。** セマンティック検索とキーワード検索を自動で組み合わせ、
スコア順にランキングされた結果を返す。ユーザーの質問をそのまま検索クエリとして使える。

```
uv run python {scripts}/search_json.py hybrid "冷蔵庫の容量は？" --dir database
```

- セマンティック類似度（60%）+ キーワード一致（40%）でスコアリング
- キーワードが一致しなくても意味的に関連するページがヒットする
- スコアが高い順に結果が返る

### 2. セマンティック検索（自然言語クエリ向け）

ユーザーの質問が抽象的・自然言語的で、正確なキーワードが分からない場合に有効。

```
uv run python {scripts}/search_json.py semantic "食べ物を長持ちさせる方法" --dir database
```

### 3. キーワードインデックス方式（フォールバック）

embeddingファイルがない場合や、exact matchが必要な場合に使用。

1. **キーワードインデックス取得**: `keywords` で全ファイルのキーワード一覧を取得
2. **最適キーワード選定**: ユーザーのクエリとキーワード一覧を照合し、最も関連性の高いキーワードを選ぶ
   - 例: クエリ「容量」→ キーワード一覧から「定格内容積」「容量」「冷蔵室」等を発見 → 「定格内容積」で検索
   - 例: クエリ「電気代」→ キーワード一覧から「消費電力」「年間電力」等を発見 → 「消費電力」で検索
3. **キーワード横断検索**: 選定したキーワードで `search` を実行（スコア付きで結果が返る）
4. **サマリー閲覧**: JSON がヒットしたら `summaries` で全ページ概要を把握
5. **全文取得**: JSON は `get_page`、md/csv/txt は `read_file` で全文を取得
6. **類義語・関連語で再検索**: ヒットしなければ、キーワード一覧から別の候補を選んで `search`
7. **grep フォールバック**: 検索スクリプトで見つからない場合は `grep` で正規表現検索

**1つの戦略で3回失敗したら次の戦略に切り替える。**

## 回答の生成

ループ終了後、**取得した content（全文）に基づいて** 回答する:

- 質問と同じ言語で回答する
- 比較・一覧の質問 → 表形式で整理する
- content に書かれている具体的な数値・手順・詳細を含めて回答する
- 情報が見つからなかった場合 → 「database 内に該当する情報が見つかりませんでした」と伝える

### 出典カード（必須）

回答の **末尾に必ず** 以下の形式で参照元を表示する。
`<!-- sources -->` と `<!-- /sources -->` で囲むと GUI でカード表示になる。

```markdown
<!-- sources -->
- `ファイルパス` — Page X, Y
- `ファイルパス`
<!-- /sources -->
```

出典カードの例:
```markdown
<!-- sources -->
- `database/冷蔵庫/r_h54xg_b.json` — Page 10, 11
- `database/冷蔵庫/r_hws47x_b/操作パネルと機能説明/page_008.md`
<!-- /sources -->
```

## 実行例

### 例1: ハイブリッド検索（推奨）
```
think: "質問は「冷蔵庫の容量」。ハイブリッド検索を試す"
run_command: uv run python {scripts}/search_json.py hybrid "冷蔵庫の容量" --dir database
think: "r_h54xg_b.json の Page 34 がスコア 0.85 でヒット。全文を取得する"
run_command: uv run python {scripts}/search_json.py get_page "r_h54xg_b.json" 34 --dir database
think: "容量の具体的な数値を取得した。回答を生成する"
→ 回答を生成
```

### 例2: ハイブリッド検索 → キーワード補完
```
think: "質問は「冷蔵庫の温度設定方法」。ハイブリッド検索を試す"
run_command: uv run python {scripts}/search_json.py hybrid "冷蔵庫の温度設定方法" --dir database
think: "r_h54xg_b.json の Page 10, 20 にヒット。全文を取得する"
run_command: uv run python {scripts}/search_json.py get_page "r_h54xg_b.json" 10 --dir database
run_command: uv run python {scripts}/search_json.py get_page "r_h54xg_b.json" 20 --dir database
think: "温度設定の具体的な手順を取得した。回答を生成する"
→ 回答を生成
```

### 例3: セマンティック検索（抽象的な質問）
```
think: "質問は「食べ物を長持ちさせるコツ」。抽象的なのでセマンティック検索を使う"
run_command: uv run python {scripts}/search_json.py semantic "食べ物を長持ちさせるコツ" --dir database
think: "保存食品例のPage 9, 野菜室のPage 18 がヒット。全文を取得する"
run_command: uv run python {scripts}/search_json.py get_page "r_h54xg_b.json" 9 --dir database
run_command: uv run python {scripts}/search_json.py get_page "r_h54xg_b.json" 18 --dir database
think: "保存のコツを取得した。回答を生成する"
→ 回答を生成
```

### 例4: キーワードインデックス方式（フォールバック）
```
think: "ハイブリッド検索で十分な結果が得られなかった。キーワードインデックスを使う"
run_command: uv run python {scripts}/search_json.py keywords --dir database
think: "キーワード一覧に「お手入れ」「清掃」がある。「お手入れ」で横断検索する"
run_command: uv run python {scripts}/search_json.py search "お手入れ" --dir database
think: "r_hws47x_b/お手入れと清掃方法/page_023.md がヒット。全文を読む"
run_command: uv run python {scripts}/search_json.py read_file "冷蔵庫/r_hws47x_b/お手入れと清掃方法/page_023.md" --dir database
think: "お手入れの具体的な手順を取得した。回答を生成する"
→ 回答を生成
```
