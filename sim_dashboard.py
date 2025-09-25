#!/usr/bin/env python3
"""
疑似ダッシュボード（制御盤ランプ模擬表示）
------------------------------------------------------------
■ 背景
制御盤の実機ランプでテストするのは手間がかかるため、
PCモニター上に制御盤ランプを模した「仮想ダッシュボード」を表示し、
検知プログラムや通知フローの動作確認を手軽に行えるように作成した。

■ 概要
- 12個のランプをグリッド配置で表示（初期状態は全て緑）
- キーボード操作でランプの色を切替（緑 ↔ 赤）、点滅や一括変更も可能
- 動的なウィンドウリサイズに対応し、スケーリングして表示を調整
- 画像保存機能あり（状態の記録やデバッグ用途）

■ 操作方法
- 1～0, -, = : ランプ1～12のトグル（緑↔赤）
- g : 全ランプを緑に設定
- r : 全ランプを赤に設定
- b : 一部ランプを点滅状態にトグル
- a : ランダムで数個のランプを赤に設定
- s : 現在の画面をPNG画像として保存
- q / ESC : 終了
- ×ボタン : ウィンドウを閉じて終了

■ 想定ユースケース
- 本番の制御盤を使う前に、検知アルゴリズムや通知処理の疎通を確認
- ROI設定ツールと組み合わせて、ランプ位置やサイズの検証を容易に行う
- 動作確認の自動化・デバッグ用に画像を保存して後から解析可能
"""

import cv2
import numpy as np
import yaml
import time
import os
from typing import Dict, List, Tuple

