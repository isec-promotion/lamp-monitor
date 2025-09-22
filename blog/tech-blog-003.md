# 制御盤ランプ監視システム開発記 (2) - Web カメラで実験

## はじめに

前回の記事では、合成ダッシュボードを使用してランプ監視システムのロジックを検証しました。今回は、開発の第二段階である「Web カメラで実験」について詳しく解説します。実環境での課題と、それに対する技術的な解決策を中心にお話しします。

## 実環境移行の課題

合成ダッシュボードから実際の Web カメラに移行する際、以下の課題が浮上しました：

### 1. カメラ初期化の複雑さ

Windows 環境でのカメラアクセスは、デバイスドライバーやバックエンドの違いにより不安定になることがあります。

### 2. 照明条件の変動

実環境では以下の要因により、色判定が困難になります：

- 自然光の変化（時間帯による影響）
- 人工照明の種類（蛍光灯、LED など）
- 反射や影の影響
- カメラの自動露出・ホワイトバランス

### 3. 誤検知の増加

実環境では合成環境では発生しない様々なノイズが発生します：

- カメラセンサーのノイズ
- 圧縮アーティファクト
- 微細な振動による画像ブレ
- 周辺環境の映り込み

## 高速化版の実装

実環境での安定動作を実現するため、`monitor_webcam.py`を高速化版として再設計しました。

### 1. 遅延初期化による起動時間短縮

```python
class LampDetector:
    def __init__(self, config: Dict):
        """初期化（設定を直接受け取り）"""
        self.config = config

        # 遅延初期化用フラグ
        self._initialized = False
        self.lamp_history = None
        self.lamp_statuses = None

        print("ランプ検出システムを初期化しました（遅延初期化モード）")

    def _lazy_init(self):
        """遅延初期化 - 最初のフレーム処理時に実行"""
        if not self._initialized:
            self.lamp_history = {i: deque(maxlen=self.logic_config["frames_window"])
                               for i in range(1, 13)}
            self.lamp_statuses = {i: LampStatus(i, "UNKNOWN", 0.0) for i in range(1, 13)}
            self._initialized = True
```

重い初期化処理を実際に必要になるまで遅延させることで、起動時間を大幅に短縮しました。

### 2. カメラ初期化の最適化

```python
def initialize_camera_fast(self) -> bool:
    """カメラを高速初期化（最適化版）"""
    device_id = self.camera_config["device_id"]

    try:
        # DSHOWバックエンドを優先（Windowsで最も安定）
        self.cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)

        if self.cap.isOpened():
            print("カメラ初期化成功 (DSHOW)")
        else:
            print("DSHOW失敗、デフォルトを試行中...")
            self.cap.release()
            self.cap = cv2.VideoCapture(device_id)

            if not self.cap.isOpened():
                print("カメラ初期化失敗")
                return False
            print("カメラ初期化成功 (デフォルト)")

        # 基本設定のみ適用（高速化のため）
        width, height = self.camera_config["size"]
        fps = self.camera_config["fps"]

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 遅延削減

        return True

    except Exception as e:
        print(f"カメラ初期化エラー: {e}")
        return False
```

Windows で最も安定している DSHOW バックエンドを優先し、フォールバック機能も実装しました。

## 誤検知対策の強化

実環境での誤検知を防ぐため、多層防御を強化しました。

### 1. 多数決の閾値強化

```python
def update_lamp_status(self, lamp_id: int, state: str, confidence: float):
    """ランプ状態を更新（多数決フィルタ適用）- 誤検知対策強化版"""
    # 履歴に追加
    self.lamp_history[lamp_id].append((state, confidence))

    if len(self.lamp_history[lamp_id]) >= self.logic_config["frames_window"]:
        states = [item[0] for item in self.lamp_history[lamp_id]]
        state_counts = {s: states.count(s) for s in set(states)}
        final_state = max(state_counts, key=state_counts.get)

        # 誤検知対策1: 多数決の閾値チェック
        total_frames = len(self.lamp_history[lamp_id])
        majority_count = state_counts[final_state]
        majority_ratio = majority_count / total_frames

        # 過半数を超えない場合はUNKNOWNとする
        if majority_ratio < 0.6:  # 60%以上の合意が必要
            final_state = "UNKNOWN"
            final_confidence = 0.0
        else:
            # 信頼度は平均値
            confidences = [item[1] for item in self.lamp_history[lamp_id] if item[0] == final_state]
            final_confidence = np.mean(confidences) if confidences else 0.0

            # 誤検知対策2: 信頼度の最小閾値チェック
            min_confidence_thresh = 0.4  # 最小信頼度閾値
            if final_confidence < min_confidence_thresh:
                final_state = "UNKNOWN"
                final_confidence = 0.0
```

