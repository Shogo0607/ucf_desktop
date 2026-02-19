# ucf_desktop

Claude Code / OpenAI Codex 風のローカル AI コーディングアシスタント。
自然言語でファイル操作・コマンド実行・コードレビューなどを行えます。

CLI (ターミナル) と GUI (Electron デスクトップアプリ) の両方で動作します。

---

## 必要なもの

| ソフトウェア | バージョン | 用途 |
|---|---|---|
| **Python** | 3.13 以上 | エージェント本体 |
| **uv** | 最新推奨 | Python パッケージ管理 (pip の代替) |
| **Node.js** | 18 以上 | GUI (Electron) を使う場合のみ |
| **OpenAI API キー** | — | LLM の呼び出しに必要 |

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/Shogo0607/ucf_desktop.git
cd ucf_desktop
```

### 2. uv をインストール (未導入の場合)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3. Python 依存パッケージをインストール

```bash
uv sync
```

これで仮想環境 (`.venv`) が作成され、必要なパッケージがすべてインストールされます。

### 4. API キーを設定

プロジェクトルートに `.env` ファイルを作成します。

```bash
cp .env.example .env   # テンプレートがある場合
# または手動で作成
```

`.env` ファイルの中身:

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

OpenAI 互換の別の API を使う場合は、`OPENAI_BASE_URL` も設定してください。

```env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.example.com/v1
```

> **補足**: 環境変数として直接設定しても OK です。
> `.env` ファイルは環境変数が未設定の場合にのみ読み込まれます (既存の環境変数を上書きしません)。

---

## 使い方

### CLI モード (ターミナル)

```bash
uv run python agent.py
```

起動すると対話型プロンプトが表示されます。

```
============================================================
  ucf_desktop - ローカルファイル操作エージェント
  OS: Darwin | CWD: /Users/you/project
  Model: gpt-4.1-mini
  ✓ プロジェクトコンテキスト読み込み済み
  ✓ スキル: 2 個読み込み済み (/skills で一覧)
  /help でコマンド一覧 | quit で終了
============================================================

>
```

自然言語でリクエストを入力するだけです。

```
> このプロジェクトの構造を教えて
> src/main.py のバグを修正して
> テストを実行して結果を教えて
```

### GUI モード (デスクトップアプリ)

```bash
cd desktop
npm install        # 初回のみ
npm start
```

Electron ウィンドウが開き、チャット画面が表示されます。

#### GUI の機能

| 要素 | 説明 |
|---|---|
| **チャットエリア** | ストリーミング応答、ツール実行カード、確認ダイアログを表示 |
| **会話クリア** | 会話履歴を全削除 |
| **自動確認** | 破壊的操作 (ファイル編集、コマンド実行) の自動承認を切り替え |
| **スキル一覧** | サイドバーにスキルを表示。クリックで実行 |
| **スキルのオン/オフ** | 各スキルのトグルスイッチで有効・無効を切り替え。無効にしたスキルは LLM からも見えなくなる |
| **スキル再読み込み** | ↻ ボタンでディスクからスキルを再スキャン |
| **ステータスバー** | 使用中モデル、カレントディレクトリ、接続状態を表示 |

#### 自動会話圧縮

GUI モードでは、会話のトークン数がコンテキストウィンドウの上限 (デフォルト 128,000 tokens) の 80% を超えると、チャット送信前に **自動で会話を圧縮** します。圧縮中はスピナーが表示され、完了後に圧縮前後のトークン数が通知されます。

> 閾値は設定 `context_limit` と `auto_compact_ratio` で調整可能です。

---

## スラッシュコマンド一覧

CLI モードでは `/` で始まるコマンドが使えます。

| コマンド | 説明 |
|---|---|
| `/help` | コマンド一覧を表示 |
| `/clear` | 会話履歴をクリア |
| `/compact` | 会話履歴を要約して圧縮 (トークン節約) |
| `/history` | 会話履歴のサマリーを表示 |
| `/tokens` | 現在のトークン使用量の概算を表示 |
| `/autoconfirm` | 破壊的操作の自動確認モードを切り替え |
| `/model [name]` | 使用モデルを表示・変更 (例: `/model gpt-4.1`) |
| `/config [key] [value]` | 設定の表示・変更 |
| `/image <path> [質問]` | 画像を送信して質問する |
| `/skills` | 利用可能なスキル一覧を表示 |
| `/skills reload` | スキルを再読み込み |
| `/skill <name> [args]` | スキルを直接実行 |

---

## Agent Skills

スキルは **LLM に手順書を渡して複雑なタスクを実行させる仕組み** です。
ディレクトリに `SKILL.md` ファイルを置くだけで、新しい機能を簡単に追加できます。

### スキルの配置場所

| 場所 | 用途 |
|---|---|
| `~/.ucf_desktop/skills/<name>/SKILL.md` | グローバル (どのプロジェクトでも使える) |
| `./skills/<name>/SKILL.md` | プロジェクトローカル (このプロジェクト専用) |

プロジェクトローカルのスキルが同名のグローバルスキルより優先されます。

### スキルの構造

```
skill-name/
├── SKILL.md          (必須) YAML frontmatter + Markdown 指示
├── scripts/          (任意) 実行可能なスクリプト
├── references/       (任意) 参照ドキュメント
└── assets/           (任意) テンプレート・素材
```

`SKILL.md` は YAML フロントマター + マークダウン本文で構成します。

```markdown
---
name: my-task
description: このスキルが何をするかの簡潔な説明
---

