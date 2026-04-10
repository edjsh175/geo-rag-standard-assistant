#!/usr/bin/env python3
"""
简单项目结构测试 - ASCII only
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    print("Testing project structure imports...")
    modules = [
        "src.geoai.core.config",
        "src.geoai.utils",
        "src.geoai.data.processor",
        "src.geoai.spatial.importer",
    ]

    for module in modules:
        try:
            __import__(module)
            print(f"PASS: {module}")
        except ImportError as e:
            print(f"FAIL: {module} - {e}")
            return False
        except Exception as e:
            print(f"WARN: {module} - {e} (may need dependencies)")

    return True

def test_paths():
    print("\nTesting essential paths...")
    paths = [
        "config/development.yaml",
        "config/production.yaml",
        "config/pachong.py",
        "scripts/build_vector_db.py",
        "scripts/import_spatial_data.py",
    ]

    for path in paths:
        if os.path.exists(path):
            print(f"EXISTS: {path}")
        else:
            print(f"MISSING: {path}")
            return False

    return True

def test_packages():
    print("\nTesting package structure...")
    packages = [
        "src/geoai",
        "src/geoai/core",
        "src/geoai/data",
        "src/geoai/spatial",
        "src/geoai/web",
        "src/geoai/utils",
    ]

    for pkg in packages:
        if not os.path.isdir(pkg):
            print(f"MISSING DIR: {pkg}")
            return False

        init = os.path.join(pkg, "__init__.py")
        if not os.path.exists(init):
            print(f"MISSING INIT: {init}")
            return False

    print("All packages present")
    return True

if __name__ == "__main__":
    print("GeoAI Project Structure Test")
    print("=" * 50)

    results = []
    results.append(("Imports", test_imports()))
    results.append(("Paths", test_paths()))
    results.append(("Packages", test_packages()))

    print("\n" + "=" * 50)
    print("Results:")

    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{name}: {status}")
        if not passed:
            all_pass = False

    print("\n" + "=" * 50)
    if all_pass:
        print("SUCCESS: All structure tests passed!")
        sys.exit(0)
    else:
        print("FAILURE: Some tests failed")
        sys.exit(1)