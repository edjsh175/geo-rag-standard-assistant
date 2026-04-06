#!/usr/bin/env python3
"""
启动GUI应用程序
"""
import sys
import os

# 将项目根目录添加到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.geoai.web.gui import main
except ImportError as e:
    print(f"错误: 无法导入GUI模块: {e}")
    print("请确保geoai包已正确安装或PYTHONPATH已设置")
    sys.exit(1)

if __name__ == "__main__":
    main()