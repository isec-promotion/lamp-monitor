# 制御盤ランプ監視システム開発記 (3) - Raspberry Pi 5 への移植

## はじめに

前回までの記事では、合成ダッシュボードでのロジック検証と Web カメラでの実環境実験について解説しました。今回は開発の最終段階である「Raspberry Pi 5 への移植」について詳しく解説します。実際の制御盤監視システムとして完成させるまでの過程と、運用上の課題・対策を中心にお話しします。

## Raspberry Pi 移植の意義

### なぜ Raspberry Pi なのか？

制御盤監視システムを実用化するにあたり、Raspberry Pi を選択した理由は以下の通りです：

1. **小型・省電力**: 制御盤近くに設置可能
2. **Linux ベース**: 開発したコードをそのまま移植可能
3. **豊富な I/O**: 将来的な拡張に対応
4. **コストパフォーマンス**: 商用システムとして現実的
5. **長期サポート**: 産業用途での安定運用が可能

### Raspberry Pi 5 の選択理由

Raspberry Pi 5 を選択した技術的理由：

- **ARM Cortex-A76 クアッドコア**: 画像処理に十分な性能
- **8GB RAM**: OpenCV と複数プロセスの同時実行に対応
- **USB 3.0**: 高解像度カメラからの高速データ転送
- **Gigabit Ethernet**: 安定したネットワーク通信
- **PCIe 2.0**: 将来的な拡張カードに対応

## 移植時の技術的課題

### 1. アーキテクチャの違い

Windows（x86_64）から Raspberry Pi（ARM64）への移植で発生する課題：

```python
# Windows版では問題なかったが、ARM64では最適化が必要
def initialize_camera_fast(self) -> bool:
    """カメラを高速初期化（Raspberry Pi向けに最適化）"""
    device_id = self.camera_config["device_id"]

    try:
        # Raspberry Pi / LinuxではCAP_V4L2を明示的に指定すると安定しやすい
        self.cap = cv2.VideoCapture(device_id, cv2.CAP_V4L2)

        if not self.cap.isOpened():
            print("カメラの初期化に失敗しました。デバイスが接続されているか、権限を確認してください。")
            return False

        print("カメラ初期化成功 (V4L2)")

        # 基本設定のみ適用（ARM64での安定性を重視）
        width, height = self.camera_config["size"]
        fps = self.camera_config["fps"]

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 遅延削減

        return True

    except Exception as e:
        print(f"カメラ初期化中に予期せぬエラーが発生: {e}")
        if self.cap is not None:
            self.cap.release()
        return False
```

**主な変更点**:

- Windows の `CAP_DSHOW` から Linux の `CAP_V4L2` に変更
- エラーハンドリングの強化
- ARM64 での安定性を重視した設定

### 2. 依存関係の管理

Raspberry Pi での Python ライブラリインストールには 2 つのアプローチがあります：

#### アプローチ 1: apt パッケージマネージャー（推奨）

```bash
# システムパッケージとして安定したバージョンをインストール
sudo apt install -y \
    python3-opencv \
    python3-numpy \
    python3-requests \
    python3-yaml \
    python3-pil

# インストール確認
python3 -c "import cv2; import numpy; import requests; import yaml; print('ライブラリのインストールが完了しました')"
```

**メリット**:

- システム全体で利用可能
- 依存関係が自動解決
- ARM64 向けに最適化済み
- 長期サポート

#### アプローチ 2: pip + 仮想環境

```bash
# Python仮想環境を作成
python3 -m venv .venv
source .venv/bin/activate

# 必要なライブラリをインストール
pip install \
    opencv-python-headless \
    numpy \
    requests \
    pyyaml \
    pillow
```

**メリット**:

- 環境の分離
- バージョン管理の柔軟性
- 開発環境との一貫性

### 3. パフォーマンス最適化

ARM64 アーキテクチャでの最適化設定：

```yaml
# config.yaml - Raspberry Pi向け最適化
camera:
  size: [640, 480] # 解像度を下げて処理負荷を軽減
  fps: 15 # フレームレートを下げて安定性を向上
  device_id: 0

logic:
  frames_window: 7 # フレーム窓を増やして安定性を向上
  morphological_kernel: 5 # ノイズ除去を強化
  red_ratio_thresh: 0.25 # 閾値を環境に合わせて調整
  green_ratio_thresh: 0.25

notify:
  min_interval_sec: 300 # 通知間隔を長めに設定（運用負荷軽減）
```

**最適化のポイント**:

