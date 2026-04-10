#!/usr/bin/env python3
"""
兼容性 setup.py 文件
新项目应使用 pyproject.toml
"""
from setuptools import setup, find_packages

if __name__ == "__main__":
    setup(
        packages=find_packages(where="src"),
        package_dir={"": "src"},
    )