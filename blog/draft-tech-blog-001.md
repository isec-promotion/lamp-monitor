# 制御盤ランプ監視システム開発記 (1) - Cloudflare Workers による通知基盤の構築

## はじめに

制御盤の 12 個のランプ（正常=緑／異常=赤）をカメラで監視し、異常を検出したら Discord Webhook に通知するシステムを開発しています。本記事では、開発の第一段階として「Cloudflare Workers による通知基盤の構築と検証」について詳しく解説します。

カメラやランプ検出ロジックを実装する前に、まず通知システムが正常に動作することを確認することで、後の開発段階でのトラブルシューティングを効率化できます。

## プロジェクト概要

このプロジェクトは四段階の開発アプローチを採用しています：

1. **Cloudflare Workers による通知基盤構築** ← 本記事
2. **疑似ダッシュボードでロジック検証**
3. **Web カメラで実験**
4. **Raspberry Pi 5 への移植**

段階的開発により、各コンポーネントを独立して検証し、統合時の問題を最小化することが狙いです。

## なぜ Cloudflare Workers なのか？

### 技術的メリット

1. **サーバーレス**: インフラ管理が不要
2. **グローバル配信**: エッジロケーションでの高速処理
3. **高可用性**: Cloudflare のインフラによる安定性
4. **コスト効率**: 従量課金で小規模利用時は無料
5. **簡単デプロイ**: Git 連携による自動デプロイ

### セキュリティ面でのメリット

1. **Discord Webhook URL の隠蔽**: 環境変数で管理
2. **HMAC 署名検証**: 不正なリクエストの排除
3. **HTTPS 強制**: 通信の暗号化
4. **レート制限**: DDoS 攻撃への耐性

## アーキテクチャ設計

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   監視システム   │    │ Cloudflare      │    │    Discord      │
│  (Raspberry Pi) │    │   Workers       │    │   Webhook       │
│                 │    │                 │    │                 │
│ ・ランプ検出     │───▶│ ・署名検証      │───▶│ ・通知表示      │
│ ・HMAC署名生成  │    │ ・メッセージ変換│    │ ・チャンネル投稿│
│ ・HTTP POST     │    │ ・Discord転送   │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

この設計により、以下の利点があります：

- **責任分離**: 各コンポーネントが独立した責任を持つ
- **セキュリティ**: Discord Webhook URL が監視システムに露出しない
- **拡張性**: 将来的に複数の通知先に対応可能
- **保守性**: 各コンポーネントを独立してメンテナンス可能

## Cloudflare Workers の実装

### 基本構造

```javascript
export default {
  async fetch(request, env) {
    // POST以外のリクエストは拒否
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // 署名検証とDiscord通知の処理
    // ...
  },
};
```

Cloudflare Workers は ES6 モジュール形式で実装し、`fetch` イベントハンドラーでリクエストを処理します。

### HMAC 署名検証の実装

セキュリティの要となる HMAC 署名検証を詳しく見てみましょう：

```javascript
async function verifySignature(body, signature, secret) {
  // 環境変数が設定されているか確認
  if (typeof secret !== "string" || secret.length === 0) {
    console.log("エラー: 環境変数 'SECRET_KEY' が設定されていません。");
    return false;
  }

  // 署名が 'sha256=...' の形式か確認
  const [algo, sigHex] = signature.split("=");
  if (algo !== "sha256" || !sigHex) {
    return false;
  }

  try {
    const encoder = new TextEncoder();
    const key = await crypto.subtle.importKey(
      "raw",
      encoder.encode(secret),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"]
    );
    const sigBuffer = hexToBuffer(sigHex);
    const data = encoder.encode(body);
    return await crypto.subtle.verify("HMAC", key, sigBuffer, data);
  } catch (e) {
    console.log("署名検証中に内部エラー:", e.message);
    return false;
  }
}
```

**実装のポイント**:

1. **Web Crypto API の使用**: ブラウザ標準の暗号化 API を活用
2. **エラーハンドリング**: 各段階での適切なエラー処理
3. **セキュリティ検証**: 署名形式の厳密なチェック
4. **ログ出力**: デバッグ用の詳細なログ

### 16 進数変換ユーティリティ

HMAC 署名は 16 進数文字列として送信されるため、バイナリデータに変換する必要があります：

```javascript
// 16進数文字列をArrayBufferに変換する関数
function hexToBuffer(hex) {
  const buffer = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    buffer[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return buffer;
}
```

この関数により、文字列形式の署名をバイナリ形式に変換し、`crypto.subtle.verify` で検証できます。

### Discord 通知の実装