- **解像度の調整**: 1280x720 → 640x480 で処理負荷を約 1/4 に削減
- **フレームレートの調整**: 20fps → 15fps で CPU 使用率を削減
- **安定性の向上**: フレーム窓を増やして誤検知を削減

## systemd による常駐サービス化

実用的な監視システムとして、systemd サービスとして常駐化します。

### サービスファイルの作成

```bash
# サービスファイルを作成
sudo nano /etc/systemd/system/lamp-monitor.service
```

#### apt を使用した場合のサービス設定

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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

#### pip + 仮想環境を使用した場合のサービス設定

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
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### サービスの管理

```bash
# systemdをリロード
sudo systemctl daemon-reload

# サービスを有効化（自動起動）
sudo systemctl enable lamp-monitor.service

# サービスを開始
sudo systemctl start lamp-monitor.service

# サービスの状態確認
sudo systemctl status lamp-monitor.service

# リアルタイムログの確認
sudo journalctl -u lamp-monitor.service -f

# サービスの停止
sudo systemctl stop lamp-monitor.service

# サービスの再起動
sudo systemctl restart lamp-monitor.service
```

## 運用監視とログ管理

### ログ管理の実装

```python
import logging
import logging.handlers

class WebcamMonitorFast:
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        # ログ設定
        self.setup_logging()

        self.logger.info("設定ファイル読み込み中...")
        self.config = self.load_config(config_path)

        self.logger.info("検出器初期化中...")
        self.detector = LampDetector(self.config)

        self.logger.info("初期化完了")

    def setup_logging(self):
        """ログ設定"""
        # ログディレクトリの作成
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # ログフォーマット
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # ファイルハンドラー（ローテーション付き）
        file_handler = logging.handlers.RotatingFileHandler(
            f"{log_dir}/lamp_monitor.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)

        # コンソールハンドラー
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        # ロガー設定
        self.logger = logging.getLogger("LampMonitor")
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
```

### システム監視スクリプト

```bash
#!/bin/bash
# monitor_system.sh - システム監視スクリプト

LOG_FILE="/home/pi/lamp-monitor/logs/system_monitor.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# CPU温度の確認
TEMP=$(vcgencmd measure_temp | cut -d'=' -f2)

# メモリ使用量の確認
MEM_USAGE=$(free | grep Mem | awk '{printf "%.1f", $3/$2 * 100.0}')

# ディスク使用量の確認
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}')

# サービス状態の確認
SERVICE_STATUS=$(systemctl is-active lamp-monitor.service)

# ログ出力
echo "[$DATE] Temp: $TEMP, Memory: ${MEM_USAGE}%, Disk: $DISK_USAGE, Service: $SERVICE_STATUS" >> $LOG_FILE

# 異常時の通知（例：温度が80度を超えた場合）
TEMP_NUM=$(echo $TEMP | sed 's/°C//')
if (( $(echo "$TEMP_NUM > 80" | bc -l) )); then
    echo "[$DATE] WARNING: High temperature detected: $TEMP" >> $LOG_FILE
    # 必要に応じて通知処理を追加
fi

# サービスが停止している場合の自動復旧
if [ "$SERVICE_STATUS" != "active" ]; then
    echo "[$DATE] ERROR: Service is not active. Attempting restart..." >> $LOG_FILE
    sudo systemctl restart lamp-monitor.service
fi
```

### cron による定期監視

```bash
# crontabを編集
crontab -e

# 5分ごとにシステム監視を実行
*/5 * * * * /home/pi/lamp-monitor/monitor_system.sh

# 日次でログのクリーンアップ
0 2 * * * find /home/pi/lamp-monitor/logs -name "*.log.*" -mtime +7 -delete
```

## セキュリティ対策

### 1. ファイアウォール設定

```bash
# UFWのインストールと基本設定
sudo apt install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH接続を許可
sudo ufw allow ssh

# HTTPS通信を許可（Cloudflare Workers通信用）
sudo ufw allow out 443/tcp

# ファイアウォールを有効化
sudo ufw enable

# 設定確認
sudo ufw status verbose
```

### 2. 自動更新の設定

```bash
# 自動更新パッケージのインストール
sudo apt install unattended-upgrades

# 自動更新の設定
sudo dpkg-reconfigure -plow unattended-upgrades

# 設定ファイルの確認
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```

### 3. SSH セキュリティ強化

