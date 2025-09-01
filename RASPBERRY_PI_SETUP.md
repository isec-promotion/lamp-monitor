# Raspberry Pi 用 ランプ監視システム セットアップ手順書

## 概要

制御盤の 12 個のランプ（緑=正常、赤=異常）をカメラで監視し、赤を検出したら Cloudflare Workers 経由で Discord Webhook に通知するシステムを Raspberry Pi で動作させるための手順書です。

## 前提条件

- **Raspberry Pi 3/4/5**（推奨：Pi 4/5）
- **Raspberry Pi OS**（Bullseye 以降推奨）
- **USB Web カメラ**（UVC 準拠推奨）
- **インターネット接続**（Cloudflare Workers 連携用）
- **Python 3.7 以上**

## セットアップ手順

### 1. システムの更新

```bash
# システムパッケージを最新に更新
sudo apt update
sudo apt upgrade -y

# 必要なシステムパッケージをインストール
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libatlas-base-dev \
    libhdf5-dev \
    libhdf5-serial-dev \
    libatlas-base-dev \
    libjasper-dev \
    libqtcore4 \
    libqtgui4 \
    libqt4-test \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    libgtk-3-0 \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libatlas-base-dev \
    gfortran \
    wget \
    git
```

### 2. プロジェクトディレクトリの作成

```bash
# ホームディレクトリに移動
cd ~

# プロジェクトディレクトリを作成
mkdir lamp-monitor
cd lamp-monitor

# プロジェクトファイルをコピー（USBメモリやSCP等で転送）
# または、GitHubからクローン（リポジトリがある場合）
```

**注意**: どちらの方法を選択するかは、運用方針によって決めてください。

### 3. Python ライブラリのインストール

#### 方法 1: apt を使用（推奨）

```bash
# 必要なPythonライブラリをaptでインストール
sudo apt install -y \
    python3-opencv \
    python3-numpy \
    python3-requests \
    python3-yaml \
    python3-pil \
    python3-pip \
    python3-venv

# インストール確認
python3 -c "import cv2; import numpy; import requests; import yaml; print('ライブラリのインストールが完了しました')"
```

#### 方法 2: pip を使用（仮想環境推奨）

```bash
# Python仮想環境を作成
python3 -m venv .venv

# 仮想環境をアクティベート
source .venv/bin/activate

# pipを最新版に更新
pip install --upgrade pip

# 必要なPythonライブラリをインストール
pip install \
    opencv-python-headless \
    numpy \
    requests \
    pyyaml \
    pillow

# インストール確認
python3 -c "import cv2; import numpy; import requests; import yaml; print('ライブラリのインストールが完了しました')"
```

**注意**:

- **apt を使用**: システム全体にインストールされ、どのディレクトリからでも実行可能
- **pip を使用**: 仮想環境内にインストールされ、環境を分離できる（推奨）
- `opencv-python-headless`を使用することで、GUI ライブラリ（X11）に依存せずに OpenCV を使用できます

### 4. カメラの接続と権限設定

```bash
# USBカメラが認識されているか確認
lsusb

# カメラデバイスが存在するか確認
ls /dev/video*

# カメラグループにユーザーを追加（カメラアクセス権限付与）
sudo usermod -a -G video $USER

# 権限変更を反映するため、一度ログアウトして再ログイン
# または、以下のコマンドで即座に反映
newgrp video

# カメラのテスト
python3 -c "
import cv2
cap = cv2.VideoCapture(0)
if cap.isOpened():
    print('カメラが正常に認識されました')
    ret, frame = cap.read()
    if ret:
        print(f'フレームサイズ: {frame.shape}')
    cap.release()
else:
    print('カメラの認識に失敗しました')
"
```

### 5. 設定ファイルの準備

`config.yaml`ファイルを編集して、Raspberry Pi 環境に合わせて設定を調整します：

```bash
# 設定ファイルを編集
nano config.yaml
```

**重要な設定項目**:

