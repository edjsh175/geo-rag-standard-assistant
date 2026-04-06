#!/usr/bin/env python3
"""
导入省级行政区划Shapefile数据到PostgreSQL PostGIS数据库
目标表：spatial_regions
字段：adcode(行政区划代码), region_name(名称), geometry(几何)
坐标系：EPSG:4326 (WGS84)
"""

import geopandas as gpd
import psycopg2
from psycopg2.extras import execute_values
import os
import sys
from src.geoai.core.config import DB_CONFIG, SHENG_2022_SHP  # 从新配置模块导入

def check_shapefile_fields(gdf):
    """检查shapefile字段并确定映射关系"""
    print("Shapefile字段:")
    for col in gdf.columns:
        if col != 'geometry':
            sample = gdf[col].iloc[0] if len(gdf) > 0 else 'N/A'
            dtype = gdf[col].dtype
            print(f"  - {repr(col)}: 类型={dtype}, 示例值={repr(sample)}")

    # 尝试自动识别字段
    field_map = {}

    # 查找可能的adcode字段（int64类型，6位数字）
    for col in gdf.columns:
        if col == 'geometry':
            continue
        if gdf[col].dtype in ['int64', 'float64']:
            # 检查值是否为6位数字（行政区划代码）
            sample = gdf[col].iloc[0] if len(gdf) > 0 else None
            if sample is not None and len(str(int(sample))) == 6:
                field_map['adcode'] = col
                print(f"    识别为adcode字段: {repr(col)}")
                break

    # 查找可能的名称字段（字符串类型，包含中文字符）
    for col in gdf.columns:
        if col == 'geometry' or col == field_map.get('adcode'):
            continue
        if gdf[col].dtype == 'object':  # 字符串类型
            sample = gdf[col].iloc[0] if len(gdf) > 0 else ''
            # 检查是否包含中文字符（简单判断）
            if sample and any('\u4e00' <= char <= '\u9fff' for char in str(sample)):
                field_map['region_name'] = col
                print(f"    识别为region_name字段: {repr(col)}")
                break

    # 如果自动识别失败，使用默认映射
    if 'adcode' not in field_map and len(gdf.columns) >= 2:
        # 查找第一个非几何、非字符串字段作为adcode
        for col in gdf.columns:
            if col != 'geometry' and gdf[col].dtype in ['int64', 'float64']:
                field_map['adcode'] = col
                print(f"    默认映射adcode字段: {repr(col)}")
                break

    if 'region_name' not in field_map and len(gdf.columns) >= 1:
        # 查找第一个非几何、非adcode字段作为region_name
        for col in gdf.columns:
            if col != 'geometry' and col != field_map.get('adcode'):
                field_map['region_name'] = col
                print(f"    默认映射region_name字段: {repr(col)}")
                break

    print(f"字段映射: {field_map}")
    return field_map

def transform_coordinates(gdf):
    """将坐标系转换为EPSG:4326"""
    print(f"原始坐标系: {gdf.crs}")

    # 转换坐标系
    if gdf.crs is None:
        print("警告: shapefile没有定义坐标系，尝试使用EPSG:4326")
        gdf.crs = 'EPSG:4326'
    else:
        print("正在转换坐标系到EPSG:4326...")
        gdf = gdf.to_crs('EPSG:4326')

    print(f"转换后坐标系: {gdf.crs}")

    # 验证坐标范围
    bounds = gdf.total_bounds
    print(f"坐标范围: 经度 [{bounds[0]:.4f}, {bounds[2]:.4f}], 纬度 [{bounds[1]:.4f}, {bounds[3]:.4f}]")

    # 检查是否在合理范围内（中国大致范围）
    if bounds[0] < 70 or bounds[2] > 140 or bounds[1] < 15 or bounds[3] > 55:
        print("警告: 坐标范围超出中国大致范围，请检查坐标系转换是否正确")

    return gdf

def connect_database():
    """连接PostgreSQL数据库"""
    try:
        conn = psycopg2.connect(
            dbname=DB_CONFIG['dbname'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port']
        )
        conn.autocommit = False
        print(f"成功连接到数据库: {DB_CONFIG['dbname']}")
        return conn
    except Exception as e:
        print(f"数据库连接失败: {e}")
        sys.exit(1)

def check_spatial_regions_table(conn):
    """检查spatial_regions表是否存在"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'spatial_regions'
                );
            """)
            exists = cur.fetchone()[0]

            if exists:
                print("spatial_regions表已存在")
                # 检查表结构
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'spatial_regions'
                    ORDER BY ordinal_position;
                """)
                columns = cur.fetchall()
                print("表结构:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]}")
            else:
                print("spatial_regions表不存在，将创建新表")
                create_spatial_regions_table(conn)

            return exists
    except Exception as e:
        print(f"检查表失败: {e}")
        conn.rollback()
        return False

def create_spatial_regions_table(conn):
    """创建spatial_regions表"""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE spatial_regions (
                    id SERIAL PRIMARY KEY,
                    adcode VARCHAR(10) NOT NULL,
                    region_name VARCHAR(100) NOT NULL,
                    geometry GEOMETRY(MultiPolygon, 4326),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(adcode)
                );
            """)

            # 创建空间索引
            cur.execute("""
                CREATE INDEX idx_spatial_regions_geometry
                ON spatial_regions USING GIST(geometry);
            """)

            conn.commit()
            print("成功创建spatial_regions表")
    except Exception as e:
        print(f"创建表失败: {e}")
        conn.rollback()
        raise

