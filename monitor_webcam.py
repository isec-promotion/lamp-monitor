#!/usr/bin/env python3
"""
Webカメラ監視システム - Webカメラからフレームを取得し、ランプ状態を判定してCloudflare Workersに通知
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

class WebcamMonitor:
    """Webカメラ監視システム"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        self.config = self.load_config(config_path)
        self.detector = LampDetector(config_path)
        self.cap = None
        self.running = False
        
        # カメラ設定
        self.camera_config = self.config["camera"]
        
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
    
    def try_device_name_initialization(self):
        """デバイス名を使用してカメラを初期化"""
        # C922 Pro Stream Webcamの一般的なデバイス名パターン
        device_names = [
            "C922 Pro Stream Webcam",
            "Logitech C922 Pro Stream Webcam",
            "USB Camera",
            "Integrated Camera",
        ]
        
        for device_name in device_names:
            try:
                cap = cv2.VideoCapture(device_name, cv2.CAP_DSHOW)
                if cap.isOpened():
                    print(f"デバイス名 '{device_name}' で接続成功")
                    return cap
                cap.release()
            except:
                continue
        
        return None
    
    def initialize_camera(self) -> bool:
        """カメラを初期化（複数の方法を試行）"""
        device_id = self.camera_config["device_id"]
        
        # 複数のバックエンドと初期化方法を試行
        initialization_methods = [
            ("デフォルト", lambda: cv2.VideoCapture(device_id)),
            ("DSHOW", lambda: cv2.VideoCapture(device_id, cv2.CAP_DSHOW)),
            ("MSMF", lambda: cv2.VideoCapture(device_id, cv2.CAP_MSMF)),
            ("デバイス名指定", lambda: self.try_device_name_initialization()),
        ]
        
        for method_name, init_func in initialization_methods:
            print(f"カメラ初期化を試行中: {method_name}")
            try:
                self.cap = init_func()
                
                if self.cap is not None and self.cap.isOpened():
                    print(f"カメラ初期化成功: {method_name}")
                    break
                else:
                    print(f"カメラ初期化失敗: {method_name}")
                    if self.cap is not None:
                        self.cap.release()
                        self.cap = None
            except Exception as e:
                print(f"カメラ初期化エラー ({method_name}): {e}")
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
        
        if self.cap is None or not self.cap.isOpened():
            print("すべてのカメラ初期化方法が失敗しました")
            print("以下を確認してください:")
            print("1. カメラが正しく接続されているか")
            print("2. 他のアプリケーションがカメラを使用していないか")
            print("3. カメラドライバが正しくインストールされているか")
            print("4. Windowsのプライバシー設定でカメラアクセスが許可されているか")
            return False
            
        # カメラ設定を適用
        try:
            width, height = self.camera_config["size"]
            fps = self.camera_config["fps"]
            
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
            
            # バッファサイズを小さくして遅延を減らす
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # 実際の設定値を確認
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            print(f"カメラ設定完了:")
            print(f"  解像度: {actual_width}x{actual_height} (設定: {width}x{height})")
            print(f"  FPS: {actual_fps} (設定: {fps})")
            
            # テストフレームを取得
            print("テストフレーム取得中...")
            for i in range(3):
                ret, frame = self.cap.read()
                if ret:
                    print(f"  テストフレーム {i+1}: 成功 (サイズ: {frame.shape})")
                    break
                else:
                    print(f"  テストフレーム {i+1}: 失敗")
            
            if not ret:
                print("テストフレームの取得に失敗しました")
                return False
            
            # 露出・ゲイン設定の推奨
            print("\n重要: カメラの露出・ゲイン・ホワイトバランスを手動固定することを推奨します")
            print("自動調整により色域がぶれ、誤検知が増加する可能性があります")
            
            return True
            
        except Exception as e:
            print(f"カメラ設定エラー: {e}")
            return False
    
    def release_camera(self):
        """カメラを解放"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def run(self):
        """監視システムを実行"""
        print("Webカメラ監視システムを開始します")
        
        if not self.initialize_camera():
            print("カメラの初期化に失敗しました")
            return
        
        self.running = True
        frame_count = 0
        start_time = time.time()
        
        # ウィンドウ作成
        cv2.namedWindow("Webcam Monitor", cv2.WINDOW_AUTOSIZE)
        
        try:
            while self.running:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("フレームの取得に失敗しました")
                    break
                
                # フレーム処理
                self.detector.process_frame(frame)
                
                # デバッグ用オーバーレイを描画
                display_frame = self.detector.draw_debug_overlay(frame)
                
                # フレーム情報を描画
                frame_count += 1
                elapsed_time = time.time() - start_time
                current_fps = frame_count / elapsed_time if elapsed_time > 0 else 0
                
                info_text = f"Frame: {frame_count}, FPS: {current_fps:.1f}"
                cv2.putText(display_frame, info_text, (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
                # 操作説明を描画
                instructions = [
                    "Press 'q' to quit",
                    "Press 's' to save current frame",
                    "Press 'r' to reset lamp history"
                ]
                
                for i, instruction in enumerate(instructions):
                    y_pos = display_frame.shape[0] - 60 + i * 20
                    cv2.putText(display_frame, instruction, (10, y_pos), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                # フレーム表示
                cv2.imshow("Webcam Monitor", display_frame)
                
                # キー入力処理
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('s'):
                    self.save_frame(frame, frame_count)
                elif key == ord('r'):
                    self.reset_lamp_history()
                
                # 統計情報出力
                if frame_count % 100 == 0:
                    print(f"処理フレーム数: {frame_count}, FPS: {current_fps:.1f}")
                    self.print_lamp_status()
                
        except KeyboardInterrupt:
            print("\nキーボード割り込みで終了します")
        finally:
            self.running = False
            cv2.destroyAllWindows()
            self.release_camera()
            print("Webカメラ監視システムを終了しました")
    
    def save_frame(self, frame: np.ndarray, frame_count: int):
        """現在のフレームを保存"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"webcam_frame_{timestamp}_{frame_count:06d}.png"
        cv2.imwrite(filename, frame)
        print(f"フレームを保存しました: {filename}")
    
    def reset_lamp_history(self):
        """ランプ履歴をリセット"""
        for lamp_id in range(1, 13):
            self.detector.lamp_history[lamp_id].clear()
            self.detector.lamp_statuses[lamp_id].state = "UNKNOWN"
            self.detector.lamp_statuses[lamp_id].confidence = 0.0
        print("ランプ履歴をリセットしました")
    
    def print_lamp_status(self):
        """現在のランプ状態を出力"""
        print("\n=== 現在のランプ状態 ===")
        for lamp_id in range(1, 13):
            status = self.detector.lamp_statuses[lamp_id]
            print(f"ランプ {lamp_id:2d}: {status.state:7s} (信頼度: {status.confidence:.2f})")
        print("========================\n")

def main():
    """メイン関数"""
    print("=== Webカメラ監視システム ===")
    print("このシステムはWebカメラからランプを監視し、異常を検出します")
    print("事前にconfig.yamlでROI座標を設定してください")
    print("roi_tool.pyを使用してROIを設定することを推奨します")
    print()
    
    monitor = WebcamMonitor()
    monitor.run()

if __name__ == "__main__":
    main()