```yaml
# カメラ設定（Raspberry Pi向け最適化）
camera:
  size: [640, 480] # 解像度を下げて処理負荷を軽減
  fps: 15 # フレームレートを下げて安定性を向上
  device_id: 0 # カメラデバイスID

# 通知設定
notify:
  worker_url: "https://your-worker.workers.dev" # 実際のWorkers URL
  secret: "your-secret-key" # 実際の共通鍵
  min_interval_sec: 300 # 通知間隔（秒）

# 判定ロジック設定（Raspberry Pi向け調整）
logic:
  frames_window: 7 # フレーム窓を増やして安定性を向上
  morphological_kernel: 5 # ノイズ除去を強化
```

### 6. ROI 設定ツールの実行

カメラで実際のランプの位置を設定します：

#### apt を使用した場合

```bash
# ROI設定ツールを実行
python3 roi_tool.py
```

#### pip を使用した場合（仮想環境）

```bash
# 仮想環境をアクティベート
source .venv/bin/activate

# ROI設定ツールを実行
python3 roi_tool.py
```

**操作方法**:

- マウスドラッグで各ランプの ROI 領域を設定
- `n`: 次のランプ
- `p`: 前のランプ
- `d`: 現在のランプの ROI を削除
- `s`: 設定を保存
- `q`: 終了

**注意**: Raspberry Pi では、X11 環境が必要です。ヘッドレス環境の場合は、VNC や SSH X11 フォワーディングを使用してください。

### 7. 合成ダッシュボードのテスト

まず、合成環境でシステムが正常に動作するかテストします：

#### apt を使用した場合

```bash
# 合成ダッシュボードを起動
python3 sim_dashboard.py
```

#### pip を使用した場合（仮想環境）

```bash
# 仮想環境をアクティベート
source .venv/bin/activate

# 合成ダッシュボードを起動
python3 sim_dashboard.py
```

**操作方法**:

- `1-0`: ランプ 1-10 のトグル
- `-`: ランプ 11 のトグル
- `=`: ランプ 12 のトグル
- `g`: 全て緑
- `r`: 全て赤
- `a`: ランダム赤
- `s`: 画像保存
- `q`: 終了

### 8. Web カメラ監視システムの実行

実際のカメラでランプ監視を開始します：

#### apt を使用した場合

```bash
# Webカメラ監視システムを起動
python3 monitor_webcam-pi.py
```

#### pip を使用した場合（仮想環境）

```bash
# 仮想環境をアクティベート
source .venv/bin/activate

# Webカメラ監視システムを起動
python3 monitor_webcam-pi.py
```

**操作方法**:

- `q`: 終了
- `s`: 現在のフレームを保存
- `r`: ランプ履歴をリセット

## 自動起動の設定

### systemd サービスとして登録

```bash
# サービスファイルを作成
sudo nano /etc/systemd/system/lamp-monitor.service
```

**サービスファイルの内容**:

#### apt を使用した場合

```ini
[Unit]
Description=Lamp Monitor System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/lamp-monitor
ExecStart=/usr/bin/python3 monitor_webcam-pi.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### pip を使用した場合（仮想環境）

```ini
[Unit]
Description=Lamp Monitor System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/lamp-monitor
Environment=PATH=/home/pi/lamp-monitor/.venv/bin
ExecStart=/home/pi/lamp-monitor/.venv/bin/python3 monitor_webcam-pi.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**サービスの有効化と開始**:

```bash
# systemdをリロード
sudo systemctl daemon-reload

# サービスを有効化（自動起動）
sudo systemctl enable lamp-monitor.service

# サービスを開始
sudo systemctl start lamp-monitor.service

# サービスの状態確認
sudo systemctl status lamp-monitor.service

# ログの確認
sudo journalctl -u lamp-monitor.service -f
```

## トラブルシューティング

### カメラが認識されない

```bash
# カメラデバイスの確認
ls /dev/video*

# カメラドライバーの確認
dmesg | grep -i camera
dmesg | grep -i usb

# カメラの権限確認
ls -la /dev/video*

# カメラグループの確認
groups $USER
```

### OpenCV のエラー

```bash
# OpenCVのバージョン確認
python3 -c "import cv2; print(cv2.__version__)"

# カメラテスト
python3 -c "
import cv2
print('OpenCV version:', cv2.__version__)
cap = cv2.VideoCapture(0)
print('Camera opened:', cap.isOpened())
if cap.isOpened():
    ret, frame = cap.read()
    print('Frame read:', ret)
    if ret:
        print('Frame shape:', frame.shape)
    cap.release()
"
```

