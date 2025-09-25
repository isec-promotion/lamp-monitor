# Lamp Monitor (Windows → Raspberry Pi5)

制御盤の **12 個ランプ（正常=緑／異常=赤）** をカメラで監視し、**赤を検出したら Cloudflare Workers 経由で Discord Webhook に通知**するプロジェクト。ランプは長方形であり、幅の方が広く、フィナンシェのような形をしてます。ランプには 1 から 12 の番号が割り振られてます。  
まずは **Windows 11** で「疑似ダッシュボード → 判定＆通知」を完成させ、次に **Web カメラ実験**、最後に **Raspberry Pi 5** へ移植する三段階方式です。そのため、Python を使って実現します。

---

## 特長 / ねらい

- **段階開発**：合成映像でロジック完成 → Web カメラで実験 → 実機へ
- **I/O 分離**：フレーム取得（入力）と判定/通知（処理）を分離し移植容易
- **誤検知対策**：HSV 色判定＋形態学的処理＋多数決（フレーム窓）
- **スパム防止**：同一ランプの再通知を間隔制御
- **設定ファイル駆動**：ROI 座標・閾値・通知先 URL などを `config.yaml` で一元管理

---

## ディレクトリ構成

```
lamp-monitor/
├── README.md                   # プロジェクト全体の概要と利用方法
├── SETUP.md                    # セットアップ手順書（環境構築ガイド）
├── config.yaml                 # 設定ファイル（カメラ/ROI/通知/閾値など）
├── sim_dashboard.py            # 疑似ダッシュボード（制御盤ランプの模擬表示ツール）
├── monitor_test.py             # 疑似ランプ監視・通知テスター（カメラなしで動作確認）
├── monitor_webcam.py           # Webカメラ版ランプ監視（実カメラ映像を解析して通知）
├── monitor_webcam-pi.py        # Raspberry Pi版ランプ監視（実カメラ映像を解析して通知）
├── roi_tool.py                 # ROI設定ツール（マウス操作でランプ検知領域を設定・保存）
├── cloudflare-worker.js        # Cloudflare Workers（HMAC署名検証＋Discord通知）
└── utils/                      # ユーティリティツール
    ├── camera_debug.py         # カメラデバッグツール
    └── test_camera.py          # カメラテストツール
```

---

## 前提条件

- **Windows 11**
- **Python 3.11**（推奨）
- Cloudflare Workers の受け口 URL（例: `https://<your-worker>.workers.dev/notify`）
  - 任意で共通鍵（`SHARED_SECRET`）による署名検証を実装可能
- Web カメラ（UVC 準拠推奨）※合成のみなら不要

---

## セットアップ（Windows 11）

```powershell
mkdir C:\lamp-monitor
cd C:\lamp-monitor
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install opencv-python numpy requests pyyaml
```

---

## 設定（`config.yaml`）

- 主要項目

  - `camera.size` / `camera.fps`：処理負荷と検出安定のバランスで 1280×720 / 20fps 目安
  - `notify.worker_url` / `notify.secret`：Cloudflare Workers のエンドポイントと共通鍵
  - `notify.min_interval_sec`：同一ランプの再通知最短間隔
  - `logic.*`：HSV 閾値、形態学的処理サイズ、多数決窓フレーム数など
  - `rois`：ランプ 12 個の矩形座標（`x,y,w,h`）

初期は合成用の ROI（サンプル値）で OK。Web カメラ実験時に `roi_tool.py` で実映像に合わせて更新します。

---

## 実行手順

### 1) 疑似ダッシュボードでロジック検証

別ウィンドウ 2 本を起動：

```powershell
# ① 疑似ダッシュボード（操作用ウィンドウ）
python .\sim_dashboard.py

# ② 判定＆通知（合成フレームを読み取り）
python .\monitor_test.py
```

**操作（SIM 画面）**
`1–0`=L1〜L10、`-`=L11、`=`=L12 のトグル／`g`=全緑／`r`=全赤／`b`=一部点滅／`a`=ランダム赤／`s`=画像保存／`q`=終了
→ 赤を作ると **Cloudflare Workers → Discord** に通知されます。

### 2) Web カメラで実験

```powershell
# ROI キャリブ（任意）
python .\roi_tool.py   # 12 個のランプをドラッグ選択→'s'でconfig.yamlに保存

# 判定＆通知（Webカメラ入力）
python .\monitor_webcam.py
```

**重要**：露出・ゲイン・ホワイトバランス（AWB）は**手動固定**が望ましい（カメラユーティリティがあればそこで固定）。
自動露出/AWB のままだと赤/緑の色域がぶれ、誤検知が増えます。

---

## Cloudflare Workers 連携（概要）

- Pi/PC 側：`worker_url` に `POST application/json`（必要に応じ `X-Signature` ヘッダで HMAC）
- Workers 側：署名検証 → Discord Webhook へ転送
- セキュリティ：Webhook URL は **環境変数（`DISCORD_WEBHOOK_URL`）** に保持し直書きを避ける

---

## Raspberry Pi 5 への移植

- 判定・通知ロジックは流用。**フレーム取得のみ置換**（`picamera2` 推奨）
- 同じ `config.yaml` を持ち込み、ROI と HSV 閾値を現場照明に合わせて微調整
- 常駐は `systemd`（Windows サービス化も可）

---

## チューニング指針（誤検知/過検知対策）

- **HSV 閾値**：`logic.red_ratio_thresh` / `green_ratio_thresh` を実映像で調整
- **明るさフィルタ**：`logic.min_brightness_v` を上げて暗部ノイズを除外
- **形態学的処理**：`logic.morphological_kernel` を 3〜5 程度でノイズ削り
- **多数決**：`logic.frames_window` を 3→7 に増やすと点滅・ちらつきに強い
- **ROI の取り方**：ランプ反射や周辺光を含めないよう小さめに（丸 LED でも矩形で OK）

---

## 運用のベストプラクティス

- **再通知制御**：`notify.min_interval_sec` を現場運用に合わせる（Discord スパム防止）
- **監査用スナップ**：一定間隔で静止画保存（ログ用途）を入れても良い
- **ヘルスチェック**：Workers で「直近受信時刻」を KV 等に保存し、一定時間なしで別経路通知

---

## トラブルシューティング

- **通知が来ない**：`worker_url` が正しいか／Workers で CORS/署名検証の失敗がないか
- **常に UNKNOWN**：露出/AWB 固定・ROI の再調整・`min_brightness_v` を確認
- **赤の誤検知**：`red_ratio_thresh` を上げる or ROI を小さくする or 照明条件を安定化
- **Web カメラが映らない**：他アプリが使用中でないか／UVC 準拠か／`VideoCapture(0, cv2.CAP_DSHOW)` を確認

---

## ライセンス / クレジット

- 本プロジェクトは社内/顧客向け PoC 用のテンプレートです。ライセンスは必要に応じて記載してください。

---

## 今後の拡張案

- LED の形状テンプレートマッチで反射耐性を向上
- カラー学習（k-means/ガウシアン混合）による色域自動学習
- マルチカメラ対応・複数パネル一括監視
- ダッシュボード（Web UI）で状態可視化／通知履歴検索
