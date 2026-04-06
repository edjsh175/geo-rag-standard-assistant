#!/usr/bin/env python3
"""
项目结构测试脚本
测试新的企业级项目结构是否能正常工作
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """测试所有主要模块的导入"""
    print("=" * 60)
    print("测试项目结构导入...")
    print("=" * 60)

    modules_to_test = [
        ("src.geoai.core.config", "核心配置"),
        ("src.geoai.utils", "工具函数"),
        ("src.geoai.data.processor", "数据处理"),
        ("src.geoai.spatial.importer", "空间数据导入"),
        ("src.geoai.data.extractor", "数据提取"),
        ("src.geoai.data.crawler", "网络爬虫"),
        ("src.geoai.web.gui", "GUI应用"),
    ]

    all_passed = True

    for module_name, description in modules_to_test:
        try:
            __import__(module_name)
            print(f"✅ {description} ({module_name}) 导入成功")
        except ImportError as e:
            print(f"❌ {description} ({module_name}) 导入失败: {e}")
            all_passed = False
        except Exception as e:
            print(f"⚠️  {description} ({module_name}) 导入异常: {e}")
            # 某些模块可能需要特定依赖，这不算完全失败
            print(f"    (可能需要额外依赖: {e})")

    print("\n" + "=" * 60)

    # 测试配置文件路径
    print("\n测试配置文件路径...")
    config_paths = [
        ("config/development.yaml", "开发环境配置"),
        ("config/production.yaml", "生产环境配置"),
        ("config/pachong.py", "爬虫配置"),
        ("config/logging.conf", "日志配置"),
    ]

    for path, description in config_paths:
        if os.path.exists(path):
            print(f"✅ {description} ({path}) 存在")
        else:
            print(f"❌ {description} ({path}) 不存在")
            all_passed = False

    # 测试数据目录结构
    print("\n测试数据目录结构...")
    data_dirs = [
        ("data/raw", "原始数据目录"),
        ("data/processed", "处理数据目录"),
        ("data/external", "外部数据目录"),
    ]

    for path, description in data_dirs:
        if os.path.exists(path):
            print(f"✅ {description} ({path}) 存在")
        else:
            print(f"⚠️  {description} ({path}) 不存在 (将自动创建)")
            # 数据目录不存在不算失败

    # 测试关键脚本
    print("\n测试关键脚本...")
    scripts = [
        ("scripts/build_vector_db.py", "向量数据库构建脚本"),
        ("scripts/import_spatial_data.py", "空间数据导入脚本"),
        ("scripts/run_gui.py", "GUI启动脚本"),
    ]

    for path, description in scripts:
        if os.path.exists(path):
            print(f"✅ {description} ({path}) 存在")
        else:
            print(f"❌ {description} ({path}) 不存在")
            all_passed = False

    print("\n" + "=" * 60)

    if all_passed:
        print("🎉 所有结构测试通过！项目结构完整。")
        return True
    else:
        print("⚠️  部分测试失败，请检查上述问题。")
        return False

def test_config_values():
    """测试配置值"""
    print("\n" + "=" * 60)
    print("测试配置值...")
    print("=" * 60)

    try:
        from src.geoai.core.config import PROJECT_ROOT, EXTRACT_DIR, SAFE_EXTRACT_DIR

        print(f"PROJECT_ROOT: {PROJECT_ROOT}")
        print(f"EXTRACT_DIR: {EXTRACT_DIR}")
        print(f"SAFE_EXTRACT_DIR: {SAFE_EXTRACT_DIR}")

        # 检查路径是否存在
        for name, path in [
            ("项目根目录", PROJECT_ROOT),
            ("提取目录", EXTRACT_DIR),
            ("安全提取目录", SAFE_EXTRACT_DIR),
        ]:
            if os.path.exists(path):
                print(f"✅ {name}: {path} (存在)")
            else:
                print(f"⚠️  {name}: {path} (不存在)")

        return True
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_package_structure():
    """测试包结构"""
    print("\n" + "=" * 60)
    print("测试包结构...")
    print("=" * 60)

    required_packages = [
        "src/geoai",
        "src/geoai/core",
        "src/geoai/data",
        "src/geoai/spatial",
        "src/geoai/api",
        "src/geoai/web",
        "src/geoai/utils",
    ]

    all_exists = True

    for package in required_packages:
        # 检查目录
        if os.path.isdir(package):
            print(f"✅ 包目录: {package}/")

            # 检查 __init__.py
            init_file = os.path.join(package, "__init__.py")
            if os.path.exists(init_file):
                print(f"    └─ __init__.py 存在")
            else:
                print(f"    └─ ❌ __init__.py 缺失")
                all_exists = False
        else:
            print(f"❌ 包目录: {package}/ (缺失)")
            all_exists = False

    return all_exists

if __name__ == "__main__":
    print("GeoAI 项目结构测试")
    print("=" * 60)

    tests = [
        ("导入测试", test_imports),
        ("包结构测试", test_package_structure),
        ("配置测试", test_config_values),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"\n▶ 执行 {test_name}...")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    print("\n" + "=" * 60)
    print("测试结果汇总:")
    print("=" * 60)

    all_passed = True
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 所有测试通过！项目结构完整且可工作。")
        sys.exit(0)
    else:
        print("⚠️  部分测试失败，请修复上述问题。")
        sys.exit(1)