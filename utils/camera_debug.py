#!/usr/bin/env python3
"""
カメラデバッグ用スクリプト - より詳細な診断
"""

import cv2
import sys
import subprocess

def check_privacy_settings():
    """Windowsのプライバシー設定を確認"""
    print("=== Windowsプライバシー設定の確認 ===")
    print("以下の設定を確認してください:")
    print("1. 設定 → プライバシーとセキュリティ → カメラ")
    print("2. 'カメラへのアクセス' がオンになっているか")
    print("3. 'デスクトップ アプリがカメラにアクセスできるようにする' がオンになっているか")
    print("4. Python.exe がカメラアクセス許可リストにあるか")
    print()

def test_camera_with_different_methods():
    """異なる方法でカメラテスト"""
    print("=== 詳細カメラテスト ===")
    
    # 方法1: デフォルト
    print("方法1: デフォルトバックエンド")
    try:
        cap = cv2.VideoCapture(0)
        print(f"  VideoCapture(0): {cap.isOpened()}")
        if cap.isOpened():
            ret, frame = cap.read()
            print(f"  フレーム読み取り: {ret}")
            if ret:
                print(f"  フレームサイズ: {frame.shape}")
        cap.release()
    except Exception as e:
        print(f"  エラー: {e}")
    
    # 方法2: DSHOW with different indices
    print("\n方法2: DSHOWバックエンド（複数インデックス）")
    for i in range(3):
        try:
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            is_opened = cap.isOpened()
            print(f"  VideoCapture({i}, CAP_DSHOW): {is_opened}")
            if is_opened:
                ret, frame = cap.read()
                print(f"    フレーム読み取り: {ret}")
                if ret:
                    print(f"    フレームサイズ: {frame.shape}")
                    # 簡単なテスト表示
                    cv2.imshow(f"Test Camera {i}", frame)
                    cv2.waitKey(1000)  # 1秒表示
                    cv2.destroyAllWindows()
                    cap.release()
                    return i  # 成功したインデックスを返す
            cap.release()
        except Exception as e:
            print(f"    エラー: {e}")
    
    # 方法3: MSMF
    print("\n方法3: MSMFバックエンド")
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_MSMF)
        print(f"  VideoCapture(0, CAP_MSMF): {cap.isOpened()}")
        if cap.isOpened():
            ret, frame = cap.read()
            print(f"  フレーム読み取り: {ret}")
            if ret:
                print(f"  フレームサイズ: {frame.shape}")
        cap.release()
    except Exception as e:
        print(f"  エラー: {e}")
    
    # 方法4: デバイス名
    print("\n方法4: デバイス名指定")
    device_names = [
        "c922 Pro Stream Webcam",
        "C922 Pro Stream Webcam", 
        "Logitech C922 Pro Stream Webcam",
        "USB Camera"
    ]
    
    for device_name in device_names:
        try:
            cap = cv2.VideoCapture(device_name, cv2.CAP_DSHOW)
            is_opened = cap.isOpened()
            print(f"  VideoCapture('{device_name}', CAP_DSHOW): {is_opened}")
            if is_opened:
                ret, frame = cap.read()
                print(f"    フレーム読み取り: {ret}")
                if ret:
                    print(f"    フレームサイズ: {frame.shape}")
                    cv2.imshow(f"Test {device_name}", frame)
                    cv2.waitKey(1000)
                    cv2.destroyAllWindows()
                cap.release()
                return device_name
            cap.release()
        except Exception as e:
            print(f"    エラー: {e}")
    
    return None

def check_opencv_info():
    """OpenCV情報を確認"""
    print("=== OpenCV情報 ===")
    print(f"OpenCVバージョン: {cv2.__version__}")
    print(f"ビルド情報:")
    print(cv2.getBuildInformation())

def main():
    print("C922 Pro Stream Webcam デバッグツール")
    print("=" * 50)
    
    # プライバシー設定の確認
    check_privacy_settings()
    
    # OpenCV情報
    check_opencv_info()
    
    # カメラテスト
    working_method = test_camera_with_different_methods()
    
    if working_method is not None:
        print(f"\n✅ 成功: {working_method} でカメラにアクセスできました！")
        print("config.yamlを更新してください")
    else:
        print("\n❌ すべての方法でカメラアクセスに失敗しました")
        print("\n追加の確認事項:")
        print("1. 他のアプリ（Skype、Teams、Chrome等）がカメラを使用していないか")
        print("2. Windowsのプライバシー設定でカメラアクセスが許可されているか")
        print("3. カメラドライバが正しくインストールされているか")
        print("4. 管理者権限でPythonを実行してみる")

if __name__ == "__main__":
    main()
