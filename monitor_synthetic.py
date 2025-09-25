#!/usr/bin/env python3
"""
疑似ランプ監視・通知テスター
------------------------------------------------------------
■ 背景
12個のLEDランプが並ぶ制御盤において、ランプが「緑 → 赤」に変化したら
異常としてDiscordへ通知したい。通知は Cloudflare Workers を経由して送信する。

■ 本プログラムの目的
本番ではウェブカメラで制御盤ランプの色変化を検知する予定だが、その前段階として
「映像なし・疑似的な色変化」で通知フローが正しく動作するかを確認するための
動作確認用（テスト）プログラムである。

■ 概要
- ダッシュボードを生成し、各ランプ領域の色を解析
- ランプ状態が緑から赤になったと判定された場合のみ通知イベントを発火
- 通知はHMAC署名付きのJSONをCloudflare WorkersへPOSTし、WorkersからDiscordへ中継

■ 想定ユースケース
- 通知ロジック／閾値／間隔などの手元検証
- Cloudflare Workers 側の署名検証・Discord転送の結線確認
- 本番カメラ連携前のエンドツーエンド動作確認

■ 注意
- 本プログラムは疑似データで動作するため、実カメラ映像の品質や環境光の影響は考慮しない
- 本番導入時は実カメラのキャプチャ実装に差し替えること
"""

import cv2
import numpy as np
import yaml
import time
import requests
import hashlib
import hmac
import json
from collections import deque
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

@dataclass
class LampStatus:
    """ランプ状態を表すデータクラス"""
    lamp_id: int
    state: str  # "RED", "GREEN", "UNKNOWN"
    confidence: float
    last_notification: float = 0.0