```bash
# SSH設定ファイルの編集
sudo nano /etc/ssh/sshd_config

# 推奨設定
# Port 22 → Port 2222 (デフォルトポートの変更)
# PermitRootLogin no
# PasswordAuthentication no (公開鍵認証のみ)
# AllowUsers pi

# SSH サービスの再起動
sudo systemctl restart ssh
```

## 実運用での課題と対策

### 1. ハードウェア障害対策

#### SD カードの寿命対策

```bash
# ログの書き込み頻度を削減
# /etc/systemd/journald.conf
[Journal]
Storage=volatile
RuntimeMaxUse=64M

# tmpfsの活用
# /etc/fstab に追加
tmpfs /tmp tmpfs defaults,noatime,nosuid,size=100m 0 0
tmpfs /var/tmp tmpfs defaults,noatime,nosuid,size=30m 0 0
```

#### 電源障害対策

```python
import signal
import sys

class GracefulShutdown:
    def __init__(self):
        self.shutdown = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        print(f"シャットダウンシグナル受信: {signum}")
        self.shutdown = True

# メインループでの使用例
shutdown_handler = GracefulShutdown()

while self.running and not shutdown_handler.shutdown:
    # 通常の処理
    ret, frame = self.cap.read()
    # ...

    if shutdown_handler.shutdown:
        print("グレースフルシャットダウンを実行中...")
        break
```

### 2. ネットワーク障害対策

```python
def send_notification_with_retry(self, notification_data: Dict, max_retries: int = 3):
    """リトライ機能付き通知送信"""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                self.notify_config["worker_url"],
                data=json.dumps(notification_data, sort_keys=True).encode('utf-8'),
                headers=self.get_headers(notification_data),
                timeout=10
            )

            if response.status_code == 200:
                self.logger.info(f"通知送信成功 (試行回数: {attempt + 1})")
                return True
            else:
                self.logger.warning(f"通知送信失敗 HTTP {response.status_code} (試行回数: {attempt + 1})")

        except requests.RequestException as e:
            self.logger.error(f"通知送信エラー (試行回数: {attempt + 1}): {e}")

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # 指数バックオフ

    self.logger.error(f"通知送信に {max_retries} 回失敗しました")
    return False
```

### 3. 環境変化への対応

#### 照明条件の変化

```python
def adaptive_threshold_adjustment(self):
    """照明条件に応じた閾値の自動調整"""
    # 過去1時間の判定結果を分析
    recent_results = self.get_recent_detection_results(hours=1)

    # UNKNOWN判定が多い場合は閾値を下げる
    unknown_ratio = recent_results.count("UNKNOWN") / len(recent_results)

    if unknown_ratio > 0.5:  # 50%以上がUNKNOWNの場合
        self.logic_config["red_ratio_thresh"] *= 0.9
        self.logic_config["green_ratio_thresh"] *= 0.9
        self.logger.info(f"閾値を自動調整: red={self.logic_config['red_ratio_thresh']:.2f}, green={self.logic_config['green_ratio_thresh']:.2f}")
```

#### カメラ位置のずれ検出

```python
def detect_camera_displacement(self, frame: np.ndarray) -> bool:
    """カメラ位置のずれを検出"""
    # 基準フレームとの差分を計算
    if hasattr(self, 'reference_frame'):
        diff = cv2.absdiff(frame, self.reference_frame)
        diff_ratio = np.sum(diff > 30) / diff.size

        if diff_ratio > 0.3:  # 30%以上の変化
            self.logger.warning(f"カメラ位置の変化を検出: 差分率={diff_ratio:.2f}")
            return True

    return False
```

## パフォーマンス監視

### リソース使用量の監視

```python
import psutil

class PerformanceMonitor:
    def __init__(self):
        self.start_time = time.time()
        self.frame_count = 0

    def log_performance_stats(self):
        """パフォーマンス統計をログ出力"""
        # CPU使用率
        cpu_percent = psutil.cpu_percent(interval=1)

        # メモリ使用量
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # CPU温度（Raspberry Pi固有）
        try:
            temp_output = subprocess.check_output(['vcgencmd', 'measure_temp']).decode()
            cpu_temp = float(temp_output.split('=')[1].split('°')[0])
        except:
            cpu_temp = 0.0

        # FPS計算
        elapsed_time = time.time() - self.start_time
        current_fps = self.frame_count / elapsed_time if elapsed_time > 0 else 0

        self.logger.info(f"Performance - CPU: {cpu_percent}%, Memory: {memory_percent}%, Temp: {cpu_temp}°C, FPS: {current_fps:.1f}")

        # 異常値の検出
        if cpu_temp > 75:
            self.logger.warning(f"高温警告: CPU温度 {cpu_temp}°C")

        if memory_percent > 80:
            self.logger.warning(f"メモリ使用量警告: {memory_percent}%")
```

