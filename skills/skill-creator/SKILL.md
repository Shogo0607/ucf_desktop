---
name: skill-creator
description: ユーザーが「スキルを作りたい」「新しいスキルを作成して」「スキルを追加したい」と言ったときに起動する。会話の中で対話的にスキルを設計・作成するスキル。
---

# スキル作成ガイド

ユーザーとの対話を通じて、Agent Skills 仕様に準拠したスキルを作成する。

## SKILL.md のフォーマット（厳守）

SKILL.md は **必ず YAML frontmatter で始まる**。frontmatter がないとスキルとして認識されない。

```
---
name: skill-name
description: トリガー条件の説明
---

（ここから Markdown 本文）
```

**絶対に frontmatter を省略してはならない。** `---` で囲まれた name と description が必須。

## スキルのディレクトリ構造

```
skill-name/
├── SKILL.md          (必須) YAML frontmatter + Markdown 指示
├── scripts/          (任意) 実行可能なスクリプト
├── references/       (任意) 参照ドキュメント
└── assets/           (任意) テンプレート・素材
```

## 作成プロセス

### Step 1: 要件の理解

ユーザーに以下を質問して明確にする:
- **何をするスキルか**: 具体的なユースケースを2-3個挙げてもらう
- **いつトリガーされるべきか**: ユーザーがどんな言葉で呼び出すかを確認
- **スクリプトが必要か**: 繰り返し実行するコマンドや決定論的な処理があるか

質問は一度にまとめて聞くこと。ユーザーの回答で十分な情報が得られるまでこのステップにとどまる。

### Step 2: 設計の提案

収集した情報をもとに、以下を提案する:
- **スキル名** (kebab-case)
- **description** (トリガー条件の説明)
- **SKILL.md 本文の構成案** (見出しレベルでの概要)
- **scripts/ に入れるファイル** (必要な場合)
- **references/ に入れるファイル** (必要な場合)

提案をユーザーに確認し、フィードバックを反映する。

### Step 3: ファイルの作成

`scripts/init_skill.py` を使ってスキルディレクトリを初期化する:

```
run_command: uv run python {このスキルの scripts ディレクトリの絶対パス}/init_skill.py <skill-name> --path skills/
```

init_skill.py は正しい frontmatter 付きの SKILL.md テンプレートを自動生成する。
その後、生成された SKILL.md を `edit_file` で以下の順に編集する:

1. description の `TODO:` を実際のトリガー条件に置換
2. 本文の `TODO:` を実際の指示内容に置換

scripts/ が必要な場合は `write_file` で追加ファイルを作成する。

**注意**: `write_file` で SKILL.md を一から書く場合も、必ず `---` で囲んだ frontmatter を先頭に含めること。

### Step 4: 検証

`scripts/validate_skill.py` で構造を検証する:

```
run_command: uv run python {このスキルの scripts ディレクトリの絶対パス}/validate_skill.py skills/<skill-name>
```

エラーが出たら `edit_file` で修正し、再度検証する。
最後に `read_file` で SKILL.md の内容を表示し、ユーザーに最終確認を求める。

## 設計の原則

- **簡潔さ優先**: コンテキストウィンドウは共有リソース。不要な説明は省く
- **命令形で記述**: 「〜してください」ではなく「〜する」で統一
- **Progressive Disclosure**: SKILL.md は概要、詳細は references/ に分離
- **description がトリガー**: description にはスキルの「使い時」を明確に書く。本文には書かない
- **スクリプトの活用**: 決定論的な処理、繰り返す処理は scripts/ に切り出す

## 禁止事項

以下のファイルは作成しない:
- README.md, CHANGELOG.md, INSTALLATION_GUIDE.md
- テスト用ファイル以外の補助ドキュメント