### メモリ不足

```bash
# メモリ使用量の確認
free -h

# スワップの確認
swapon --show

# スワップファイルの作成（必要に応じて）
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 処理が重い

```bash
# CPU使用率の確認
top

# 設定ファイルで解像度とフレームレートを下げる
# config.yamlのcamera.sizeとcamera.fpsを調整
```

## パフォーマンス最適化

### 1. 解像度とフレームレートの調整

```yaml
camera:
  size: [640, 480] # 1280x720から下げる
  fps: 15 # 20から下げる
```

### 2. 処理間隔の調整

```yaml
logic:
  frames_window: 7 # 安定性を重視
  morphological_kernel: 5 # ノイズ除去を強化
```

### 3. 通知間隔の調整

```yaml
notify:
  min_interval_sec: 300 # 5分間隔（運用に応じて調整）
```

## 監視とログ

### ログファイルの設定

```bash
# ログディレクトリの作成
mkdir -p /home/pi/lamp-monitor/logs

# ログローテーションの設定
sudo nano /etc/logrotate.d/lamp-monitor
```

**ログローテーション設定**:

```
/home/pi/lamp-monitor/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 pi pi
}
```

### システム監視

```bash
# システムリソースの監視
htop

# ディスク使用量の確認
df -h

# 温度の確認（Raspberry Pi）
vcgencmd measure_temp
```

## セキュリティ考慮事項

### 1. ファイアウォールの設定

```bash
# UFWのインストールと設定
sudo apt install ufw
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow out 80/tcp
sudo ufw allow out 443/tcp
```

### 2. 定期的な更新

```bash
# 自動更新の設定
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 3. ログの監視

```bash
# ログの監視スクリプトを作成
nano /home/pi/lamp-monitor/monitor_logs.sh
```

## 運用のベストプラクティス

### 1. 定期的な動作確認

- 週 1 回程度、手動でテスト実行
- 通知の動作確認
- ログの確認

### 2. バックアップ

```bash
# 設定ファイルのバックアップ
cp config.yaml config.yaml.backup.$(date +%Y%m%d)

# プロジェクト全体のバックアップ
tar -czf lamp-monitor-backup-$(date +%Y%m%d).tar.gz lamp-monitor/
```

### 3. 更新手順

#### apt を使用した場合

```bash
# システムの更新
sudo apt update && sudo apt upgrade -y
```

#### pip を使用した場合（仮想環境）

```bash
# システムの更新
sudo apt update && sudo apt upgrade -y

# Pythonライブラリの更新
source .venv/bin/activate
pip install --upgrade opencv-python-headless numpy requests pyyaml pillow
```

## サポートとトラブルシューティング

### よくある問題

1. **カメラが認識されない**: 権限設定とドライバーの確認
2. **処理が重い**: 解像度とフレームレートの調整
3. **通知が来ない**: ネットワーク設定と Workers URL の確認
4. **メモリ不足**: スワップファイルの作成

### ログの確認方法

```bash
# システムログの確認
sudo journalctl -u lamp-monitor.service

# リアルタイムログの確認
sudo journalctl -u lamp-monitor.service -f

# エラーログの確認
sudo journalctl -u lamp-monitor.service -p err
```

### 緊急時の対処

```bash
# サービスの停止
sudo systemctl stop lamp-monitor.service

# 手動での実行（デバッグ用）
cd /home/pi/lamp-monitor

#### apt を使用した場合
python3 monitor_webcam-pi.py

#### pip を使用した場合（仮想環境）
source .venv/bin/activate
python3 monitor_webcam-pi.py

# サービスの再起動
sudo systemctl start lamp-monitor.service
```

## まとめ

この手順書に従って設定することで、Raspberry Pi でランプ監視システムを動作させることができます。

### インストール方法の選択

- **apt を使用**: システム全体にインストールされ、セットアップが簡単
- **pip を使用**: 仮想環境内にインストールされ、環境を分離できる（推奨）

どちらの方法を選択するかは、運用方針や管理のしやすさを考慮して決めてください。

問題が発生した場合は、ログを確認し、段階的にトラブルシューティングを行ってください。

システムが正常に動作するようになったら、本格運用に向けて、セキュリティ設定やバックアップ体制の整備を検討してください。