単純な多数決から、**合意率 60% 以上**と**最小信頼度 0.4 以上**の二重チェックに強化しました。

### 2. バッチ通知システム

実環境では複数のランプが同時に異常になることが多いため、バッチ通知システムを実装しました。

```python
def add_to_batch_notification(self, lamp_id: int, state: str, confidence: float):
    """バッチ通知に追加（改善版：すべてのランプをまとめて通知）"""
    current_time = time.time()

    # 最初の赤色検出時刻を記録
    if self.first_red_detection_time is None:
        self.first_red_detection_time = current_time
        print(f"最初の赤色検出: ランプ {lamp_id} (収集期間開始)")

    # 既に同じランプがバッチに含まれているかチェック
    for notification in self.pending_notifications:
        if notification["lamp_id"] == lamp_id:
            # 既存の通知を更新
            notification["confidence"] = confidence
            notification["timestamp"] = int(current_time)
            print(f"ランプ {lamp_id}: バッチ通知を更新")
            return

    # 新しい通知をバッチに追加
    notification_data = {
        "lamp_id": lamp_id,
        "state": state,
        "confidence": confidence,
        "timestamp": int(current_time)
    }
    self.pending_notifications.append(notification_data)
    print(f"ランプ {lamp_id}: バッチ通知に追加 (バッチサイズ: {len(self.pending_notifications)})")
```

### 3. 収集期間ベースの通知

```python
def check_and_send_batch_notification(self):
    """バッチ通知の送信チェック（改善版：収集期間ベース）"""
    current_time = time.time()

    # バッチが空の場合は何もしない
    if not self.pending_notifications:
        self.first_red_detection_time = None
        return

    # 最初の赤色検出から収集期間が経過したかチェック
    if (self.first_red_detection_time is not None and
        current_time - self.first_red_detection_time >= self.batch_collection_window):
        print(f"収集期間終了 ({self.batch_collection_window}秒経過) - バッチ通知送信")
        self.send_batch_notification()
        self.first_red_detection_time = None
```

最初の異常検出から 2 秒間の収集期間を設け、その間に検出されたすべての異常をまとめて通知します。

## デバッグ機能の充実

実環境でのトラブルシューティングを支援するため、豊富なデバッグ機能を実装しました。

### 1. リアルタイム状態表示

```python
def draw_debug_overlay(self, frame: np.ndarray) -> np.ndarray:
    """デバッグ用のオーバーレイを描画"""
    overlay_frame = frame.copy()

    # ROI矩形を描画
    for lamp_id in range(1, 13):
        roi_key = f"lamp_{lamp_id}"
        if roi_key in self.rois:
            x, y, w, h = self.rois[roi_key]

            # ランプ状態に応じて色を変更
            status = self.lamp_statuses[lamp_id]
            if status.state == "RED":
                color = (0, 0, 255)  # 赤
            elif status.state == "GREEN":
                color = (0, 255, 0)  # 緑
            else:
                color = (128, 128, 128)  # 灰色

            # ROI矩形を描画
            cv2.rectangle(overlay_frame, (x, y), (x + w, y + h), color, 2)

            # ランプ番号と状態を描画
            text = f"L{lamp_id}: {status.state}"
            cv2.putText(overlay_frame, text, (x, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return overlay_frame
```

各ランプの ROI 領域と現在の判定状態をリアルタイムで表示します。

### 2. 統計情報とキーボード操作

```python
# フレーム情報を描画
frame_count += 1
elapsed_time = time.time() - start_time
current_fps = frame_count / elapsed_time if elapsed_time > 0 else 0

info_text = f"Frame: {frame_count}, FPS: {current_fps:.1f} [FAST MODE]"
cv2.putText(display_frame, info_text, (10, 30),
           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

# 操作説明を描画
instructions = [
    "Press 'q' or ESC to quit",
    "Press 's' to save current frame",
    "Press 'r' to reset lamp history",
    "Click X button to close window"
]
```

