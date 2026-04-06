"""验证配置文件"""
import config
import os

print('=== 配置验证 ===')
print(f'压缩包目录: {config.COMPRESSED_DIR}')
print(f'MySQL主机: {config.MYSQL_CONFIG["host"]}:{config.MYSQL_CONFIG["port"]}')
print(f'MySQL数据库: {config.MYSQL_CONFIG["database"]}')
print(f'MySQL用户: {config.MYSQL_CONFIG["user"]}')
print(f'MySQL表: {config.MYSQL_TABLE}')
print(f'PostgreSQL数据库: {config.DB_CONFIG["dbname"]}')
print(f'向量维度: {config.VECTOR_DIMENSION}')
print(f'Embedding模型: {config.EMBEDDING_MODEL}')
print('')
print('=== 检查压缩包目录 ===')
if os.path.exists(config.COMPRESSED_DIR):
    files = os.listdir(config.COMPRESSED_DIR)
    print(f'目录存在，包含 {len(files)} 个文件/文件夹')
    for f in files[:10]:
        full_path = os.path.join(config.COMPRESSED_DIR, f)
        if os.path.isdir(full_path):
            subfiles = os.listdir(full_path)
            zip_files = [sf for sf in subfiles if sf.endswith('.zip')]
            print(f'  - {f}/ (文件夹, 包含 {len(zip_files)} 个zip文件)')
else:
    print(f'目录不存在: {config.COMPRESSED_DIR}')
