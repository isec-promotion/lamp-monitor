#!/usr/bin/env python3
"""
Webカメラ監視システム（高速化版） - 起動時間を最適化
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
    """ランプ検出・判定クラス（高速化版）"""
    
    def __init__(self, config: Dict):
        """初期化（設定を直接受け取り）"""
        self.config = config
        
        # 遅延初期化用フラグ
        self._initialized = False
        self.lamp_history = None
        self.lamp_statuses = None
        
        # 設定値の取得
        self.logic_config = self.config["logic"]
        self.notify_config = self.config["notify"]
        self.rois = self.config["rois"]
        
        # 通知バッチ処理用
        self.pending_notifications = []
        self.last_batch_notification = 0.0
        self.batch_interval = 3.0  # 3秒間隔でバッチ通知（より長い待機時間）
        self.first_red_detection_time = None  # 最初の赤色検出時刻
        self.batch_collection_window = 2.0  # 赤色検出後の収集期間
        
        print("ランプ検出システムを初期化しました（遅延初期化モード）")
    
    def _lazy_init(self):
        """遅延初期化 - 最初のフレーム処理時に実行"""
        if not self._initialized:
            self.lamp_history = {i: deque(maxlen=self.logic_config["frames_window"]) 
                               for i in range(1, 13)}
            self.lamp_statuses = {i: LampStatus(i, "UNKNOWN", 0.0) for i in range(1, 13)}
            self._initialized = True
            print(f"遅延初期化完了 - フレーム窓サイズ: {self.logic_config['frames_window']}")
    
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
        """赤色の面積比を計算（元のロジックベース）"""
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
        """ランプ状態を更新（多数決フィルタ適用）- 誤検知対策強化版"""
        # 遅延初期化
        self._lazy_init()
        
        # 履歴に追加
        self.lamp_history[lamp_id].append((state, confidence))
        
        # 多数決で最終状態を決定
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
            
            # 状態が変化した場合のみ更新
            if self.lamp_statuses[lamp_id].state != final_state:
                old_state = self.lamp_statuses[lamp_id].state
                self.lamp_statuses[lamp_id].state = final_state
                self.lamp_statuses[lamp_id].confidence = final_confidence
                
                print(f"ランプ {lamp_id}: {old_state} → {final_state} (信頼度: {final_confidence:.2f}, 合意率: {majority_ratio:.2f})")
                
                # 赤色検出時はバッチ通知に追加
                if final_state == "RED":
                    self.add_to_batch_notification(lamp_id, final_state, final_confidence)
    
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

        # 署名を生成
        signature = self.create_signature(notification_data)
    
        # ヘッダーに署名を追加
        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": signature
        }
        
        try:
            request_url = self.notify_config["worker_url"]
            data_payload = json.dumps(notification_data, sort_keys=True)
            
            print(f"通知送信先URL: {request_url}")
            print(f"通知データ: {data_payload}")

            response = requests.post(
                request_url,
                data=data_payload.encode('utf-8'),
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
    
    def add_to_batch_notification(self, lamp_id: int, state: str, confidence: float):
        """バッチ通知に追加（改善版：すべてのランプをまとめて通知）"""
        current_time = time.time()
        last_notification = self.lamp_statuses[lamp_id].last_notification
        min_interval = self.notify_config["min_interval_sec"]
        
        # 通知間隔チェック
        if current_time - last_notification < min_interval:
            print(f"ランプ {lamp_id}: 通知間隔が短いためスキップ ({current_time - last_notification:.1f}秒)")
            return
        
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
        
        # 即座に送信せず、収集期間の終了を待つ
        # check_and_send_batch_notification()は定期的に呼び出される
    
    def check_and_send_batch_notification(self):
        """バッチ通知の送信チェック（改善版：収集期間ベース）"""
        current_time = time.time()
        
        # バッチが空の場合は何もしない
        if not self.pending_notifications:
            # 最初の検出時刻もリセット
            self.first_red_detection_time = None
            return
        
        # 最初の赤色検出から収集期間が経過したかチェック
        if (self.first_red_detection_time is not None and 
            current_time - self.first_red_detection_time >= self.batch_collection_window):
            print(f"収集期間終了 ({self.batch_collection_window}秒経過) - バッチ通知送信")
            self.send_batch_notification()
            # 最初の検出時刻をリセット
            self.first_red_detection_time = None
        
        # 従来のバッチ間隔チェックも維持（フォールバック）
        elif current_time - self.last_batch_notification >= self.batch_interval:
            print(f"バッチ間隔経過 ({self.batch_interval}秒) - バッチ通知送信")
            self.send_batch_notification()
            # 最初の検出時刻をリセット
            self.first_red_detection_time = None
    
    def send_batch_notification(self):
        """バッチ通知を送信（改善版：すべてのランプを統一形式で通知）"""
        if not self.pending_notifications:
            return
        
        current_time = time.time()
        
        # すべてのランプを統一形式でまとめて通知
        lamp_ids = sorted([n['lamp_id'] for n in self.pending_notifications])
        lamp_ids_str = [str(lamp_id) for lamp_id in lamp_ids]
        lamp_list = ", ".join(lamp_ids_str)
        
        if len(self.pending_notifications) == 1:
            # 単一ランプの場合も統一形式
            message = f"ランプが RED 状態になりました: ランプ {lamp_list} (1個)"
        else:
            # 複数ランプの場合
            message = f"複数のランプが RED 状態になりました: ランプ {lamp_list} ({len(self.pending_notifications)}個)"
        
        # 通知データ作成（代表として最初のランプの情報を使用）
        representative_notification = self.pending_notifications[0]
        notification_data = {
            "timestamp": int(current_time),
            "lamp_id": representative_notification["lamp_id"],
            "state": "RED",
            "confidence": representative_notification["confidence"],
            "message": message,
            "batch_size": len(self.pending_notifications),
            "lamp_ids": lamp_ids  # ソート済みのリスト
        }
        
        # 署名を生成
        signature = self.create_signature(notification_data)
        
        # ヘッダーに署名を追加
        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": signature
        }
        
        try:
            request_url = self.notify_config["worker_url"]
            data_payload = json.dumps(notification_data, sort_keys=True)
            
            print(f"バッチ通知送信: {len(self.pending_notifications)}個のランプ")
            print(f"通知データ: {data_payload}")
            
            response = requests.post(
                request_url,
                data=data_payload.encode('utf-8'),
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"バッチ通知送信成功: ランプ {[n['lamp_id'] for n in self.pending_notifications]}")
                # 通知済みランプの最終通知時刻を更新
                for notification in self.pending_notifications:
                    self.lamp_statuses[notification["lamp_id"]].last_notification = current_time
            else:
                print(f"バッチ通知送信失敗 (HTTP {response.status_code}) - {response.text}")
                
        except requests.RequestException as e:
            print(f"バッチ通知送信エラー - {e}")
        finally:
            # バッチをクリア
            self.pending_notifications.clear()
            self.last_batch_notification = current_time
    
    def create_signature(self, data: Dict) -> str:
        """HMAC署名を作成"""
        secret = self.notify_config["secret"].encode('utf-8')
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
        # 遅延初期化
        self._lazy_init()
        
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

class WebcamMonitorFast:
    """Webカメラ監視システム（高速化版）"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        print("設定ファイル読み込み中...")
        self.config = self.load_config(config_path)
        
        print("検出器初期化中...")
        self.detector = LampDetector(self.config)
        
        self.cap = None
        self.running = False
        
        # カメラ設定
        self.camera_config = self.config["camera"]
        
        print("初期化完了")
    
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
    
    def initialize_camera_fast(self) -> bool:
        """カメラを高速初期化（最適化版）"""
        device_id = self.camera_config["device_id"]
        
        print(f"カメラ初期化中... (デバイスID: {device_id})")
        
        # 最も成功率の高い方法を最初に試行
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
            
            # テストフレーム取得を1回のみに削減
            ret, frame = self.cap.read()
            if not ret:
                print("テストフレーム取得失敗")
                return False
            
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            print(f"カメラ設定完了: {actual_width}x{actual_height}")
            return True
            
        except Exception as e:
            print(f"カメラ初期化エラー: {e}")
            return False
    
    def release_camera(self):
        """カメラを解放"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def run(self):
        """監視システムを実行"""
        print("Webカメラ監視システム（高速化版）を開始します")
        
        if not self.initialize_camera_fast():
            print("カメラの初期化に失敗しました")
            return
        
        self.running = True
        frame_count = 0
        start_time = time.time()
        
        # ウィンドウ作成
        cv2.namedWindow("Webcam Monitor (Fast)", cv2.WINDOW_AUTOSIZE)
        
        try:
            while self.running:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("フレームの取得に失敗しました")
                    break
                
                # フレーム処理
                self.detector.process_frame(frame)
                
                # バッチ通知の定期チェック（画面フリーズ対策）
                self.detector.check_and_send_batch_notification()
                
                # デバッグ用オーバーレイを描画
                display_frame = self.detector.draw_debug_overlay(frame)
                
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
                
                for i, instruction in enumerate(instructions):
                    y_pos = display_frame.shape[0] - 60 + i * 20
                    cv2.putText(display_frame, instruction, (10, y_pos), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                # フレーム表示
                try:
                    cv2.imshow("Webcam Monitor (Fast)", display_frame)
                except cv2.error:
                    print("ウィンドウが閉じられました")
                    break
                
                # キー入力処理
                key = cv2.waitKey(1) & 0xFF
                
                # ウィンドウの状態をチェック
                try:
                    if cv2.getWindowProperty("Webcam Monitor (Fast)", cv2.WND_PROP_VISIBLE) < 1:
                        print("ウィンドウが閉じられました")
                        break
                except:
                    print("ウィンドウが閉じられました")
                    break
                
                if key == ord('q') or key == 27:
                    break
                elif key == ord('s'):
                    self.save_frame(frame, frame_count)
                elif key == ord('r'):
                    self.reset_lamp_history()
                
                # 統計情報出力（頻度を下げて高速化）
                if frame_count % 200 == 0:
                    print(f"処理フレーム数: {frame_count}, FPS: {current_fps:.1f}")
                    self.print_lamp_status()
                
        except KeyboardInterrupt:
            print("\nキーボード割り込みで終了します")
        finally:
            self.running = False
            cv2.destroyAllWindows()
            self.release_camera()
            print("Webカメラ監視システム（高速化版）を終了しました")
    
    def save_frame(self, frame: np.ndarray, frame_count: int):
        """現在のフレームを保存"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"webcam_frame_fast_{timestamp}_{frame_count:06d}.png"
        cv2.imwrite(filename, frame)
        print(f"フレームを保存しました: {filename}")
    
    def reset_lamp_history(self):
        """ランプ履歴をリセット"""
        if self.detector._initialized:
            for lamp_id in range(1, 13):
                self.detector.lamp_history[lamp_id].clear()
                self.detector.lamp_statuses[lamp_id].state = "UNKNOWN"
                self.detector.lamp_statuses[lamp_id].confidence = 0.0
            print("ランプ履歴をリセットしました")
        else:
            print("まだ初期化されていません")
    
    def print_lamp_status(self):
        """現在のランプ状態を出力"""
        if not self.detector._initialized:
            print("まだランプ状態が初期化されていません")
            return
            
        print("\n=== 現在のランプ状態 ===")
        for lamp_id in range(1, 13):
            status = self.detector.lamp_statuses[lamp_id]
            print(f"ランプ {lamp_id:2d}: {status.state:7s} (信頼度: {status.confidence:.2f})")
        print("========================\n")

def main():
    """メイン関数"""
    print("=== Webカメラ監視システム（高速化版） ===")
    print("起動時間を最適化したバージョンです")
    print("事前にconfig.yamlでROI座標を設定してください")
    print()
    
    monitor = WebcamMonitorFast()
    monitor.run()

if __name__ == "__main__":
    main()
