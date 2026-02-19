# codex_modoki

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
  codex_modoki - ローカルファイル操作エージェント
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
| `~/.codex_modoki/skills/<name>/SKILL.md` | グローバル (どのプロジェクトでも使える) |
| `./skills/<name>/SKILL.md` | プロジェクトローカル (このプロジェクト専用) |

プロジェクトローカルのスキルが同名のグローバルスキルより優先されます。

### スキルの作り方

`skills/` ディレクトリにサブディレクトリを作り、`SKILL.md` を置きます。

```
skills/
  my-task/
    SKILL.md
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
| `description` | いいえ | スキルの説明。LLM がいつこのスキルを使うべきか判断する材料になる |

### スキルの実行方法

3つの方法があります。

**1. LLM が自動で呼ぶ**

スキルの `description` を見て、LLM が適切なタイミングで自動的に `run_skill` ツールを使います。

```
> コミットメッセージを作って
  ⚡ run_skill({"name": "commit-message"})    ← LLM が自動判断
```

**2. スラッシュコマンドで直接実行 (CLI)**

```
> /skill commit-message
> /skill code-review 認証周りを重点的に見て
```

**3. サイドバーからクリック (GUI)**

GUI のサイドバーにスキル一覧が表示されます。クリックするとそのスキルが実行されます。
↻ ボタンでスキルの再読み込みができます。

### 同梱サンプルスキル

| スキル名 | 説明 |
|---|---|
| `commit-message` | git diff からコミットメッセージを自動生成 |
| `code-review` | git diff に対してコードレビューを実行 |

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

「確認あり」のツールは実行前にユーザーの承認を求めます。
`/autoconfirm` で自動承認に切り替えられます。

---

## 設定

設定ファイルは `~/.codex_modoki/config.json` に保存されます。

| キー | デフォルト | 説明 |
|---|---|---|
| `model` | `gpt-4.1-mini` | 使用する LLM モデル |
| `timeout` | `30` | シェルコマンドのタイムアウト (秒) |
| `auto_confirm` | `false` | 破壊的操作の自動承認 |
| `max_context_messages` | `200` | 会話履歴の最大メッセージ数 |
| `compact_keep_recent` | `10` | 圧縮時に保持する直近メッセージ数 |
| `auto_context` | `true` | 起動時にプロジェクト構造を自動収集 |
| `auto_context_max_files` | `50` | 自動収集するファイル数の上限 |

CLI で変更:

```
> /config model gpt-4.1
> /config timeout 60
> /config save           # ファイルに保存
```

---

## プロジェクト構成

```
codex_modoki/
├── agent.py                 # Python バックエンド (エージェント本体)
├── pyproject.toml           # Python プロジェクト設定
├── .env                     # API キー (自分で作成, git 管理外)
├── skills/                  # プロジェクトローカルスキル
│   ├── commit-message/
│   │   └── SKILL.md
│   └── code-review/
│       └── SKILL.md
└── desktop/                 # Electron デスクトップアプリ
    ├── main.js              # メインプロセス
    ├── preload.js           # IPC ブリッジ
    ├── package.json
    └── renderer/
        ├── index.html
        ├── renderer.js
        └── styles.css
```

---

## アーキテクチャ

```
┌─────────────────────┐
│   Electron GUI      │  renderer.js (HTML/CSS/JS)
│   または CLI ターミナル │
└──────────┬──────────┘
           │ JSON Lines (stdin/stdout)
┌──────────▼──────────┐
│   agent.py          │  Python バックエンド
│   ├── chat()        │  ストリーミング会話ループ
│   ├── TOOLS[]       │  OpenAI function calling
│   ├── SkillRegistry │  スキル管理
│   └── SlashCommands │  ユーザーコマンド
└──────────┬──────────┘
           │ HTTPS (streaming)
┌──────────▼──────────┐
│   OpenAI API        │  gpt-4.1-mini (デフォルト)
│   (互換 API 対応)     │
└─────────────────────┘
```

---

## ライセンス

MIT