# LLM への指示

ここに手順を書きます。LLM はこの指示に従って作業します。

1. まず `run_command` で xxx を実行
2. 結果を分析して ...
3. ユーザーに報告
```

**フロントマターのフィールド:**

| フィールド | 必須 | 説明 |
|---|---|---|
| `name` | はい | スキルの識別名 (英数字とハイフン) |
| `description` | はい | スキルの説明。LLM がいつこのスキルを使うべきか判断する材料になる |

> **重要**: YAML フロントマター (`---` で囲まれたブロック) がない SKILL.md はスキルとして認識されません。

### バンドルリソース (scripts / references / assets)

| ディレクトリ | 用途 | 例 |
|---|---|---|
| `scripts/` | 決定論的に実行するプログラム | `init_skill.py`, `validate.sh` |
| `references/` | LLM が参照するドキュメント | `api-spec.md`, `style-guide.md` |
| `assets/` | テンプレートや素材ファイル | `template.html`, `config.yaml` |

スキル実行時、これらのリソースの存在は自動検出され、LLM のコンテキストに情報が注入されます (Progressive Disclosure)。

### スキルの作り方

**方法 1: 会話で作成 (推奨)**

エージェントに「スキルを作りたい」「新しいスキルを作って」と言うだけで、`skill-creator` スキルが起動し、対話形式でスキルを設計・作成します。

```
> 新しいスキルを作りたい
  ⚡ run_skill({"name": "skill-creator"})
  → 要件のヒアリング → 設計の提案 → ファイル作成 → 検証
```

**方法 2: 手動で作成**

`skills/` ディレクトリにサブディレクトリを作り、YAML フロントマター付きの `SKILL.md` を配置します。必要に応じて `scripts/` などを追加してください。

### スキルの実行方法

**1. LLM が自動で呼ぶ**

ユーザーのリクエストに合致する `description` を持つスキルがあれば、LLM が自動的に `run_skill` ツールを優先的に使います。

```
> Word でサンプル文書を作って
  ⚡ run_skill({"name": "word-skill"})    ← LLM が自動判断
```

**2. スラッシュコマンドで直接実行 (CLI)**

```
> /skill skill-creator
> /skill word-skill テスト文書を作成して
```

**3. サイドバーからクリック (GUI)**

GUI のサイドバーにスキル一覧が表示されます。クリックするとそのスキルが実行されます。
↻ ボタンでスキルの再読み込みができます。

### スキルのオン/オフ (GUI)

GUI サイドバーの各スキルにはトグルスイッチがあります。

- **オフ**にすると、そのスキルはシステムプロンプトから除外され、LLM からは見えなくなります
- サイドバーからのクリック実行もブロックされます
- 設定は `~/.ucf_desktop/config.json` に永続化されます

### スキルの自動検出

`write_file` や `edit_file` で `skills/` ディレクトリ内のファイルを作成・編集すると、スキルレジストリが自動で再スキャンされ、新しいスキルが即座にサイドバーに反映されます。

### 同梱スキル

| スキル名 | 説明 |
|---|---|
| `skill-creator` | 会話を通じた対話的スキル作成。テンプレート生成 (`init_skill.py`) とバリデーション (`validate_skill.py`) のスクリプト付き |
| `word-skill` | Word (docx) ファイルの読み書き。`python-docx` ラッパースクリプト付き |

---

## 組み込みツール

LLM が使えるツールの一覧です。ユーザーが直接呼ぶものではありません。

| ツール | 確認 | 説明 |
|---|---|---|
| `run_command` | あり | シェルコマンドを実行 |
| `read_file` | なし | ファイルの内容を読み込む |
| `write_file` | あり | ファイルを書き込む (全体置換) |
| `edit_file` | あり | ファイルの一部を置換編集 |
| `list_directory` | なし | ディレクトリ内のファイル一覧を取得 |
| `search_files` | なし | glob パターンでファイルを検索 |
| `grep` | なし | 正規表現でファイル内容を検索 |
| `get_file_info` | なし | ファイルのメタ情報を取得 |
| `run_python_sandbox` | なし | Python コードをサンドボックスで安全に実行 |
| `run_skill` | なし | 登録済みスキルを実行 |

- 「確認あり」のツールは実行前にユーザーの承認を求めます
- `/autoconfirm` (CLI) または「自動確認」ボタン (GUI) で自動承認に切り替え可能
- 安全なツール (read_file, list_directory 等) は並列実行されます (最大 4 ワーカー)

---

## 設定

設定ファイルは `~/.ucf_desktop/config.json` に保存されます。

| キー | デフォルト | 説明 |
|---|---|---|
| `model` | `gpt-4.1-mini` | 使用する LLM モデル |
| `timeout` | `30` | シェルコマンドのタイムアウト (秒) |
| `auto_confirm` | `false` | 破壊的操作の自動承認 |
| `max_context_messages` | `200` | 会話履歴の最大メッセージ数 |
| `compact_keep_recent` | `10` | 圧縮時に保持する直近メッセージ数 |
| `auto_context` | `true` | 起動時にプロジェクト構造を自動収集 |
| `auto_context_max_files` | `50` | 自動収集するファイル数の上限 |
| `context_limit` | `128000` | コンテキストウィンドウの上限トークン数 |
| `auto_compact_ratio` | `0.8` | 自動圧縮を発動するトークン使用率 (0.0〜1.0) |
| `disabled_skills` | `[]` | 無効化されたスキル名のリスト |

CLI で変更:

```
> /config model gpt-4.1
> /config timeout 60
> /config save           # ファイルに保存
```

---

## プロジェクト構成

```
ucf_desktop/
├── agent.py                 # Python バックエンド (エージェント本体)
├── pyproject.toml           # Python プロジェクト設定
├── .env                     # API キー (自分で作成, git 管理外)
├── skills/                  # プロジェクトローカルスキル
│   ├── skill-creator/       # スキル作成ガイド
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── init_skill.py
│   │       └── validate_skill.py
│   └── word-skill/          # Word ファイル操作
│       ├── SKILL.md
│       └── scripts/
│           └── word_skill.py
└── desktop/                 # Electron デスクトップアプリ
    ├── main.js              # メインプロセス (Python 子プロセス管理)
    ├── preload.js           # IPC ブリッジ (セキュアな通信層)
    ├── package.json
    └── renderer/
        ├── index.html       # UI レイアウト
        ├── renderer.js      # メッセージハンドリング・UI ロジック
        └── styles.css       # ダークテーマ UI スタイル
