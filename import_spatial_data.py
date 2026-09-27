#!/usr/bin/env python3
"""
离线空间数据导入入口脚本 (Offline Tooling)。
系统运行时规范服务端单一真源为 Backend/app；src.geoai 属于离线数据预处理工具包。
"""
import sys
import os

# 将项目根目录添加到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from src.geoai.spatial.importer import *
except ImportError as e:
    print(f"警告: 无法从新位置导入空间导入器模块: {e}")
    print("请确保已正确安装geoai包或设置PYTHONPATH")
    raise

# 如果脚本被直接运行，调用导入器的主函数
if __name__ == "__main__":
    try:
        from src.geoai.spatial.importer import main as importer_main
        importer_main()
    except ImportError:
        print("错误: 无法运行导入器主函数")
        sys.exit(1)