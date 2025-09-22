# 制御盤ランプ監視システム開発記 (1) - 合成ダッシュボードでロジック検証

## はじめに

制御盤の 12 個のランプ（正常=緑／異常=赤）をカメラで監視し、異常を検出したら Discord Webhook に通知するシステムを開発しました。本記事では、開発の第一段階である「合成ダッシュボードでロジック検証」について詳しく解説します。

## プロジェクト概要

このプロジェクトは三段階の開発アプローチを採用しています：

1. **合成ダッシュボードでロジック検証** ← 本記事
2. **Web カメラで実験**
3. **Raspberry Pi 5 への移植**

段階的開発により、実機環境に依存せずにロジックを完成させ、後の移植を容易にすることが狙いです。

## 技術スタック

- **言語**: Python 3.11
- **画像処理**: OpenCV
- **設定管理**: PyYAML
- **通知**: Cloudflare Workers + Discord Webhook
- **セキュリティ**: HMAC 署名による認証

## 合成ダッシュボードの設計思想

### なぜ合成ダッシュボードから始めるのか？

実機での開発には以下の課題があります：

- 制御盤の物理的な制約（常時アクセス困難）
- 照明条件の変動
- ランプ状態の制御困難
- デバッグ時の状況再現性の低さ

合成ダッシュボードを使用することで、これらの課題を解決し、**制御された環境でロジックを完成**させることができます。

### アーキテクチャ設計

システムは以下の 2 つのプロセスで構成されています：

```
┌─────────────────────┐    ┌─────────────────────┐
│  sim_dashboard.py   │    │ monitor_synthetic.py│
│  (合成ダッシュボード)  │    │   (監視・判定)      │
│                     │    │                     │
│ ・12個のランプ表示   │    │ ・フレーム取得      │
│ ・キーボード操作     │    │ ・色判定ロジック    │
│ ・状態変更          │    │ ・通知処理          │
└─────────────────────┘    └─────────────────────┘
```

この分離設計により、**入力部分（フレーム取得）と処理部分（判定・通知）を独立**させ、後の Web カメラや Raspberry Pi 移植時に処理部分をそのまま流用できます。

## 合成ダッシュボードの実装詳細

### 1. 動的レイアウト対応

```python
def get_dynamic_sizes(self):
    """現在のウィンドウサイズに基づいて動的サイズを計算"""
    scale_x = self.current_window_size[0] / self.default_window_size[0]
    scale_y = self.current_window_size[1] / self.default_window_size[1]
    scale = min(scale_x, scale_y)  # アスペクト比を保持

    lamp_w = int(self.default_lamp_size[0] * scale)
    lamp_h = int(self.default_lamp_size[1] * scale)

    return (lamp_w, lamp_h), margin_x, margin_y, spacing_x, spacing_y
```

ウィンドウサイズの変更に対応し、ランプサイズやレイアウトを動的に調整します。これにより、様々な解像度での検証が可能になります。

### 2. 豊富な操作機能

| キー | 機能                   | 用途             |
| ---- | ---------------------- | ---------------- |
| 1-0  | ランプ 1-10 のトグル   | 個別ランプテスト |
| -, = | ランプ 11, 12 のトグル | 全ランプテスト   |
| g    | 全て緑                 | 正常状態の確認   |
| r    | 全て赤                 | 異常状態の確認   |
| b    | 一部点滅               | 点滅対応テスト   |
| a    | ランダム赤             | 複数異常の検証   |
| s    | 画像保存               | デバッグ用       |

### 3. 点滅機能の実装

```python
def draw_lamp(self, frame: np.ndarray, lamp_id: int, state: str, is_blinking: bool = False):
    """ランプを描画"""
    # 点滅処理
    if is_blinking and not self.blink_on:
        color = self.bg_color  # 背景色で非表示
    else:
        if state == "RED":
            color = (0, 0, 255)  # BGR: 赤
        elif state == "GREEN":
            color = (0, 255, 0)  # BGR: 緑
        else:
            color = (128, 128, 128)  # BGR: 灰色
```

実際の制御盤でよく見られる点滅パターンに対応し、0.5 秒間隔での点滅を実装しています。

## 監視・判定ロジックの実装

### 1. HSV 色空間による色判定

RGB 色空間は照明変化に敏感なため、HSV 色空間を採用しました：