```

---

## アーキテクチャ

```
┌─────────────────────────────┐
│   Electron GUI              │  renderer.js (HTML/CSS/JS)
│   ├── チャット (ストリーミング) │
│   ├── ツール実行カード         │
│   ├── 確認ダイアログ           │
│   ├── スキル一覧 + トグル      │
│   └── 自動圧縮スピナー         │
│   または CLI ターミナル         │
└──────────┬──────────────────┘
           │ JSON Lines (stdin/stdout)
┌──────────▼──────────────────┐
│   agent.py                  │  Python バックエンド
│   ├── chat()                │  ストリーミング会話ループ
│   ├── TOOLS[]               │  OpenAI function calling (並列実行)
│   ├── SkillRegistry         │  スキル管理 (自動スキャン)
│   ├── SlashCommands         │  ユーザーコマンド
│   └── AutoCompact           │  コンテキスト自動圧縮
└──────────┬──────────────────┘
           │ HTTPS (streaming)
┌──────────▼──────────────────┐
│   OpenAI API                │  gpt-4.1-mini (デフォルト)
│   (互換 API 対応)             │
└─────────────────────────────┘
```

### IPC メッセージプロトコル

Electron ↔ Python 間は JSON Lines で通信します。

**Renderer → Python:**

| type | 説明 |
|---|---|
| `user_message` | ユーザーの入力テキスト |
| `confirm_response` | 確認ダイアログへの応答 (承認/拒否) |
| `command` | GUI コマンド (clear, autoconfirm, toggle_skill, run_skill 等) |

**Python → Renderer:**

| type | 説明 |
|---|---|
| `system_info` | 起動時の初期情報 (モデル, CWD, スキル一覧) |
| `token` | ストリーミング応答の断片 |
| `assistant_done` | アシスタントの応答完了 |
| `tool_call` | ツール呼び出しの開始 |
| `tool_result` | ツール実行結果 |
| `confirm_request` | 破壊的操作の確認要求 |
| `skills_list` | スキル一覧の更新 |
| `skill_toggled` | スキルのオン/オフ状態変更 |
| `compacting` | 自動圧縮開始 (スピナー表示) |
| `compact_done` | 自動圧縮完了 (スピナー非表示) |
| `status` | ステータスメッセージ |
| `error` | エラーメッセージ |
| `chat_finished` | チャットスレッド完了 |

---

## 主な依存パッケージ

| パッケージ | 用途 |
|---|---|
| `openai` | OpenAI API クライアント |
| `python-dotenv` | `.env` ファイルの読み込み |
| `openpyxl` | Excel (.xlsx) ファイル操作 |
| `pandas` | データ処理・分析 |
| `python-docx` | Word (.docx) ファイル操作 |
| `pyxlsb` | Excel バイナリ (.xlsb) ファイル操作 |

---

## ライセンス

MIT