class SyntheticDashboard:
    def __init__(self, config_path: str = "config.yaml"):
        """初期化"""
        self.config = self.load_config(config_path)
        self.lamp_states = ["GREEN"] * 12  # 初期状態は全て緑
        self.blink_states = [False] * 12   # 点滅状態
        self.blink_timer = time.time()
        self.blink_on = True
        self.window_closed = False  # ウィンドウが閉じられたかのフラグ
        
        # 設定値の取得
        self.default_window_size = self.config["synthetic"]["window_size"]
        self.current_window_size = self.default_window_size.copy()
        self.default_lamp_size = self.config["synthetic"]["lamp_size"]
        self.bg_color = tuple(self.config["synthetic"]["background_color"])
        self.text_color = tuple(self.config["synthetic"]["text_color"])
        
        # ウィンドウ作成（リサイズ可能に変更）
        cv2.namedWindow("Synthetic Dashboard", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Synthetic Dashboard", self.default_window_size[0], self.default_window_size[1])
        
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
    
    def update_window_size(self):
        """現在のウィンドウサイズを取得して更新"""
        try:
            # ウィンドウの実際のサイズを取得
            rect = cv2.getWindowImageRect("Synthetic Dashboard")
            if rect[2] > 0 and rect[3] > 0:  # 有効なサイズの場合
                self.current_window_size = [rect[2], rect[3]]
        except:
            # 取得できない場合はデフォルトサイズを使用
            self.current_window_size = self.default_window_size.copy()
    
    def get_dynamic_sizes(self):
        """現在のウィンドウサイズに基づいて動的サイズを計算"""
        # スケール比を計算
        scale_x = self.current_window_size[0] / self.default_window_size[0]
        scale_y = self.current_window_size[1] / self.default_window_size[1]
        scale = min(scale_x, scale_y)  # アスペクト比を保持
        
        # ランプサイズを調整
        lamp_w = int(self.default_lamp_size[0] * scale)
        lamp_h = int(self.default_lamp_size[1] * scale)
        
        # マージンとスペーシングを調整
        margin_x = int(50 * scale_x)
        margin_y = int(50 * scale_y)
        spacing_x = int(100 * scale_x)
        spacing_y = int(70 * scale_y)
        
        return (lamp_w, lamp_h), margin_x, margin_y, spacing_x, spacing_y
    
    def get_lamp_position(self, lamp_id: int) -> Tuple[int, int]:
        """ランプIDから表示位置を計算（動的サイズ対応）"""
        # 4x3のグリッドレイアウト
        col = (lamp_id - 1) % 4
        row = (lamp_id - 1) // 4
        
        # 動的サイズを取得
        _, margin_x, margin_y, spacing_x, spacing_y = self.get_dynamic_sizes()
        
        x = margin_x + col * spacing_x
        y = margin_y + row * spacing_y
        
        return x, y
    
    def draw_lamp(self, frame: np.ndarray, lamp_id: int, state: str, is_blinking: bool = False):
        """ランプを描画"""
        x, y = self.get_lamp_position(lamp_id)
        lamp_size, _, _, _, _ = self.get_dynamic_sizes()
        w, h = lamp_size
        
        # 点滅処理
        if is_blinking and not self.blink_on:
            color = self.bg_color
        else:
            if state == "RED":
                color = (0, 0, 255)  # BGR: 赤
            elif state == "GREEN":
                color = (0, 255, 0)  # BGR: 緑
            else:  # UNKNOWN
                color = (128, 128, 128)  # BGR: 灰色
        
        # ランプ本体を描画（フィナンシェ形状を矩形で近似）
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 255, 255), 2)
        
        # ランプ番号を描画（動的フォントサイズ）
        scale_x = self.current_window_size[0] / self.default_window_size[0]
        scale_y = self.current_window_size[1] / self.default_window_size[1]
        font_scale = min(scale_x, scale_y) * 0.7
        thickness = max(1, int(min(scale_x, scale_y) * 2))
        
        text = str(lamp_id)
        text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0]
        text_x = x + (w - text_size[0]) // 2
        text_y = y + (h + text_size[1]) // 2
        cv2.putText(frame, text, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness)
    
    def create_frame(self) -> np.ndarray:
        """フレームを生成（動的サイズ対応）"""
        # 現在のウィンドウサイズでフレームを作成
        frame = np.full((self.current_window_size[1], self.current_window_size[0], 3), self.bg_color, dtype=np.uint8)
        
        # 点滅タイマー更新
        current_time = time.time()
        if current_time - self.blink_timer > 0.5:  # 0.5秒間隔で点滅
            self.blink_on = not self.blink_on
            self.blink_timer = current_time
        
        # 各ランプを描画
        for i in range(12):
            lamp_id = i + 1
            state = self.lamp_states[i]
            is_blinking = self.blink_states[i]
            self.draw_lamp(frame, lamp_id, state, is_blinking)
        
        # 動的スケールを取得
        scale_x = self.current_window_size[0] / self.default_window_size[0]
        scale_y = self.current_window_size[1] / self.default_window_size[1]
        font_scale = min(scale_x, scale_y) * 0.4
        
        # 操作説明を描画（動的サイズ対応）
        instructions = [
            "Controls:",
            "1-0: Toggle L1-L10 , -: Toggle L11, =: Toggle L12",
            "g: All Green, r: All Red, b: Blink, a: Random Red",
            "s: Save Image, q: Quit"
        ]
        
        y_offset = self.current_window_size[1] - int(55 * scale_y)
        line_height = int(15 * scale_y)
        margin_x = int(10 * scale_x)
        
        for i, instruction in enumerate(instructions):
            cv2.putText(frame, instruction, (margin_x, y_offset + i * line_height), 
                       cv2.FONT_HERSHEY_SIMPLEX, font_scale, self.text_color, 1)
        
        return frame
    
    def toggle_lamp(self, lamp_id: int):
        """ランプの状態をトグル"""
        if 1 <= lamp_id <= 12:
            idx = lamp_id - 1
            if self.lamp_states[idx] == "GREEN":
                self.lamp_states[idx] = "RED"
            else:
                self.lamp_states[idx] = "GREEN"
            print(f"ランプ {lamp_id}: {self.lamp_states[idx]}")
    
    def set_all_lamps(self, state: str):
        """全ランプの状態を設定"""
        self.lamp_states = [state] * 12
        self.blink_states = [False] * 12
        print(f"全ランプ: {state}")
    
    def toggle_blink(self):
        """一部のランプの点滅をトグル"""
        # ランプ2, 5, 8を点滅対象とする
        blink_targets = [1, 4, 7]  # 0-based index
        for idx in blink_targets:
            self.blink_states[idx] = not self.blink_states[idx]
        print("点滅状態をトグルしました")
    
    def random_red(self):
        """ランダムに一部のランプを赤にする"""
        import random
        num_red = random.randint(1, 4)
        red_indices = random.sample(range(12), num_red)
        
        self.lamp_states = ["GREEN"] * 12
        for idx in red_indices:
            self.lamp_states[idx] = "RED"
        
        lamp_numbers = [idx + 1 for idx in red_indices]
        print(f"ランダム赤: ランプ {lamp_numbers}")
    
    def save_image(self):
        """現在の画像を保存"""
        frame = self.create_frame()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"dashboard_{timestamp}.png"
        cv2.imwrite(filename, frame)
        print(f"画像を保存しました: {filename}")
    
    def run(self):
        """メインループ"""
        print("疑似ダッシュボードを開始します")
        print("操作方法:")
        print("  1-0: ランプ1-10のトグル")
        print("  -: ランプ11のトグル, =: ランプ12のトグル")
        print("  g: 全て緑, r: 全て赤")
        print("  b: 一部点滅, a: ランダム赤")
        print("  s: 画像保存, q: 終了")
        print("  ×ボタン: ウィンドウを閉じて終了")
        
        try:
            while True:
                # ウィンドウサイズを更新
                self.update_window_size()
                
                # フレーム生成と表示
                frame = self.create_frame()
                
                try:
                    cv2.imshow("Synthetic Dashboard", frame)
                except cv2.error:
                    # ウィンドウが閉じられた場合
                    print("ウィンドウが閉じられました")
                    break
                
                # キー入力処理
                key = cv2.waitKey(30) & 0xFF
                
                # ウィンドウの状態をチェック（×ボタン対応）
                try:
                    # ウィンドウプロパティを取得してウィンドウの存在を確認
                    if cv2.getWindowProperty("Synthetic Dashboard", cv2.WND_PROP_VISIBLE) < 1:
                        print("ウィンドウが閉じられました")
                        break
                except:
                    # ウィンドウが存在しない場合
                    print("ウィンドウが閉じられました")
                    break
                
                if key == ord('q') or key == 27:  # 'q'キーまたはESCキー
                    break
                elif key == ord('1'):
                    self.toggle_lamp(1)
                elif key == ord('2'):
                    self.toggle_lamp(2)
                elif key == ord('3'):
                    self.toggle_lamp(3)
                elif key == ord('4'):
                    self.toggle_lamp(4)
                elif key == ord('5'):
                    self.toggle_lamp(5)
                elif key == ord('6'):
                    self.toggle_lamp(6)
                elif key == ord('7'):
                    self.toggle_lamp(7)
                elif key == ord('8'):
                    self.toggle_lamp(8)
                elif key == ord('9'):
                    self.toggle_lamp(9)
                elif key == ord('0'):
                    self.toggle_lamp(10)
                elif key == ord('-'):
                    self.toggle_lamp(11)
                elif key == ord('='):
                    self.toggle_lamp(12)
                elif key == ord('g'):
                    self.set_all_lamps("GREEN")
                elif key == ord('r'):
                    self.set_all_lamps("RED")
                elif key == ord('b'):
                    self.toggle_blink()
                elif key == ord('a'):
                    self.random_red()
                elif key == ord('s'):
                    self.save_image()
                
        except KeyboardInterrupt:
            print("\nキーボード割り込みで終了します")
        finally:
            cv2.destroyAllWindows()
            print("疑似ダッシュボードを終了しました")

def main():
    """メイン関数"""
    dashboard = SyntheticDashboard()
    dashboard.run()

if __name__ == "__main__":
    main()