```python
def analyze_color(self, roi: np.ndarray) -> Tuple[str, float]:
    """ROI内の色を分析してランプ状態を判定"""
    # HSVに変換
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    # 明度フィルタ
    min_brightness = self.logic_config["min_brightness_v"]
    bright_mask = hsv[:, :, 2] >= min_brightness

    if not np.any(bright_mask):
        return "UNKNOWN", 0.0

    # 赤色判定
    red_ratio = self.calculate_red_ratio(hsv, bright_mask)
    if red_ratio >= self.logic_config["red_ratio_thresh"]:
        return "RED", red_ratio

    # 緑色判定
    green_ratio = self.calculate_green_ratio(hsv, bright_mask)
    if green_ratio >= self.logic_config["green_ratio_thresh"]:
        return "GREEN", green_ratio

    return "UNKNOWN", 0.0
```

### 2. 多層防御による誤検知対策

#### a) 明度フィルタ

```python
bright_mask = hsv[:, :, 2] >= min_brightness
```

暗部ノイズを除外し、十分な明度を持つ領域のみを判定対象とします。

#### b) 形態学的処理

```python
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
red_mask = cv2.morphologyEx(red_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
```

ノイズ除去により、小さな誤検知を排除します。

#### c) 多数決フィルタ

```python
def update_lamp_status(self, lamp_id: int, state: str, confidence: float):
    """ランプ状態を更新（多数決フィルタ適用）"""
    self.lamp_history[lamp_id].append((state, confidence))

    if len(self.lamp_history[lamp_id]) >= self.logic_config["frames_window"]:
        states = [item[0] for item in self.lamp_history[lamp_id]]
        state_counts = {s: states.count(s) for s in set(states)}
        final_state = max(state_counts, key=state_counts.get)
```

複数フレームの判定結果から多数決で最終状態を決定し、一時的な誤検知を排除します。

### 3. 設定駆動型アーキテクチャ

すべての閾値とパラメータを`config.yaml`で管理：

```yaml
logic:
  # HSV色域閾値
  red_hue_range: [[0, 10], [170, 180]] # 赤色相範囲
  red_sat_min: 100 # 赤彩度最小値
  red_val_min: 50 # 赤明度最小値

  # 判定閾値
  red_ratio_thresh: 0.3 # 赤判定の面積比閾値
  green_ratio_thresh: 0.3 # 緑判定の面積比閾値

  # 多数決フィルタ
  frames_window: 5 # 判定窓フレーム数
```

これにより、環境に応じた細かなチューニングが可能になります。

## セキュリティ実装

### HMAC 署名による認証

```python
def create_signature(self, data: Dict) -> str:
    """HMAC署名を作成"""
    secret = self.notify_config["secret"].encode('utf-8')
    message = json.dumps(data, sort_keys=True).encode('utf-8')
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"sha256={signature}"
```

通知データに HMAC-SHA256 署名を付与し、Cloudflare Workers 側で検証することで、不正な通知を防止します。

### 通知間隔制御

```python
# 通知間隔チェック
if current_time - last_notification < min_interval:
    print(f"ランプ {lamp_id}: 通知間隔が短いためスキップ")
    return
```

同一ランプの連続通知を制御し、Discord スパムを防止します。

## 検証結果と学び

### 1. 成功した点

- **制御された環境での完全なロジック検証**
- **様々な異常パターンの再現と対応確認**
- **誤検知対策の有効性確認**
- **設定パラメータの最適化**

### 2. 発見した課題

- **フレーム取得の実装簡略化**（実際の運用では共有メモリやウィンドウキャプチャが必要）
- **点滅パターンの多様性**（実機では様々な点滅パターンが存在）

### 3. 次段階への準備

合成ダッシュボードでの検証により、以下が確立されました：

- 色判定アルゴリズムの完成
- 誤検知対策の実装
- 通知システムの動作確認
- 設定パラメータの基準値

これらの成果により、次段階の Web カメラ実験に自信を持って進むことができます。

## まとめ

合成ダッシュボードを使用したロジック検証により、実機環境に依存せずに堅牢な監視システムを構築できました。特に以下の点が重要でした：

1. **段階的開発アプローチ**の有効性
2. **I/O 分離設計**による移植性の確保
3. **多層防御**による誤検知対策
4. **設定駆動型**による柔軟性の実現

次回の記事では、このロジックを実際の Web カメラに適用し、実環境での課題と対策について詳しく解説します。

---

_本記事は制御盤ランプ監視システム開発記の第 1 回です。次回「Web カメラで実験」もお楽しみに！_
