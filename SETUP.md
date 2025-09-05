# ランプ監視システム セットアップガイド

## 概要

制御盤の 12 個のランプ（緑=正常、赤=異常）をカメラで監視し、赤を検出したら Cloudflare Workers 経由で Discord Webhook に通知するシステムです。

## ファイル構成

```
lamp-monitor/
├── README.md                 # プロジェクト概要
├── SETUP.md                  # このファイル（セットアップガイド）
├── config.yaml               # 設定ファイル
├── sim_dashboard.py          # 合成ダッシュボード（テスト用）
├── monitor_synthetic.py      # 合成フレーム監視
├── monitor_webcam.py         # Webカメラ監視
├── roi_tool.py               # ROI設定ツール
├── cloudflare-worker.js      # Cloudflare Workers用スクリプト
├── cloudflare-worker-simple.js # シンプル版Cloudflare Workers用スクリプト
└── utils/                    # ユーティリティツール
    ├── camera_debug.py       # カメラデバッグツール
    └── test_camera.py        # カメラテストツール
```

## セットアップ手順

### 1. 依存関係のインストール

```bash
pip install opencv-python numpy requests pyyaml
```

### 2. Cloudflare Workers の設定

1. Cloudflare Workers で新しいワーカーを作成
2. `cloudflare-worker.js`の内容をコピー
3. 以下の値を実際の値に変更：
   - `ALLOWED_SECRET`: 任意の共通鍵（強力なパスワードを推奨）
   - `DISCORD_WEBHOOK_URL`: Discord の Webhook URL

```javascript
// 例
const ALLOWED_SECRET = "pA!M.k_)!$G.vABQ9aeQmPNM";
const DISCORD_WEBHOOK_URL =
  "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN";
```

4. ワーカーをデプロイし、URL を取得（例: `https://your-worker.workers.dev`）

### 3. 設定ファイルの更新

`config.yaml`を編集：

```yaml
notify:
  worker_url: "https://your-worker.workers.dev/notify" # 実際のWorkers URL
  secret: "pA!M.k_)!$G.vABQ9aeQmPNM" # Workersと同じ共通鍵
  min_interval_sec: 300 # 通知間隔（秒）
```

### 4. Discord Webhook URL の取得

1. Discord サーバーで通知を受け取りたいチャンネルを選択
2. チャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフック
3. ウェブフック URL をコピーして`cloudflare-worker.js`に設定

## 使用方法

### ステップ 1: 合成ダッシュボードでテスト

```bash
python sim_dashboard.py
```

**操作方法:**

- `1-0`: ランプ 1-10 のトグル
- `-`: ランプ 11 のトグル
- `=`: ランプ 12 のトグル
- `g`: 全て緑
- `r`: 全て赤
- `a`: ランダム赤
- `s`: 画像保存
- `q`: 終了

### ステップ 2: ROI 設定（Web カメラ使用時）

```bash
python roi_tool.py
```

**操作方法:**

- マウスドラッグ: ROI 設定
- `n`: 次のランプ
- `p`: 前のランプ
- `d`: 現在のランプの ROI を削除
- `s`: 設定を保存
- `q`: 終了

### ステップ 3: Web カメラ監視

```bash
python monitor_webcam.py
```

**操作方法:**

- `q`: 終了
- `s`: 現在のフレームを保存
- `r`: ランプ履歴をリセット

## 設定項目の説明

### カメラ設定

```yaml
camera:
  size: [1280, 720] # 解像度
  fps: 20 # フレームレート
  device_id: 0 # カメラデバイスID
```

### 判定ロジック設定

```yaml
logic:
  red_ratio_thresh: 0.3 # 赤判定の面積比閾値（0.0-1.0）
  green_ratio_thresh: 0.3 # 緑判定の面積比閾値（0.0-1.0）
  min_brightness_v: 30 # 最小明度（0-255）
  morphological_kernel: 3 # ノイズ除去カーネルサイズ
  frames_window: 5 # 多数決フィルタのフレーム数
```

### HSV 色域設定

```yaml
logic:
  red_hue_range: [[0, 10], [170, 180]] # 赤色相範囲
  red_sat_min: 100 # 赤彩度最小値
  red_val_min: 50 # 赤明度最小値

  green_hue_range: [40, 80] # 緑色相範囲
  green_sat_min: 100 # 緑彩度最小値
  green_val_min: 50 # 緑明度最小値
```

## チューニングガイド

### 誤検知が多い場合

1. **HSV 閾値を調整**:

   - `red_ratio_thresh`を上げる（0.3 → 0.5）
   - `min_brightness_v`を上げる（30 → 50）

2. **ROI を小さくする**:

   - ランプ以外の反射や周辺光を除外

3. **多数決フィルタを強化**:
   - `frames_window`を増やす（5 → 7）

### 検出感度が低い場合

1. **HSV 閾値を下げる**:

   - `red_ratio_thresh`を下げる（0.3 → 0.2）
   - `min_brightness_v`を下げる（30 → 20）

2. **色域を広げる**:
   - `red_hue_range`や`green_hue_range`を調整

### カメラ設定の最適化

1. **露出を手動固定**:

   - カメラユーティリティで自動露出を OFF
   - 固定値に設定

2. **ホワイトバランスを手動固定**:

   - 自動ホワイトバランスを OFF
   - 照明環境に合わせて固定

3. **ゲインを調整**:
   - ノイズを抑えるため適切なゲイン値に設定

## トラブルシューティング

### 通知が来ない

1. **Workers URL の確認**:

   - `config.yaml`の URL が正しいか確認
   - ブラウザでアクセスして 405 エラーが返ることを確認

2. **共通鍵の確認**:

   - `config.yaml`と`cloudflare-worker.js`の`secret`が一致しているか

3. **Discord Webhook URL の確認**:
   - URL が正しいか確認
   - チャンネルの権限を確認

### カメラが映らない

1. **デバイス ID の確認**:

   - `config.yaml`の`device_id`を変更（0, 1, 2...）

2. **他のアプリケーションの確認**:

   - カメラを使用している他のアプリを終了

3. **ドライバーの確認**:
   - UVC 準拠のカメラドライバーがインストールされているか

### 常に UNKNOWN 状態

1. **ROI の確認**:

   - `roi_tool.py`で ROI を再設定

2. **照明条件の確認**:

   - 十分な明るさがあるか
   - 反射や影の影響を確認

3. **HSV 閾値の調整**:
   - 実際の色に合わせて調整

## セキュリティ考慮事項

1. **共通鍵の管理**:

   - 強力なパスワードを使用
   - 定期的に変更

2. **Webhook URL の保護**:

   - URL を外部に漏らさない
   - 必要に応じて IP 制限を設定

3. **ログの管理**:
   - 機密情報がログに出力されないよう注意

## 運用のベストプラクティス

1. **定期的な動作確認**:

   - 週 1 回程度、手動でテスト

2. **設定のバックアップ**:

   - `config.yaml`を定期的にバックアップ

3. **ログの監視**:

   - エラーログを定期的に確認

4. **通知間隔の調整**:
   - 運用状況に応じて`min_interval_sec`を調整
