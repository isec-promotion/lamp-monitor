#!/usr/bin/env python3
"""
ROI設定ツール - マウスドラッグでランプのROI領域を設定し、config.yamlに保存
"""

import cv2
import numpy as np
import yaml
from typing import Dict, List, Tuple, Optional

class ROITool:
    """ROI設定ツール"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        self.config_path = config_path
        self.config = self.load_config()
        self.cap = None
        self.current_frame = None
        self.rois = {}
        self.current_lamp_id = 1
        self.drawing = False
        self.start_point = None
        self.end_point = None
        self.temp_rect = None
        
        # 既存のROI設定を読み込み
        if "rois" in self.config:
            for key, value in self.config["rois"].items():
                if key.startswith("lamp_"):
                    lamp_id = int(key.split("_")[1])
                    self.rois[lamp_id] = value
        
        print("ROI設定ツールを初期化しました")
        print(f"現在のランプID: {self.current_lamp_id}")
    
    def load_config(self) -> Dict:
        """設定ファイルを読み込み"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"設定ファイル {self.config_path} が見つかりません")
            return {}
        except yaml.YAMLError as e:
            print(f"設定ファイルの読み込みエラー: {e}")
            return {}
    
    def save_config(self):
        """設定ファイルに保存"""
        try:
            # ROI設定を更新
            if "rois" not in self.config:
                self.config["rois"] = {}
            
            for lamp_id, roi in self.rois.items():
                self.config["rois"][f"lamp_{lamp_id}"] = roi
            
            # ファイルに保存
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)
            
            print(f"設定を {self.config_path} に保存しました")
            
        except Exception as e:
            print(f"設定ファイルの保存エラー: {e}")
    
    def initialize_camera(self) -> bool:
        """カメラを初期化"""
        try:
            camera_config = self.config.get("camera", {})
            device_id = camera_config.get("device_id", 0)
            
            self.cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
            
            if not self.cap.isOpened():
                print(f"カメラ {device_id} を開けませんでした")
                return False
            
            # カメラ設定
            if "size" in camera_config:
                width, height = camera_config["size"]
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            if "fps" in camera_config:
                fps = camera_config["fps"]
                self.cap.set(cv2.CAP_PROP_FPS, fps)
            
            # 実際の設定値を確認
            actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            print(f"カメラを初期化しました: {actual_width}x{actual_height}")
            return True
            
        except Exception as e:
            print(f"カメラ初期化エラー: {e}")
            return False
    
    def release_camera(self):
        """カメラを解放"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
    
    def mouse_callback(self, event, x, y, flags, param):
        """マウスコールバック関数"""
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_point = (x, y)
            self.end_point = (x, y)
            
        elif event == cv2.EVENT_MOUSEMOVE:
            if self.drawing:
                self.end_point = (x, y)
                
        elif event == cv2.EVENT_LBUTTONUP:
            self.drawing = False
            self.end_point = (x, y)
            
            # ROIを計算
            if self.start_point and self.end_point:
                x1, y1 = self.start_point
                x2, y2 = self.end_point
                
                # 左上と右下の座標を正規化
                roi_x = min(x1, x2)
                roi_y = min(y1, y2)
                roi_w = abs(x2 - x1)
                roi_h = abs(y2 - y1)
                
                if roi_w > 10 and roi_h > 10:  # 最小サイズチェック
                    self.rois[self.current_lamp_id] = [roi_x, roi_y, roi_w, roi_h]
                    print(f"ランプ {self.current_lamp_id} のROIを設定: [{roi_x}, {roi_y}, {roi_w}, {roi_h}]")
                    
                    # 次のランプIDに進む
                    if self.current_lamp_id < 12:
                        self.current_lamp_id += 1
                        print(f"次のランプID: {self.current_lamp_id}")
                    else:
                        print("全てのランプのROI設定が完了しました")
            
            self.start_point = None
            self.end_point = None
    
    def draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        """オーバーレイを描画"""
        overlay_frame = frame.copy()
        
        # 既存のROIを描画
        for lamp_id, roi in self.rois.items():
            x, y, w, h = roi
            color = (0, 255, 0) if lamp_id != self.current_lamp_id else (0, 255, 255)
            cv2.rectangle(overlay_frame, (x, y), (x + w, y + h), color, 2)
            
            # ランプ番号を描画
            text = f"L{lamp_id}"
            cv2.putText(overlay_frame, text, (x, y - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        # 現在描画中の矩形を描画
        if self.drawing and self.start_point and self.end_point:
            cv2.rectangle(overlay_frame, self.start_point, self.end_point, (255, 0, 0), 2)
        
        # 情報表示
        info_lines = [
            f"Current Lamp: {self.current_lamp_id}",
            f"ROIs Set: {len(self.rois)}/12",
            "Drag to set ROI",
            "Keys: n=Next, p=Prev, d=Delete, s=Save, q=Quit"
        ]
        
        for i, line in enumerate(info_lines):
            y_pos = 30 + i * 25
            cv2.putText(overlay_frame, line, (10, y_pos), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # 現在のランプIDをハイライト
        highlight_text = f"Setting ROI for Lamp {self.current_lamp_id}"
        cv2.putText(overlay_frame, highlight_text, (10, overlay_frame.shape[0] - 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        
        return overlay_frame
    
    def run(self):
        """ROI設定ツールを実行"""
        print("ROI設定ツールを開始します")
        print("操作方法:")
        print("  マウスドラッグ: ROI設定")
        print("  n: 次のランプ")
        print("  p: 前のランプ")
        print("  d: 現在のランプのROIを削除")
        print("  s: 設定を保存")
        print("  q: 終了")
        print()
        
        if not self.initialize_camera():
            print("カメラの初期化に失敗しました")
            return
        
        # ウィンドウ作成とマウスコールバック設定
        cv2.namedWindow("ROI Tool", cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback("ROI Tool", self.mouse_callback)
        
        try:
            while True:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("フレームの取得に失敗しました")
                    break
                
                self.current_frame = frame
                
                # オーバーレイを描画
                display_frame = self.draw_overlay(frame)
                
                # フレーム表示
                cv2.imshow("ROI Tool", display_frame)
                
                # キー入力処理
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    break
                elif key == ord('n'):
                    if self.current_lamp_id < 12:
                        self.current_lamp_id += 1
                        print(f"ランプID: {self.current_lamp_id}")
                elif key == ord('p'):
                    if self.current_lamp_id > 1:
                        self.current_lamp_id -= 1
                        print(f"ランプID: {self.current_lamp_id}")
                elif key == ord('d'):
                    if self.current_lamp_id in self.rois:
                        del self.rois[self.current_lamp_id]
                        print(f"ランプ {self.current_lamp_id} のROIを削除しました")
                elif key == ord('s'):
                    self.save_config()
                    print("設定を保存しました")
                
        except KeyboardInterrupt:
            print("\nキーボード割り込みで終了します")
        finally:
            cv2.destroyAllWindows()
            self.release_camera()
            print("ROI設定ツールを終了しました")
    
    def print_roi_summary(self):
        """ROI設定の要約を出力"""
        print("\n=== ROI設定要約 ===")
        for lamp_id in range(1, 13):
            if lamp_id in self.rois:
                roi = self.rois[lamp_id]
                print(f"ランプ {lamp_id:2d}: [{roi[0]:3d}, {roi[1]:3d}, {roi[2]:3d}, {roi[3]:3d}]")
            else:
                print(f"ランプ {lamp_id:2d}: 未設定")
        print("==================\n")

def main():
    """メイン関数"""
    print("=== ROI設定ツール ===")
    print("このツールを使用してランプのROI領域を設定します")
    print("Webカメラが必要です")
    print()
    
    tool = ROITool()
    tool.run()
    tool.print_roi_summary()

if __name__ == "__main__":
    main()
