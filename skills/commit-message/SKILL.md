---
name: commit-message
description: Git の変更内容からコミットメッセージを生成する
---

# コミットメッセージ生成

以下の手順でコミットメッセージを生成してください:

1. `run_command` で `git diff --staged` を実行して、ステージング済みの変更を確認
2. ステージング済みの変更がない場合は `git diff` で未ステージの変更を確認
3. 変更内容を分析し、Conventional Commits 形式でコミットメッセージを提案
4. ユーザーに確認を求める

## フォーマット

```
<type>(<scope>): <description>

<body>
```

### type の種類
- `feat`: 新機能
- `fix`: バグ修正
- `refactor`: リファクタリング
- `docs`: ドキュメント
- `style`: コードスタイル
- `test`: テスト
- `chore`: その他

### ルール
- description は日本語で簡潔に（50文字以内）
- body は変更の理由や詳細を記述（任意）
- 複数の変更がある場合は最も重要な変更を type にする