## 運用のベストプラクティス

### 1. 定期メンテナンス

```bash
#!/bin/bash
# maintenance.sh - 定期メンテナンススクリプト

echo "=== 定期メンテナンス開始 ==="

# システム更新
sudo apt update && sudo apt upgrade -y

# ログのクリーンアップ
find /home/pi/lamp-monitor/logs -name "*.log.*" -mtime +30 -delete

# 設定ファイルのバックアップ
cp /home/pi/lamp-monitor/config.yaml /home/pi/lamp-monitor/config.yaml.backup.$(date +%Y%m%d)

# システム状態の確認
systemctl status lamp-monitor.service
df -h
free -h
vcgencmd measure_temp

echo "=== 定期メンテナンス完了 ==="
```

### 2. 障害対応手順

```bash
# 緊急時の対応手順

# 1. サービス状態の確認
sudo systemctl status lamp-monitor.service

# 2. ログの確認
sudo journalctl -u lamp-monitor.service --since "1 hour ago"

# 3. リソース使用量の確認
top
free -h
df -h

# 4. カメラデバイスの確認
ls -la /dev/video*
lsusb

# 5. サービスの再起動
sudo systemctl restart lamp-monitor.service

# 6. 手動実行によるデバッグ
cd /home/pi/lamp-monitor
python3 monitor_webcam-pi.py
```

### 3. 設定管理

```python
# config_manager.py - 設定管理ユーティリティ

import yaml
import shutil
from datetime import datetime

class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path

    def backup_config(self):
        """設定ファイルのバックアップ"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{self.config_path}.backup.{timestamp}"
        shutil.copy2(self.config_path, backup_path)
        print(f"設定ファイルをバックアップしました: {backup_path}")

    def validate_config(self) -> bool:
        """設定ファイルの妥当性チェック"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 必須項目のチェック
            required_keys = ['camera', 'notify', 'logic', 'rois']
            for key in required_keys:
                if key not in config:
                    print(f"必須項目が不足しています: {key}")
                    return False

            # ROI設定のチェック
            for i in range(1, 13):
                roi_key = f"lamp_{i}"
                if roi_key not in config['rois']:
                    print(f"ROI設定が不足しています: {roi_key}")
                    return False

            print("設定ファイルの妥当性チェックが完了しました")
            return True

        except Exception as e:
            print(f"設定ファイルの読み込みエラー: {e}")
            return False
```

## まとめ

Raspberry Pi 5 への移植により、制御盤ランプ監視システムを実用的な産業用システムとして完成させることができました。特に重要だった点は：

### 技術的成果

1. **アーキテクチャ移植の成功**: x86_64 から ARM64 への円滑な移植
2. **パフォーマンス最適化**: 限られたリソースでの安定動作
3. **常駐サービス化**: systemd による自動起動・監視
4. **運用監視の実装**: ログ管理・パフォーマンス監視・障害対応

### 運用面での成果

1. **高い可用性**: 自動復旧機能による 24/7 運用
2. **セキュリティ対策**: ファイアウォール・自動更新・SSH 強化
3. **保守性の向上**: 構造化されたログ・設定管理・メンテナンス手順
4. **拡張性の確保**: 将来的な機能追加に対応可能な設計

### 開発プロセスの振り返り

三段階開発アプローチの有効性が実証されました：

1. **合成ダッシュボード**: 制御された環境でのロジック完成
2. **Web カメラ実験**: 実環境での課題発見と対策
3. **Raspberry Pi 移植**: 実用システムとしての完成

この段階的アプローチにより、各段階で発見された課題を次の段階で解決し、最終的に堅牢なシステムを構築できました。

### 今後の展望

現在のシステムをベースに、以下の拡張が可能です：

- **マルチカメラ対応**: 複数の制御盤の同時監視
- **AI による学習機能**: 環境変化への自動適応
- **Web ダッシュボード**: リアルタイム状態監視 UI
- **予防保全機能**: 異常の予兆検出

制御盤ランプ監視システムの開発を通じて、段階的開発アプローチの重要性と、実用システム構築における運用面の考慮の重要性を学ぶことができました。

---

_本記事は制御盤ランプ監視システム開発記の最終回です。三段階の開発プロセスを通じて、実用的な監視システムを構築することができました。_