署名検証が成功した場合、Discord Webhook に通知を転送します：

```javascript
try {
  const body = JSON.parse(bodyText);
  const message =
    body.message ||
    `ランプ ${body.lamp_id} が ${body.state} 状態になりました！`;
  const payload = { content: message };

  const discordResponse = await fetch(env.DISCORD_WEBHOOK_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!discordResponse.ok) {
    console.log("Discordへの送信に失敗しました:", await discordResponse.text());
    return new Response("Failed to send Discord notification.", {
      status: 500,
    });
  }

  return new Response("Notification sent successfully.", { status: 200 });
} catch (e) {
  console.log("JSONのパースまたは通知処理中にエラー:", e.message);
  return new Response("Bad Request", { status: 400 });
}
```

**実装のポイント**:

1. **柔軟なメッセージ処理**: カスタムメッセージまたはデフォルトメッセージ
2. **エラーハンドリング**: Discord API のエラーレスポンス処理
3. **適切な HTTP ステータス**: クライアントへの明確な応答
4. **ログ出力**: 運用時のトラブルシューティング支援

## 環境変数の設定

Cloudflare Workers では、機密情報を環境変数として管理します：

### 必要な環境変数

1. **SECRET_KEY**: HMAC 署名検証用の共通鍵
2. **DISCORD_WEBHOOK_URL**: Discord Webhook の URL

### 設定方法

```bash
# Wrangler CLI を使用した設定
wrangler secret put SECRET_KEY
wrangler secret put DISCORD_WEBHOOK_URL

# または、Cloudflare Dashboard から設定
# Workers & Pages > 該当のWorker > Settings > Environment Variables
```

### セキュリティ考慮事項

- **SECRET_KEY**: 十分に長く、推測困難な文字列を使用
- **DISCORD_WEBHOOK_URL**: Discord から生成された正式な URL を使用
- **アクセス制御**: 環境変数へのアクセスを最小限に制限

## 検証とテスト

### 1. 基本的な動作確認

```bash
# 正常なリクエストのテスト
curl -X POST https://your-worker.workers.dev \
  -H "Content-Type: application/json" \
  -H "X-Signature-256: sha256=正しい署名" \
  -d '{"lamp_id": 1, "state": "RED", "message": "テスト通知"}'

# 期待される応答: 200 OK "Notification sent successfully."
```

### 2. セキュリティテスト

```bash
# 署名なしのリクエスト
curl -X POST https://your-worker.workers.dev \
  -H "Content-Type: application/json" \
  -d '{"lamp_id": 1, "state": "RED"}'

# 期待される応答: 401 Unauthorized "Unauthorized - Signature Required"

# 無効な署名のリクエスト
curl -X POST https://your-worker.workers.dev \
  -H "Content-Type: application/json" \
  -H "X-Signature-256: sha256=invalid_signature" \
  -d '{"lamp_id": 1, "state": "RED"}'

# 期待される応答: 401 Unauthorized "Unauthorized - Invalid Signature"
```

### 3. エラーハンドリングテスト

```bash
# 不正なJSONのテスト
curl -X POST https://your-worker.workers.dev \
  -H "Content-Type: application/json" \
  -H "X-Signature-256: sha256=正しい署名" \
  -d '{"invalid": json}'

# 期待される応答: 400 Bad Request

# GET リクエストのテスト
curl -X GET https://your-worker.workers.dev

# 期待される応答: 405 Method Not Allowed
```

## Python クライアントでの署名生成

監視システム側で HMAC 署名を生成する Python コードの例：

```python
import hmac
import hashlib
import json
import requests

def create_signature(data: dict, secret: str) -> str:
    """HMAC署名を作成"""
    message = json.dumps(data, sort_keys=True).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return f"sha256={signature}"

def send_notification(worker_url: str, secret: str, notification_data: dict):
    """Cloudflare Workersに通知を送信"""
    signature = create_signature(notification_data, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Signature-256": signature
    }

    response = requests.post(
        worker_url,
        data=json.dumps(notification_data, sort_keys=True).encode('utf-8'),
        headers=headers,
        timeout=10
    )

    if response.status_code == 200:
        print("通知送信成功")
    else:
        print(f"通知送信失敗: {response.status_code} - {response.text}")

# 使用例
notification_data = {
    "timestamp": 1640995200,
    "lamp_id": 1,
    "state": "RED",
    "confidence": 0.95,
    "message": "ランプ 1 が RED 状態になりました"
}

send_notification(
    "https://your-worker.workers.dev",
    "your-secret-key",
    notification_data
)
```

**重要なポイント**:

