#!/usr/bin/env python
"""
测试解压功能
"""

import sys
import os

# 将当前目录加入路径，以便导入 config 和 build_vector_db 中的函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入解压函数（需要从 build_vector_db 中导入）
from build_vector_db import extract_archives

def main():
    print("=== 测试解压功能 ===")

    # 调用解压函数
    extract_dir = extract_archives()

    print(f"解压目录: {extract_dir}")

    # 列出解压目录中的文件
    print(f"\n解压目录内容:")
    for root, dirs, files in os.walk(extract_dir):
        level = root.replace(extract_dir, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")

    # 统计 .md 文件数量
    md_files = []
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.endswith('.md'):
                md_files.append(os.path.join(root, file))

    print(f"\n找到 {len(md_files)} 个 .md 文件")
    if md_files:
        print("前10个 .md 文件:")
        for md_file in md_files[:10]:
            print(f"  - {os.path.relpath(md_file, extract_dir)}")

if __name__ == "__main__":
    main()