#!/usr/bin/env python3
"""
カメラテスト用スクリプト
"""

import cv2

def test_cameras():
    """利用可能なカメラをテスト"""
    print("カメラデバイステスト開始...")
    
    # 異なるデバイスIDをテスト
    for device_id in range(5):
        print(f"\nデバイスID {device_id} をテスト中...")
        
        # デフォルトバックエンド
        cap = cv2.VideoCapture(device_id)
        if cap.isOpened():
            print(f"  デフォルトバックエンド: 成功")
            # 解像度を取得
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  解像度: {width}x{height}, FPS: {fps}")
            cap.release()
            return device_id
        else:
            print(f"  デフォルトバックエンド: 失敗")
        cap.release()
        
        # MSMFバックエンド
        cap = cv2.VideoCapture(device_id, cv2.CAP_MSMF)
        if cap.isOpened():
            print(f"  MSMFバックエンド: 成功")
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  解像度: {width}x{height}, FPS: {fps}")
            cap.release()
            return device_id
        else:
            print(f"  MSMFバックエンド: 失敗")
        cap.release()
        
        # DSHOWバックエンド
        cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
        if cap.isOpened():
            print(f"  DSHOWバックエンド: 成功")
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  解像度: {width}x{height}, FPS: {fps}")
            cap.release()
            return device_id
        else:
            print(f"  DSHOWバックエンド: 失敗")
        cap.release()
    
    print("\n利用可能なカメラが見つかりませんでした")
    return None

def test_camera_capture(device_id):
    """カメラからの映像取得をテスト"""
    print(f"\nデバイスID {device_id} で映像取得テスト...")
    
    cap = cv2.VideoCapture(device_id)
    if not cap.isOpened():
        print("カメラを開けませんでした")
        return False
    
    print("カメラが開かれました。フレーム取得テスト中...")
    
    for i in range(5):
        ret, frame = cap.read()
        if ret:
            print(f"フレーム {i+1}: 取得成功 (サイズ: {frame.shape})")
        else:
            print(f"フレーム {i+1}: 取得失敗")
            cap.release()
            return False
    
    cap.release()
    print("映像取得テスト完了")
    return True

if __name__ == "__main__":
    # カメラデバイステスト
    working_device = test_cameras()
    
    if working_device is not None:
        print(f"\n動作するカメラが見つかりました: デバイスID {working_device}")
        
        # 映像取得テスト
        if test_camera_capture(working_device):
            print(f"\nカメラテスト成功！")
            print(f"config.yamlのdevice_idを {working_device} に設定してください")
        else:
            print("\n映像取得テストに失敗しました")
    else:
        print("\n利用可能なカメラが見つかりませんでした")
        print("以下を確認してください:")
        print("1. カメラが正しく接続されているか")
        print("2. 他のアプリケーションがカメラを使用していないか")
        print("3. カメラドライバが正しくインストールされているか")