フレームレート、処理フレーム数、操作方法を画面に表示し、運用時の状況把握を支援します。

## ROI 設定ツールとの連携

実環境では、カメラの設置位置や角度により ROI（関心領域）の調整が必要です。

### ROI 設定の重要性

```yaml
# config.yaml - ROI設定例
rois:
  lamp_1: [80, 80, 240, 120] # [x, y, width, height]
  lamp_2: [380, 80, 240, 120]
  # ... 12個のランプすべて
```

各ランプの位置を正確に設定することで、以下の効果があります：

- **誤検知の削減**: 不要な領域を除外
- **処理速度の向上**: 必要最小限の領域のみ処理
- **精度の向上**: ランプ以外の要素の影響を排除

### ROI 設定のベストプラクティス

1. **ランプより少し小さめに設定**: 反射や周辺光を除外
2. **均等な大きさに統一**: 判定条件の一貫性を保持
3. **重複を避ける**: 隣接ランプとの干渉を防止

## 実環境での運用知見

### 1. カメラ設定の重要性

```python
# 推奨設定
self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
self.cap.set(cv2.CAP_PROP_FPS, 20)
self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 遅延削減

# 重要: 自動調整を無効化（可能であれば）
# self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 手動露出
# self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)           # 手動ホワイトバランス
```

自動露出やホワイトバランスは色判定に悪影響を与えるため、可能な限り手動設定を推奨します。

### 2. 照明環境の安定化

- **一定の照明条件**: 蛍光灯や LED の安定した照明を使用
- **直射日光の回避**: 窓からの自然光は時間により変化
- **反射の最小化**: 光沢のある表面からの反射を避ける

### 3. 設定パラメータのチューニング

実環境に応じて以下のパラメータを調整：

```yaml
logic:
  red_ratio_thresh: 0.3 # 環境に応じて 0.2-0.5 で調整
  green_ratio_thresh: 0.3 # 環境に応じて 0.2-0.5 で調整
  min_brightness_v: 30 # 暗い環境では下げる
  frames_window: 5 # 安定性重視なら 7-10 に増加
```

## パフォーマンス最適化

### 1. フレーム処理の最適化

- **バッファサイズの最小化**: 遅延を削減
- **不要な処理の削減**: デバッグ表示の条件分岐
- **メモリ使用量の最適化**: 大きな配列の再利用

### 2. 通知処理の最適化

- **バッチ処理**: 複数の異常をまとめて通知
- **非同期処理**: 通知送信をメインループから分離（将来の改善点）
- **エラーハンドリング**: ネットワーク障害時の再試行機能

## トラブルシューティング

### よくある問題と対策

1. **カメラが認識されない**

   - デバイス ID の確認
   - 他のアプリケーションによる占有チェック
   - ドライバーの更新

2. **色判定が不安定**

   - ROI 設定の見直し
   - 照明条件の確認
   - 閾値パラメータの調整

3. **通知が送信されない**
   - ネットワーク接続の確認
   - Cloudflare Workers の URL 確認
   - HMAC 署名の検証

## 次段階への準備

Web カメラでの実験により、以下の知見を得ました：

### 成功した改善点

- **高速化による安定動作**
- **強化された誤検知対策**
- **実用的なデバッグ機能**
- **バッチ通知による運用効率向上**

### Raspberry Pi 移植への準備

- **picamera2 ライブラリへの対応準備**
- **ARM アーキテクチャでの最適化検討**
- **systemd による常駐サービス化の設計**

## まとめ

Web カメラを使用した実環境実験により、合成ダッシュボードで構築したロジックを実用レベルまで昇華させることができました。特に重要だった点は：

1. **実環境特有の課題への対応**
2. **多層防御による誤検知対策の強化**
3. **運用を意識したデバッグ機能の充実**
4. **バッチ通知による実用性の向上**

次回の最終記事では、このシステムを Raspberry Pi 5 に移植し、実際の制御盤監視システムとして完成させる過程を詳しく解説します。

---

_本記事は制御盤ランプ監視システム開発記の第 2 回です。次回「Raspberry Pi 5 への移植」もお楽しみに！_