1. **sort_keys=True**: JSON のキー順序を統一して署名の一貫性を保証
2. **UTF-8 エンコーディング**: 文字エンコーディングの統一
3. **タイムアウト設定**: ネットワーク障害時の適切な処理

## デプロイと運用

### 1. Wrangler を使用したデプロイ

```bash
# プロジェクトの初期化
npm create cloudflare@latest lamp-monitor-worker
cd lamp-monitor-worker

# 開発サーバーの起動
npm run dev

# 本番環境へのデプロイ
npm run deploy
```

### 2. 継続的デプロイメント

```yaml
# .github/workflows/deploy.yml
name: Deploy to Cloudflare Workers

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: "18"
      - run: npm install
      - run: npm run deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

### 3. 監視とログ

```javascript
// ログ出力の強化
console.log(
  `[${new Date().toISOString()}] Request from ${request.headers.get(
    "cf-connecting-ip"
  )}`
);
console.log(
  `[${new Date().toISOString()}] Notification sent for lamp ${body.lamp_id}`
);
```

Cloudflare Dashboard の「Logs」セクションでリアルタイムログを確認できます。

## パフォーマンスと制限

### Cloudflare Workers の制限

- **CPU 時間**: 10ms（無料プラン）、50ms（有料プラン）
- **メモリ**: 128MB
- **リクエストサイズ**: 100MB
- **レスポンスサイズ**: 100MB

### 最適化のポイント

1. **非同期処理**: `await` を適切に使用
2. **エラーハンドリング**: 早期リターンで CPU 時間を節約
3. **ログ出力**: 本番環境では必要最小限に制限

## セキュリティベストプラクティス

### 1. 署名検証の強化

```javascript
// タイムスタンプベースの署名検証（リプレイ攻撃対策）
function isTimestampValid(timestamp, tolerance = 300) {
  const now = Math.floor(Date.now() / 1000);
  return Math.abs(now - timestamp) <= tolerance;
}
```

### 2. レート制限

```javascript
// 簡易的なレート制限
const rateLimiter = new Map();

function checkRateLimit(ip, limit = 10, window = 60) {
  const now = Date.now();
  const key = `${ip}:${Math.floor(now / (window * 1000))}`;

  const count = rateLimiter.get(key) || 0;
  if (count >= limit) {
    return false;
  }

  rateLimiter.set(key, count + 1);
  return true;
}
```

### 3. 入力検証

```javascript
function validateNotificationData(data) {
  if (!data.lamp_id || typeof data.lamp_id !== "number") {
    return false;
  }
  if (!data.state || !["RED", "GREEN", "UNKNOWN"].includes(data.state)) {
    return false;
  }
  if (
    data.confidence !== undefined &&
    (typeof data.confidence !== "number" ||
      data.confidence < 0 ||
      data.confidence > 1)
  ) {
    return false;
  }
  return true;
}
```

## トラブルシューティング

### よくある問題と対策

1. **署名検証エラー**

   - 共通鍵の不一致を確認
   - JSON のキー順序（sort_keys）を確認
   - 文字エンコーディングを確認

2. **Discord 通知が届かない**

   - Webhook URL の有効性を確認
   - Discord サーバーの権限設定を確認
   - メッセージ形式の妥当性を確認

3. **Workers のタイムアウト**
   - CPU 時間の使用量を確認
   - 非同期処理の適切な実装を確認
   - 不要な処理の削除

### デバッグ用ツール

```javascript
// デバッグ情報の出力
function debugLog(message, data = null) {
  if (env.DEBUG === "true") {
    console.log(`[DEBUG] ${message}`, data ? JSON.stringify(data) : "");
  }
}
```

## まとめ

Cloudflare Workers による通知基盤の構築により、以下を実現できました：

### 技術的成果

1. **セキュアな通知システム**: HMAC 署名による認証
2. **高可用性**: Cloudflare のグローバルインフラを活用
3. **コスト効率**: サーバーレスによる従量課金
4. **拡張性**: 将来的な機能追加に対応可能な設計

### 開発プロセスでの価値

1. **早期検証**: カメラ実装前に通知システムを検証
2. **責任分離**: 各コンポーネントの独立した開発・テスト
3. **トラブルシューティング**: 問題の切り分けが容易
4. **段階的統合**: リスクを最小化した開発プロセス

次回の記事では、この通知基盤を活用して、疑似ダッシュボードでランプ検出ロジックの検証を行います。通知システムが確立されたことで、ロジックの動作確認に集中できるようになりました。

---

_本記事は制御盤ランプ監視システム開発記の第 1 回です。次回「疑似ダッシュボードでロジック検証」もお楽しみに！_