def clear_existing_data(conn):
    """清空表中的现有数据"""
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE spatial_regions RESTART IDENTITY;")
            conn.commit()
            print("已清空spatial_regions表中的现有数据")
    except Exception as e:
        print(f"清空数据失败: {e}")
        conn.rollback()
        raise

def import_to_database(conn, gdf, field_map):
    """将数据导入数据库"""
    try:
        # 准备数据
        records = []
        for idx, row in gdf.iterrows():
            adcode = str(row[field_map['adcode']]).strip()
            region_name = str(row[field_map['region_name']]).strip()

            # 获取几何对象的WKT表示
            geom = row['geometry']

            records.append((adcode, region_name, geom.wkt))

        print(f"准备导入 {len(records)} 条记录")

        # 插入数据
        with conn.cursor() as cur:
            # 使用execute_values进行批量插入
            execute_values(
                cur,
                """
                INSERT INTO spatial_regions (adcode, region_name, geometry)
                VALUES %s
                ON CONFLICT (adcode) DO UPDATE SET
                    region_name = EXCLUDED.region_name,
                    geometry = EXCLUDED.geometry,
                    created_at = CURRENT_TIMESTAMP
                """,
                records,
                template="(%s, %s, ST_GeomFromText(%s, 4326))"
            )

            conn.commit()
            print(f"成功导入 {len(records)} 条记录到spatial_regions表")

    except Exception as e:
        print(f"导入数据失败: {e}")
        conn.rollback()
        raise

def verify_import(conn):
    """验证导入的数据"""
    try:
        with conn.cursor() as cur:
            # 统计记录数
            cur.execute("SELECT COUNT(*) FROM spatial_regions;")
            count = cur.fetchone()[0]
            print(f"spatial_regions表中共有 {count} 条记录")

            # 检查四川省是否存在
            cur.execute("SELECT region_name FROM spatial_regions WHERE adcode LIKE '51%';")
            sichuan_records = cur.fetchall()
            print(f"四川省相关的记录: {len(sichuan_records)} 条")
            for record in sichuan_records:
                print(f"  - {record[0]}")

            # 显示前5条记录
            cur.execute("""
                SELECT adcode, region_name, ST_AsText(geometry)
                FROM spatial_regions
                LIMIT 5;
            """)
            sample_records = cur.fetchall()
            print("前5条记录:")
            for record in sample_records:
                print(f"  - {record[0]}: {record[1]}")

    except Exception as e:
        print(f"验证数据失败: {e}")
        conn.rollback()

def main():
    """主函数"""
    print("=" * 60)
    print("省级行政区划数据导入工具")
    print("=" * 60)

    # 1. 读取shapefile
    shapefile_path = SHENG_2022_SHP
    if not os.path.exists(shapefile_path):
        print(f"错误: shapefile不存在: {shapefile_path}")
        print(f"请检查配置中的SHPFILE_DIR: {os.path.dirname(shapefile_path)}")
        sys.exit(1)

    print(f"读取shapefile: {shapefile_path}")
    gdf = gpd.read_file(shapefile_path)
    print(f"成功读取 {len(gdf)} 条记录")

    # 2. 检查字段
    field_map = check_shapefile_fields(gdf)

    # 3. 转换坐标系
    gdf = transform_coordinates(gdf)

    # 4. 连接数据库
    conn = connect_database()

    # 5. 检查/创建表
    check_spatial_regions_table(conn)

    # 6. 清空现有数据（可选）
    response = input("是否清空现有数据？(y/N): ").strip().lower()
    if response == 'y':
        clear_existing_data(conn)

    # 7. 导入数据
    print("\n开始导入数据...")
    import_to_database(conn, gdf, field_map)

    # 8. 验证导入
    print("\n验证导入结果...")
    verify_import(conn)

    # 9. 关闭连接
    conn.close()
    print("\n数据导入完成！")

    # 10. 提供后续步骤建议
    print("\n后续步骤:")
    print("1. 在DBeaver中查看spatial_regions表")
    print("2. 使用以下SQL验证数据:")
    print("   SELECT COUNT(*) FROM spatial_regions;")
    print("   SELECT adcode, region_name FROM spatial_regions WHERE adcode LIKE '51%';")
    print("3. 在GeoAI系统中测试空间检索功能")

if __name__ == "__main__":
    main()