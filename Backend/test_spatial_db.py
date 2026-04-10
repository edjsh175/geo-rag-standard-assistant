#!/usr/bin/env python3
"""
空间数据库连接测试脚本
测试 PostgreSQL + PostGIS 连接并查询 spatial_regions 表
使用 ST_AsGeoJSON 函数将几何字段转为 GeoJSON 格式
"""

import asyncio
import sys
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.database import db_manager
from sqlalchemy import text


async def test_spatial_regions_query():
    """测试 spatial_regions 表查询"""
    print("测试 spatial_regions 表查询...")

    try:
        # 初始化数据库管理器
        await db_manager.initialize()

        # 获取 PostgreSQL 会话
        async with db_manager.get_postgres_session() as session:
            # 首先检查表是否存在
            check_table_sql = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'spatial_regions'
                )
            """

            result = await session.execute(text(check_table_sql))
            table_exists = result.scalar()

            if not table_exists:
                print("  ❌ spatial_regions 表不存在")
                print("\n建议:")
                print("1. 创建 spatial_regions 表:")
                print("""
                CREATE TABLE spatial_regions (
                    id SERIAL PRIMARY KEY,
                    adcode VARCHAR(20) NOT NULL,
                    region_name VARCHAR(100) NOT NULL,
                    geometry geometry(Geometry, 4326),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """)
                print("\n2. 导入测试数据:")
                print("   可以使用 shapefile 或 GeoJSON 数据导入")
                return False

            print("  ✅ spatial_regions 表存在")

            # 检查表中是否有数据
            count_sql = "SELECT COUNT(*) FROM spatial_regions"
            result = await session.execute(text(count_sql))
            row_count = result.scalar()

            print(f"  表中记录数: {row_count}")

            if row_count == 0:
                print("  ⚠️  表中没有数据，无法测试 GeoJSON 转换")
                print("\n建议:")
                print("  向 spatial_regions 表中插入一些测试数据")
                return False

            # 查询一条数据并使用 ST_AsGeoJSON 转换
            print("\n查询一条数据并转换为 GeoJSON...")
            query_sql = """
                SELECT
                    id,
                    adcode,
                    region_name,
                    ST_AsGeoJSON(geometry) as geojson
                FROM spatial_regions
                WHERE geometry IS NOT NULL
                LIMIT 1
            """

            result = await session.execute(text(query_sql))
            row = result.fetchone()

            if row is None:
                print("  ⚠️  没有找到包含几何数据的记录")
                return False

            id_val, adcode, region_name, geojson_str = row

            print(f"  ✅ 成功查询到数据:")
            print(f"      ID: {id_val}")
            print(f"      行政区划代码: {adcode}")
            print(f"      行政区划名称: {region_name}")

            # 解析和打印 GeoJSON
            if geojson_str:
                try:
                    geojson_data = json.loads(geojson_str)
                    print(f"\n  GeoJSON 数据:")
                    print(f"      类型: {geojson_data.get('type')}")

                    if geojson_data.get('type') == 'Polygon':
                        coordinates = geojson_data.get('coordinates', [])
                        if coordinates and len(coordinates) > 0:
                            print(f"      顶点数: {len(coordinates[0])}")
                            # 显示前3个和后3个坐标点
                            points = coordinates[0]
                            if len(points) >= 6:
                                print(f"      示例坐标:")
                                for i in range(min(3, len(points))):
                                    print(f"         [{points[i][0]:.6f}, {points[i][1]:.6f}]")
                                print(f"         ...")
                                for i in range(max(0, len(points)-3), len(points)):
                                    print(f"         [{points[i][0]:.6f}, {points[i][1]:.6f}]")
                    elif geojson_data.get('type') == 'MultiPolygon':
                        print(f"      包含 {len(geojson_data.get('coordinates', []))} 个多边形")

                    # 显示完整的 GeoJSON（格式化）
                    print(f"\n      完整 GeoJSON:")
                    formatted_json = json.dumps(geojson_data, indent=2, ensure_ascii=False)
                    for line in formatted_json.split('\n'):
                        print(f"        {line}")

                except json.JSONDecodeError as e:
                    print(f"  ❌ GeoJSON 解析失败: {e}")
                    print(f"      原始字符串: {geojson_str[:100]}...")
            else:
                print("  ⚠️  几何字段为 NULL")

            return True

    except Exception as e:
        print(f"  ❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_spatial_functions():
    """测试 PostGIS 空间函数"""
    print("\n测试 PostGIS 空间函数...")

    try:
        async with db_manager.get_postgres_session() as session:
            # 测试 ST_AsGeoJSON 函数
            test_sql = """
                SELECT
                    ST_AsGeoJSON(ST_MakePoint(116.4074, 39.9042)::geometry) as point_geojson,
                    ST_AsGeoJSON(ST_Buffer(ST_MakePoint(116.4074, 39.9042)::geography, 1000)::geometry) as buffer_geojson
            """

            result = await session.execute(text(test_sql))
            row = result.fetchone()

            if row:
                point_geojson, buffer_geojson = row
                print("  ✅ PostGIS 空间函数测试成功")
                print(f"      点几何 GeoJSON: {point_geojson}")
                print(f"      缓冲区几何 GeoJSON: {buffer_geojson[:100]}...")
                return True
            else:
                print("  ❌ 空间函数测试失败")
                return False

    except Exception as e:
        print(f"  ❌ 空间函数测试失败: {e}")
        return False


async def main():
    """主函数"""
    print("=" * 60)
    print("GeoAI 空间数据库连接测试")
    print("=" * 60)

    print(f"数据库连接: {settings.DATABASE_URL}")

    try:
        # 测试 spatial_regions 表查询
        query_ok = await test_spatial_regions_query()

        # 测试空间函数
        functions_ok = await test_spatial_functions()

        print("\n" + "=" * 60)
        print("测试结果:")
        print("=" * 60)

        if query_ok:
            print("✅ spatial_regions 表查询: 成功")
        else:
            print("❌ spatial_regions 表查询: 失败")

        if functions_ok:
            print("✅ PostGIS 空间函数: 正常")
        else:
            print("❌ PostGIS 空间函数: 异常")

        print("\n建议:")
        if not query_ok:
            print("- 请确保 spatial_regions 表存在并包含几何数据")
            print("- 可以运行数据库迁移脚本创建表结构")
            print("- 导入行政区划数据（如省、市、县边界）")

        print("\n下一步:")
        print("1. 如果所有测试通过，空间数据库连接正常")
        print("2. 如果测试失败，请检查数据库连接和表结构")
        print("3. 启动服务: uvicorn main:app --reload")

    finally:
        # 清理数据库连接
        await db_manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"脚本执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)