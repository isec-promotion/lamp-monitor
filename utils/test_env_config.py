#!/usr/bin/env python3
"""
test_env_config.py
環境変数展開のテストスクリプト
"""

import yaml
import os
import re
from typing import Dict

def load_env_file(env_path: str = None):
    """.envファイルを読み込んで環境変数に設定"""
    if env_path is None:
        # スクリプトの親ディレクトリ（プロジェクトルート）の.envファイルを探す
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        env_path = os.path.join(project_root, ".env")
    
    if not os.path.exists(env_path):
        print(f".envファイル ({env_path}) が見つかりません。")
        return
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # 空行やコメント行をスキップ
                if not line or line.startswith('#'):
                    continue
                
                # KEY=VALUE 形式をパース
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # クォートを除去
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    
                    # 環境変数に設定（既存の環境変数を上書きしない）
                    if key not in os.environ:
                        os.environ[key] = value
                        print(f".envから読み込み: {key} = {value}")
                    else:
                        print(f"環境変数 {key} は既に設定されているため、.envの値をスキップします")
                else:
                    print(f".envファイルの{line_num}行目の形式が正しくありません: {line}")
    
    except Exception as e:
        print(f".envファイルの読み込みエラー: {e}")

def expand_environment_variables(config: Dict) -> Dict:
    """設定内の環境変数を展開"""
    def expand_value(value):
        if isinstance(value, str):
            # ${VAR_NAME} 形式の環境変数を展開
            def replace_env_var(match):
                var_name = match.group(1)
                env_value = os.getenv(var_name)
                if env_value is None:
                    raise ValueError(f"環境変数 '{var_name}' が設定されていません")
                return env_value
            
            return re.sub(r'\$\{([^}]+)\}', replace_env_var, value)
        elif isinstance(value, dict):
            return {k: expand_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [expand_value(item) for item in value]
        else:
            return value
    
    return expand_value(config)

def test_config_loading():
    """設定ファイルの読み込みテスト"""
    try:
        print("=== 環境変数展開テスト ===")
        
        # .envファイルを読み込み
        print("1. .envファイルを読み込み中...")
        load_env_file()
        
        # 現在の環境変数を確認
        lamp_secret = os.getenv('LAMP_MONITOR_SECRET')
        print(f"2. 環境変数 LAMP_MONITOR_SECRET: {lamp_secret}")
        
        # config.yamlを読み込み
        print("3. config.yamlを読み込み中...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        config_path = os.path.join(project_root, 'config.yaml')
        
        print(f"   config.yamlのパス: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        print(f"4. 展開前のsecret: {config['notify']['secret']}")
        
        # 環境変数を展開
        print("5. 環境変数を展開中...")
        config = expand_environment_variables(config)
        
        print(f"6. 展開後のsecret: {config['notify']['secret']}")
        
        print("\n✅ テスト成功: 環境変数の展開が正常に動作しました")
        
    except Exception as e:
        print(f"\n❌ テスト失敗: {e}")

if __name__ == "__main__":
    test_config_loading()