class LampDetector:
    """ランプ検出・判定クラス"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        self.config = self.load_config(config_path)
        self.lamp_history = {i: deque(maxlen=self.config["logic"]["frames_window"]) 
                           for i in range(1, 13)}
        self.lamp_statuses = {i: LampStatus(i, "UNKNOWN", 0.0) for i in range(1, 13)}
        
        # 設定値の取得
        self.logic_config = self.config["logic"]
        self.notify_config = self.config["notify"]
        self.rois = self.config["rois"]
        
        print("ランプ検出システムを初期化しました")
        print(f"フレーム窓サイズ: {self.logic_config['frames_window']}")
        print(f"通知間隔: {self.notify_config['min_interval_sec']}秒")
    
    def load_config(self, config_path: str) -> Dict:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"設定ファイル {config_path} が見つかりません")
            raise
        except yaml.YAMLError as e:
            print(f"設定ファイルの読み込みエラー: {e}")
            raise
    
    def extract_roi(self, frame: np.ndarray, lamp_id: int) -> Optional[np.ndarray]:
        """ROI領域を抽出"""
        roi_key = f"lamp_{lamp_id}"
        if roi_key not in self.rois:
            return None
        
        x, y, w, h = self.rois[roi_key]
        if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
            return None
        
        return frame[y:y+h, x:x+w]
    
    def analyze_color(self, roi: np.ndarray) -> Tuple[str, float]:
        """ROI内の色を分析してランプ状態を判定"""
        if roi is None or roi.size == 0:
            return "UNKNOWN", 0.0
        
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
    
    def calculate_red_ratio(self, hsv: np.ndarray, bright_mask: np.ndarray) -> float:
        """赤色の面積比を計算"""
        red_hue_ranges = self.logic_config["red_hue_range"]
        red_sat_min = self.logic_config["red_sat_min"]
        red_val_min = self.logic_config["red_val_min"]
        
        red_mask = np.zeros(hsv.shape[:2], dtype=bool)
        
        # 赤色相は0-10と170-180の2つの範囲
        for hue_range in red_hue_ranges:
            hue_min, hue_max = hue_range
            hue_mask = (hsv[:, :, 0] >= hue_min) & (hsv[:, :, 0] <= hue_max)
            sat_mask = hsv[:, :, 1] >= red_sat_min
            val_mask = hsv[:, :, 2] >= red_val_min
            
            red_mask |= hue_mask & sat_mask & val_mask
        
        red_mask &= bright_mask
        
        # 形態学的処理でノイズ除去
        kernel_size = self.logic_config["morphological_kernel"]
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        red_mask = cv2.morphologyEx(red_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        
        total_pixels = np.sum(bright_mask)
        red_pixels = np.sum(red_mask)
        
        return red_pixels / total_pixels if total_pixels > 0 else 0.0
    
    def calculate_green_ratio(self, hsv: np.ndarray, bright_mask: np.ndarray) -> float:
        """緑色の面積比を計算"""
        green_hue_range = self.logic_config["green_hue_range"]
        green_sat_min = self.logic_config["green_sat_min"]
        green_val_min = self.logic_config["green_val_min"]
        
        hue_min, hue_max = green_hue_range
        hue_mask = (hsv[:, :, 0] >= hue_min) & (hsv[:, :, 0] <= hue_max)
        sat_mask = hsv[:, :, 1] >= green_sat_min
        val_mask = hsv[:, :, 2] >= green_val_min
        
        green_mask = hue_mask & sat_mask & val_mask & bright_mask
        
        # 形態学的処理でノイズ除去
        kernel_size = self.logic_config["morphological_kernel"]
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        green_mask = cv2.morphologyEx(green_mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
        
        total_pixels = np.sum(bright_mask)
        green_pixels = np.sum(green_mask)
        
        return green_pixels / total_pixels if total_pixels > 0 else 0.0
    
    def update_lamp_status(self, lamp_id: int, state: str, confidence: float):
        """ランプ状態を更新（多数決フィルタ適用）"""
        # 履歴に追加
        self.lamp_history[lamp_id].append((state, confidence))
        
        # 多数決で最終状態を決定
        if len(self.lamp_history[lamp_id]) >= self.logic_config["frames_window"]:
            states = [item[0] for item in self.lamp_history[lamp_id]]
            state_counts = {s: states.count(s) for s in set(states)}
            final_state = max(state_counts, key=state_counts.get)
            
            # 信頼度は平均値
            confidences = [item[1] for item in self.lamp_history[lamp_id] if item[0] == final_state]
            final_confidence = np.mean(confidences) if confidences else 0.0
            
            # 状態が変化した場合のみ更新
            if self.lamp_statuses[lamp_id].state != final_state:
                old_state = self.lamp_statuses[lamp_id].state
                self.lamp_statuses[lamp_id].state = final_state
                self.lamp_statuses[lamp_id].confidence = final_confidence
                
                print(f"ランプ {lamp_id}: {old_state} → {final_state} (信頼度: {final_confidence:.2f})")
                
                # 赤色検出時は通知
                if final_state == "RED":
                    self.send_notification(lamp_id, final_state, final_confidence)
    
    def send_notification(self, lamp_id: int, state: str, confidence: float):
        """Cloudflare Workersに通知を送信"""
        current_time = time.time()
        last_notification = self.lamp_statuses[lamp_id].last_notification
        min_interval = self.notify_config["min_interval_sec"]
        
        # 通知間隔チェック
        if current_time - last_notification < min_interval:
            print(f"ランプ {lamp_id}: 通知間隔が短いためスキップ ({current_time - last_notification:.1f}秒)")
            return
        
        # 通知データ作成
        notification_data = {
            "timestamp": int(current_time),
            "lamp_id": lamp_id,
            "state": state,
            "confidence": float(confidence),
            "message": f"ランプ {lamp_id} が {state} 状態になりました",
        }

        # ★ 署名を生成
        signature = self.create_signature(notification_data)
    
        # ★ ヘッダーに署名を追加
        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": signature  # 署名をヘッダーに追加
        }
        
        try:
            request_url = self.notify_config["worker_url"]
            # dumpsを使用してデータをJSON文字列に変換
            data_payload = json.dumps(notification_data, sort_keys=True)
            
            print(f"通知送信先URL: {request_url}")
            print(f"通知データ: {data_payload}")
            print(f"ヘッダー: {headers}")

            response = requests.post(
                request_url,
                data=data_payload.encode('utf-8'), # data引数でバイトとして送信
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"ランプ {lamp_id}: 通知送信成功")
                self.lamp_statuses[lamp_id].last_notification = current_time
            else:
                print(f"ランプ {lamp_id}: 通知送信失敗 (HTTP {response.status_code}) - {response.text}")
                
        except requests.RequestException as e:
            print(f"ランプ {lamp_id}: 通知送信エラー - {e}")
    
    def create_signature(self, data: Dict) -> str:
        """HMAC署名を作成"""
        secret = self.notify_config["secret"].encode('utf-8')
        # ★ requestsで送るペイロードと完全に同じものから署名を生成
        message = json.dumps(data, sort_keys=True).encode('utf-8')
        signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
        return f"sha256={signature}"
    
    def process_frame(self, frame: np.ndarray):
        """フレームを処理してランプ状態を判定"""
        for lamp_id in range(1, 13):
            roi = self.extract_roi(frame, lamp_id)
            if roi is not None:
                state, confidence = self.analyze_color(roi)
                self.update_lamp_status(lamp_id, state, confidence)

class SyntheticMonitor:
    """合成フレーム監視システム"""
    
    def __init__(self):
        """初期化"""
        self.detector = LampDetector()
        self.running = False
        
    def create_test_frame(self) -> np.ndarray:
        """テスト用のフレームを生成"""
        # 疑似ダッシュボードと同じサイズのフレームを作成
        window_size = self.detector.config["synthetic"]["window_size"]
        frame = np.full((window_size[1], window_size[0], 3), (50, 50, 50), dtype=np.uint8)
        
        # 現在時刻に基づいてランプ状態を変化させる（テスト用）
        current_time = time.time()
        
        for lamp_id in range(1, 13):
            roi_key = f"lamp_{lamp_id}"
            if roi_key in self.detector.rois:
                x, y, w, h = self.detector.rois[roi_key]
                
                # 時間に基づいてランプ状態を決定（デモ用）
                # ランプ1は10秒ごとに赤/緑を切り替え
                if lamp_id == 1:
                    if int(current_time / 10) % 2 == 0:
                        color = (0, 255, 0)  # 緑
                    else:
                        color = (0, 0, 255)  # 赤
                # ランプ2は15秒ごとに赤/緑を切り替え
                elif lamp_id == 2:
                    if int(current_time / 15) % 2 == 0:
                        color = (0, 255, 0)  # 緑
                    else:
                        color = (0, 0, 255)  # 赤
                else:
                    color = (0, 255, 0)  # その他は緑
                
                # ランプを描画
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, -1)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 2)
                
                # ランプ番号を描画
                text = str(lamp_id)
                text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                text_x = x + (w - text_size[0]) // 2
                text_y = y + (h + text_size[1]) // 2
                cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        
        return frame
    
    def capture_synthetic_frame(self) -> Optional[np.ndarray]:
        """合成フレームを取得（テスト用実装）"""
        try:
            return self.create_test_frame()
        except Exception as e:
            print(f"フレーム生成エラー: {e}")
            return None
    
    def run(self):
        """監視システムを実行"""
        print("合成フレーム監視システムを開始します")
        print("注意: この実装では、実際のフレームキャプチャは簡略化されています")
        print("実際の運用では、ウィンドウキャプチャまたは共有メモリを使用してください")
        
        self.running = True
        frame_count = 0
        
        try:
            while self.running:
                # フレームキャプチャ（簡略化）
                frame = self.capture_synthetic_frame()
                
                if frame is not None:
                    # フレーム処理
                    self.detector.process_frame(frame)
                    frame_count += 1
                    
                    if frame_count % 100 == 0:
                        print(f"処理フレーム数: {frame_count}")
                
                # フレームレート制御
                time.sleep(1.0 / 20)  # 20 FPS
                
        except KeyboardInterrupt:
            print("\nキーボード割り込みで終了します")
        finally:
            self.running = False
            print("合成フレーム監視システムを終了しました")

def main():
    """メイン関数"""
    print("=== 合成フレーム監視システム ===")
    print("このシステムは疑似ダッシュボードと連携して動作します")
    print("先に sim_dashboard.py を起動してください")
    print()
    
    monitor = SyntheticMonitor()
    monitor.run()

if __name__ == "__main__":
    main()
