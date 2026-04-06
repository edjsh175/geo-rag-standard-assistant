import os
import re
import time
import psycopg2
from pgvector.psycopg2 import register_vector
from zhipuai import ZhipuAI
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
import zipfile
import tarfile
import shutil
import tempfile
from pathlib import Path
import datetime
from functools import wraps

# 从新配置模块导入
from src.geoai.core.config import (
    MYSQL_CONFIG,
    MYSQL_TABLE,
    MYSQL_STANDARD_CODE_FIELD,
    MYSQL_RELEASE_DATE_FIELD,
    MYSQL_IMPLEMENT_DATE_FIELD,
    MYSQL_DRAFT_UNIT_FIELD,
    MYSQL_KEYWORD_FIELD,
    PROJECT_ROOT,
    COMPRESSED_DIR,
    EXTRACT_DIR,
    SAFE_EXTRACT_DIR,
    SUPPORTED_ARCHIVE_EXTENSIONS,
    FORCE_EXTRACT,
    DELETE_AFTER_EXTRACT,
    RECURSIVE_EXTRACT,
    HEADERS_TO_SPLIT_ON,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    ZHIPU_API_KEY,
    EMBEDDING_MODEL,
    VECTOR_DIMENSION,
    DB_CONFIG
)

# ================= MySQL 连接配置（从新配置模块读取）=================
# 使用统一的 MySQL 配置（已从配置模块导入）

try:
    import pymysql
    MYSQL_SUPPORT = True
except ImportError:
    MYSQL_SUPPORT = False
    print("[警告] 未安装 pymysql，无法从 MySQL 获取元数据。请运行: pip install pymysql")

try:
    import rarfile
    RAR_SUPPORT = True
except ImportError:
    RAR_SUPPORT = False

try:
    import py7zr
    SEVENZIP_SUPPORT = True
except ImportError:
    SEVENZIP_SUPPORT = False

# 全局客户端，在 main 中初始化
client = None

def exponential_backoff(max_retries=4, base_delay=1):
    """
    指数退避重试装饰器
    重试序列: 1s, 2s, 4s, 8s
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        print(f"[错误] 达到最大重试次数，执行失败: {e}")
                        return None  # 与现有 get_embedding 行为保持一致，返回 None
                    delay = base_delay * (2 ** attempt)
                    print(f"[重试] 接口调用失败: {e}，{delay}秒后进行第{attempt + 2}次重试...")
                    time.sleep(delay)
        return wrapper
    return decorator

def extract_archives():
    """
    解压压缩包到目标目录
    返回解压后的目录路径
    """
    compressed_dir = config.COMPRESSED_DIR
    extract_dir = config.EXTRACT_DIR

    # 如果压缩包目录不存在，直接返回解压目录（可能已有解压文件）
    if not os.path.exists(compressed_dir):
        print(f"[警告] 压缩包目录不存在: {compressed_dir}")
        print(f"[目录] 直接使用解压目录: {extract_dir}")
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir, exist_ok=True)
        return extract_dir

    # 检查是否需要解压
    if config.FORCE_EXTRACT or not os.path.exists(extract_dir) or not os.listdir(extract_dir):
        print(f"[开始] 开始解压压缩包，从 {compressed_dir} 到 {extract_dir}")

        # 创建或清空解压目录
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)

        # 遍历压缩包目录
        extracted_count = 0
        for file_name in os.listdir(compressed_dir):
            file_path = os.path.join(compressed_dir, file_name)

            # 检查是否支持的文件类型
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in config.SUPPORTED_ARCHIVE_EXTENSIONS:
                continue

            print(f"[解压] 解压: {file_name}")

            try:
                if ext == '.zip':
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    extracted_count += 1

                elif ext == '.rar' and RAR_SUPPORT:
                    with rarfile.RarFile(file_path, 'r') as rar_ref:
                        rar_ref.extractall(extract_dir)
                    extracted_count += 1
                elif ext == '.rar' and not RAR_SUPPORT:
                    print(f"[警告] 跳过 .rar 文件 {file_name}，需要安装 rarfile 库: pip install rarfile")

                elif ext == '.7z' and SEVENZIP_SUPPORT:
                    with py7zr.SevenZipFile(file_path, mode='r') as sz_ref:
                        sz_ref.extractall(extract_dir)
                    extracted_count += 1
                elif ext == '.7z' and not SEVENZIP_SUPPORT:
                    print(f"[警告] 跳过 .7z 文件 {file_name}，需要安装 py7zr 库: pip install py7zr")

                # 可选：解压后删除压缩包
                if config.DELETE_AFTER_EXTRACT:
                    os.remove(file_path)

            except Exception as e:
                print(f"[错误] 解压失败 {file_name}: {e}")

        print(f"[完成] 解压完成，共处理 {extracted_count} 个压缩包")

        # 递归解压：处理解压目录中的压缩包
        if config.RECURSIVE_EXTRACT:
            recursive_extract(extract_dir)
    else:
        print(f"[目录] 使用已存在的解压目录: {extract_dir}")

    return extract_dir

def safe_extract_archives():
    """
    安全解压压缩包：按分类/标准名创建独立目录，防止文件覆盖
    返回解压后的安全目录路径
    """
    compressed_dir = config.COMPRESSED_DIR
    safe_extract_dir = SAFE_EXTRACT_DIR

    # 如果压缩包目录不存在，直接返回安全解压目录（可能已有解压文件）
    if not os.path.exists(compressed_dir):
        print(f"[警告] 压缩包目录不存在: {compressed_dir}")
        print(f"[目录] 直接使用安全解压目录: {safe_extract_dir}")
        if not os.path.exists(safe_extract_dir):
            os.makedirs(safe_extract_dir, exist_ok=True)
        return safe_extract_dir

    # 检查是否需要解压
    if config.FORCE_EXTRACT or not os.path.exists(safe_extract_dir) or not os.listdir(safe_extract_dir):
        print(f"[开始] 开始安全解压压缩包，从 {compressed_dir} 到 {safe_extract_dir}")

        # 创建或清空安全解压目录
        if os.path.exists(safe_extract_dir):
            shutil.rmtree(safe_extract_dir)
        os.makedirs(safe_extract_dir, exist_ok=True)

        # 遍历压缩包目录及其子目录
        extracted_count = 0
        for root, dirs, files in os.walk(compressed_dir):
            for file_name in files:
                file_path = os.path.join(root, file_name)

                # 检查是否支持的文件类型
                ext = os.path.splitext(file_name)[1].lower()
                if ext not in config.SUPPORTED_ARCHIVE_EXTENSIONS:
                    continue

                # 解析分类和标准名
                # 压缩包路径示例: compressed_dir/崩塌/DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南.zip
                # relative_path 是从 compressed_dir 开始的相对路径
                relative_path = os.path.relpath(root, compressed_dir)

                # 分类是相对路径的第一部分（如果存在）
                if relative_path == ".":
                    category = "未分类"
                else:
                    # 取第一个目录作为分类
                    category = relative_path.split(os.sep)[0]

                # 从文件名提取标准号和标准名
                # 文件名格式: "DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南.zip"
                # 去除扩展名
                file_name_no_ext = os.path.splitext(file_name)[0]

                # 标准号可能包含空格，如 "DB61_T 1533-2022" 或 "GB/T 12345-2020"
                # 使用正则表达式匹配标准号
                # 匹配模式：字母开头 + 可选数字 + 可选分隔符 + 可选字母 + 可选空格 + 数字-数字
                match = re.match(r'^([A-Z]+\d*[/._]?[A-Z]*\s*\d+[—\-]\d+)(?:\s+(.+))?$', file_name_no_ext, re.IGNORECASE)
                if match:
                    standard_code = match.group(1).strip()  # 标准号: DB61_T 1533-2022
                    standard_name = match.group(2) if match.group(2) else ""  # 标准名
                else:
                    # 回退到简单的空格分割
                    parts = file_name_no_ext.split(' ', 1)
                    if len(parts) >= 2:
                        standard_code = parts[0]
                        standard_name = parts[1]
                    else:
                        standard_code = file_name_no_ext
                        standard_name = file_name_no_ext

                # 创建目标目录: safe_extract_dir/分类/标准号 标准名/
                target_dir = os.path.join(safe_extract_dir, category, file_name_no_ext)
                os.makedirs(target_dir, exist_ok=True)

                print(f"[安全解压] {category}/{file_name} -> {category}/{file_name_no_ext}/")

                try:
                    if ext == '.zip':
                        with zipfile.ZipFile(file_path, 'r') as zip_ref:
                            zip_ref.extractall(target_dir)
                        extracted_count += 1

                    elif ext == '.rar' and RAR_SUPPORT:
                        with rarfile.RarFile(file_path, 'r') as rar_ref:
                            rar_ref.extractall(target_dir)
                        extracted_count += 1
                    elif ext == '.rar' and not RAR_SUPPORT:
                        print(f"[警告] 跳过 .rar 文件 {file_name}，需要安装 rarfile 库: pip install rarfile")

                    elif ext == '.7z' and SEVENZIP_SUPPORT:
                        with py7zr.SevenZipFile(file_path, mode='r') as sz_ref:
                            sz_ref.extractall(target_dir)
                        extracted_count += 1
                    elif ext == '.7z' and not SEVENZIP_SUPPORT:
                        print(f"[警告] 跳过 .7z 文件 {file_name}，需要安装 py7zr 库: pip install py7zr")

                    # 可选：解压后删除压缩包
                    if config.DELETE_AFTER_EXTRACT:
                        os.remove(file_path)

                except Exception as e:
                    print(f"[错误] 安全解压失败 {file_name}: {e}")

        print(f"[完成] 安全解压完成，共处理 {extracted_count} 个压缩包")

        # 递归解压：处理安全解压目录中的压缩包
        if config.RECURSIVE_EXTRACT:
            recursive_extract(safe_extract_dir)
    else:
        print(f"[目录] 使用已存在的安全解压目录: {safe_extract_dir}")

    return safe_extract_dir

def recursive_extract(directory):
    """递归解压目录中的压缩包"""
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            ext = os.path.splitext(file_name)[1].lower()

            if ext in config.SUPPORTED_ARCHIVE_EXTENSIONS:
                print(f"[解压] 递归解压: {file_name}")
                try:
                    # 在相同目录解压
                    if ext == '.zip':
                        with zipfile.ZipFile(file_path, 'r') as zip_ref:
                            zip_ref.extractall(root)
                    elif ext == '.rar' and RAR_SUPPORT:
                        with rarfile.RarFile(file_path, 'r') as rar_ref:
                            rar_ref.extractall(root)
                    elif ext == '.7z' and SEVENZIP_SUPPORT:
                        with py7zr.SevenZipFile(file_path, mode='r') as sz_ref:
                            sz_ref.extractall(root)

                    # 可选：删除解压后的压缩包
                    if config.DELETE_AFTER_EXTRACT:
                        os.remove(file_path)

                except Exception as e:
                    print(f"[错误] 递归解压失败 {file_name}: {e}")

def init_mysql():
    """初始化 MySQL 连接"""
    if not MYSQL_SUPPORT:
        print("[警告] pymysql 未安装，无法连接 MySQL 数据库")
        return None

    try:
        mysql_conn = pymysql.connect(**MYSQL_CONFIG)
        print("[MySQL] 连接成功")
        return mysql_conn
    except Exception as e:
        print(f"[MySQL 错误] 连接失败: {e}")
        return None

def get_standard_metadata(mysql_conn, standard_code):
    """从 MySQL 查询标准的完整元数据"""
    if not mysql_conn:
        return None

    try:
        with mysql_conn.cursor() as cursor:
            # 构建查询语句，获取所有重要元数据字段
            # 支持多种标准号格式匹配（下划线/斜杠/连字符）
            query = f"""
                SELECT
                    {MYSQL_RELEASE_DATE_FIELD},
                    {MYSQL_IMPLEMENT_DATE_FIELD},
                    {MYSQL_DRAFT_UNIT_FIELD},
                    {MYSQL_KEYWORD_FIELD},
                    chinese_name,
                    english_name,
                    standard_status,
                    release_unit,
                    charge_unit,
                    replace_standard,
                    application_scope
                FROM {MYSQL_TABLE}
                WHERE {MYSQL_STANDARD_CODE_FIELD} = %s
                   OR REPLACE(REPLACE({MYSQL_STANDARD_CODE_FIELD}, '/', '_'), '-', '_') = REPLACE(REPLACE(%s, '/', '_'), '-', '_')
                   OR REPLACE({MYSQL_STANDARD_CODE_FIELD}, '_', '/') = %s
                   OR REPLACE({MYSQL_STANDARD_CODE_FIELD}, '/', '_') = %s
                   OR REPLACE(%s, '_', '/') = REPLACE({MYSQL_STANDARD_CODE_FIELD}, '_', '/')
                   OR REPLACE(%s, '_', '/') = {MYSQL_STANDARD_CODE_FIELD}
                   OR REPLACE(SUBSTRING_INDEX({MYSQL_STANDARD_CODE_FIELD}, ' ', 1), '_', '/') = REPLACE(SUBSTRING_INDEX(%s, ' ', 1), '_', '/')
                   OR REPLACE(SUBSTRING_INDEX({MYSQL_STANDARD_CODE_FIELD}, ' ', 1), '_', '/') = REPLACE(%s, '_', '/')
                LIMIT 1
            """
            cursor.execute(query, (standard_code, standard_code, standard_code, standard_code, standard_code, standard_code, standard_code, standard_code))
            result = cursor.fetchone()

            if result:
                # 解包结果（11个字段）
                (release_date, implement_date, draft_unit, keyword,
                 chinese_name, english_name, standard_status, release_unit,
                 charge_unit, replace_standard, application_scope) = result

                # 处理日期格式
                def format_date(date_val):
                    if isinstance(date_val, datetime.date):
                        return date_val.strftime("%Y-%m-%d")
                    elif date_val is None:
                        return "未知"
                    else:
                        return str(date_val)

                # 处理空值
                def format_text(text_val):
                    if text_val is None:
                        return "未知"
                    return str(text_val)

                metadata = {
                    "release_date": format_date(release_date),
                    "implement_date": format_date(implement_date),
                    "draft_unit": format_text(draft_unit),
                    "keyword": format_text(keyword),
                    "chinese_name": format_text(chinese_name),
                    "english_name": format_text(english_name),
                    "standard_status": format_text(standard_status),
                    "release_unit": format_text(release_unit),
                    "charge_unit": format_text(charge_unit),
                    "replace_standard": format_text(replace_standard),
                    "application_scope": format_text(application_scope)
                }

                print(f"[MySQL] 查询到标准号 {standard_code}:")
                print(f"       发布日期: {metadata['release_date']}, 实施日期: {metadata['implement_date']}")
                print(f"       起草单位: {metadata['draft_unit']}, 关键词: {metadata['keyword']}")
                print(f"       中文名称: {metadata['chinese_name'][:30]}...")

                return metadata
            else:
                print(f"[MySQL 警告] 未找到标准号 {standard_code} 的元数据")
                # 返回默认元数据
                return {
                    "release_date": "未知",
                    "implement_date": "未知",
                    "draft_unit": "未知",
                    "keyword": "未知",
                    "chinese_name": "未知",
                    "english_name": "未知",
                    "standard_status": "未知",
                    "release_unit": "未知",
                    "charge_unit": "未知",
                    "replace_standard": "未知",
                    "application_scope": "未知"
                }
    except Exception as e:
        print(f"[MySQL 错误] 查询失败: {e}")
        # 返回默认元数据
        return {
            "release_date": "未知",
            "implement_date": "未知",
            "draft_unit": "未知",
            "keyword": "未知",
            "chinese_name": "未知",
            "english_name": "未知",
            "standard_status": "未知",
            "release_unit": "未知",
            "charge_unit": "未知",
            "replace_standard": "未知",
            "application_scope": "未知"
        }

def init_db():
    """初始化 PostgreSQL 数据库，创建企业级向量表（如果不存在）"""
    conn = psycopg2.connect(**config.DB_CONFIG)
    cur = conn.cursor()

    # 创建企业级向量表，包含标准号、分类及MySQL同步的完整元数据
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS policy_chunks (
            id bigserial PRIMARY KEY,
            standard_code varchar(100),  -- 核心标识1：标准号（用于跨库联动 MySQL）
            category varchar(100),       -- 核心标识2：行业关键词（从文件夹提取）
            keyword varchar(100),        -- 关键词（从MySQL同步）
            chinese_name varchar(500),   -- 中文名称（从MySQL同步）
            english_name varchar(500),   -- 英文名称（从MySQL同步）
            release_date varchar(20),    -- 发布日期（从MySQL同步）
            implement_date varchar(20),  -- 实施日期（从MySQL同步）
            standard_status varchar(50), -- 标准状态（现行/废止等）
            release_unit varchar(255),   -- 发布单位（从MySQL同步）
            charge_unit varchar(255),    -- 归口单位（从MySQL同步）
            draft_unit varchar(255),     -- 起草单位（从MySQL同步）
            replace_standard varchar(500), -- 代替标准（从MySQL同步）
            application_scope text,      -- 适用范围（从MySQL同步）
            document_name varchar(255),  -- 原始文件名（压缩包名）
            header_path text,            -- 章节层级（Markdown标题路径）
            content text,                -- 具体文本切片（原始内容）
            embedding vector({config.VECTOR_DIMENSION})  -- embedding-3 模型输出的向量
        );
    """)
    conn.commit()

    # 注册 vector 类型，让 psycopg2 能认识它
    register_vector(conn)
    return conn, cur

@exponential_backoff(max_retries=4)
def get_embedding(text):
    """调用大模型，将文字转化为向量"""
    global client
    # 如果 client 未初始化，则初始化
    if client is None:
        client = ZhipuAI(api_key=config.ZHIPU_API_KEY)

    response = client.embeddings.create(
        model=config.EMBEDDING_MODEL,  # 当前应为 "embedding-3"
        input=text[:2000]  # 限制输入长度
    )
    return response.data[0].embedding

def process_markdown_file(file_path, conn, cur, mysql_conn=None):
    """读取、提取元数据、切片并存入数据库（企业级双库联动版本）"""
    # ================= 1. 智能元数据提取 =================
    # 文件路径示例: md_extracted_safe/崩塌/DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南/full.md
    # 或: md_extracted/... 兼容旧路径

    # 提取分类（祖父目录名）
    parent_dir = os.path.dirname(file_path)
    category = os.path.basename(parent_dir)

    # 如果父目录是解压根目录（如 md_extracted_safe），则尝试向上查找分类
    if category in ["md_extracted", "md_extracted_safe"] or not category:
        # 再向上找一级
        grandparent_dir = os.path.dirname(parent_dir)
        category = os.path.basename(grandparent_dir)
        if category in ["md_extracted", "md_extracted_safe"] or not category:
            category = "未分类"

    # 提取标准信息（从父目录名）
    parent_dir_name = os.path.basename(parent_dir)
    # 父目录名格式: "DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南"
    # 标准号可能包含空格，如 "DB61_T 1533-2022" 或 "GB/T 12345-2020"
    # 使用正则表达式匹配标准号（通常包含字母、数字、斜杠、下划线、连字符）
    # 匹配模式：字母开头 + 可选数字 + 可选分隔符 + 可选字母 + 可选空格 + 数字-数字
    match = re.match(r'^([A-Z]+\d*[/._]?[A-Z]*\s*\d+[—\-]\d+)(?:\s+(.+))?$', parent_dir_name, re.IGNORECASE)
    if match:
        standard_code = match.group(1).strip()  # 标准号: DB61_T 1533-2022
        standard_name = match.group(2) if match.group(2) else ""  # 标准名
    else:
        # 回退到简单的空格分割（取第一部分作为标准号）
        parts = parent_dir_name.split(' ', 1)
        if len(parts) >= 2:
            standard_code = parts[0]
            standard_name = parts[1]
        else:
            standard_code = parent_dir_name
            standard_name = parent_dir_name

    # 文档名（使用压缩包文件名作为唯一标识）
    # 构建压缩包文件名: "DB61_T 1533-2022 公路上边坡崩塌滑坡灾害风险评估指南.zip"
    zip_file_name = f"{parent_dir_name}.zip"

    print(f"\n[处理] 正在处理: {zip_file_name}")
    print(f"       [文件] 文件路径: {file_path}")
    print(f"       [元数据] 提取元数据 -> 分类: [{category}] | 标准号: [{standard_code}]")

    # ================= 2. 查询 MySQL 元数据 =================
    # 默认元数据（当MySQL未连接或查询失败时使用）
    default_metadata = {
        "release_date": "未知",
        "implement_date": "未知",
        "draft_unit": "未知",
        "keyword": "未知",
        "chinese_name": "未知",
        "english_name": "未知",
        "standard_status": "未知",
        "release_unit": "未知",
        "charge_unit": "未知",
        "replace_standard": "未知",
        "application_scope": "未知"
    }

    mysql_metadata = default_metadata.copy()

    if mysql_conn:
        metadata_result = get_standard_metadata(mysql_conn, standard_code)
        if metadata_result:
            mysql_metadata.update(metadata_result)
            print(f"       [MySQL] MySQL元数据同步完成")
            print(f"          关键词: [{mysql_metadata['keyword']}]")
            print(f"          发布日期: [{mysql_metadata['release_date']}] | 实施日期: [{mysql_metadata['implement_date']}]")
            print(f"          起草单位: [{mysql_metadata['draft_unit']}] | 状态: [{mysql_metadata['standard_status']}]")
    else:
        print(f"       [警告] MySQL未连接，使用默认元数据")

    # ================= 3. 幂等性删除（防止重复数据） =================
    # 删除该标准的所有旧记录（基于标准号和分类）
    try:
        cur.execute(
            """DELETE FROM policy_chunks
               WHERE standard_code = %s AND category = %s""",
            (standard_code, category)
        )
        deleted_count = cur.rowcount
        if deleted_count > 0:
            print(f"       [清理] 幂等性清理: 删除 {deleted_count} 条旧记录")
        conn.commit()
    except Exception as e:
        print(f"[警告] 幂等性删除失败: {e}")
        conn.rollback()

    # ================= 4. 读取与切分 Markdown =================
    with open(file_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 语义切分：按 Markdown 的标题层级来切
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=config.HEADERS_TO_SPLIT_ON)
    md_header_splits = markdown_splitter.split_text(md_text)

    # 长度控制
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)
    final_chunks = text_splitter.split_documents(md_header_splits)

    # ================= 5. 向量化与入库 =================
    insert_count = 0
    for chunk in final_chunks:
        content = chunk.page_content
        metadata = chunk.metadata

        # 构建标题层级路径
        header_path_str = " > ".join([f"{k}: {v}" for k, v in metadata.items()])

        # 注入元数据到内容头部（增强检索效果）
        # 格式: [标准号: ...][分类: ...][关键词: ...][中文名称: ...][发布日期: ...][实施日期: ...][起草单位: ...][状态: ...]\n\n原文内容
        enriched_content = (
            f"[标准号: {standard_code}]"
            f"[分类: {category}]"
            f"[关键词: {mysql_metadata['keyword']}]"
            f"[中文名称: {mysql_metadata['chinese_name']}]"
            f"[发布日期: {mysql_metadata['release_date']}]"
            f"[实施日期: {mysql_metadata['implement_date']}]"
            f"[起草单位: {mysql_metadata['draft_unit']}]"
            f"[标准状态: {mysql_metadata['standard_status']}]"
            f"\n\n{content}"
        )

        # 生成向量（使用增强后的内容）
        vector = get_embedding(enriched_content)

        if vector:
            cur.execute(
                """INSERT INTO policy_chunks
                   (standard_code, category, keyword, chinese_name, english_name,
                    release_date, implement_date, standard_status, release_unit,
                    charge_unit, draft_unit, replace_standard, application_scope,
                    document_name, header_path, content, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (standard_code, category, mysql_metadata['keyword'], mysql_metadata['chinese_name'], mysql_metadata['english_name'],
                 mysql_metadata['release_date'], mysql_metadata['implement_date'], mysql_metadata['standard_status'], mysql_metadata['release_unit'],
                 mysql_metadata['charge_unit'], mysql_metadata['draft_unit'], mysql_metadata['replace_standard'], mysql_metadata['application_scope'],
                 zip_file_name, header_path_str, content, vector)  # 注意：content 存储原始内容，enriched_content 仅用于向量化
            )
            insert_count += 1

    conn.commit()
    print(f"[完成] {zip_file_name} 入库完成，生成 {insert_count} 个语义切片。")

def main():
    print("[开始] 开始企业级知识库构建流程（双库联动版本）...")

    # ================= 第一步：安全解压压缩包 =================
    print("\n[阶段1] 安全解压压缩包（按分类/标准名创建独立目录）...")
    extract_dir = safe_extract_archives()
    print(f"[目录] 安全解压目录: {extract_dir}")

    # 检查解压目录中是否有 .md 文件
    md_files = []
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.endswith('.md'):
                md_files.append(os.path.join(root, file))

    if not md_files:
        print("[警告] 目录中没有找到 .md 文件，请检查路径。")
        return

    print(f"[文档] 找到 {len(md_files)} 个 .md 文件准备入库...")

    # ================= 第二步：初始化 MySQL 连接 =================
    print("\n[阶段2] 初始化 MySQL 连接（用于获取元数据）...")
    mysql_conn = None
    if MYSQL_SUPPORT:
        mysql_conn = init_mysql()
        if mysql_conn:
            print("[MySQL] 连接成功，准备查询元数据")
        else:
            print("[MySQL] 连接失败，将继续处理但无法获取实施日期和起草单位")
    else:
        print("[MySQL] pymysql 未安装，跳过 MySQL 元数据查询")

    # ================= 第三步：初始化大模型客户端和 PostgreSQL =================
    print("\n[阶段3] 初始化大模型客户端和 PostgreSQL 向量数据库...")
    global client
    client = ZhipuAI(api_key=config.ZHIPU_API_KEY)
    conn, cur = init_db()
    print("[PostgreSQL] 连接成功，表结构已就绪")

    # ================= 第四步：处理所有 md 文件 =================
    print("\n[阶段4] 开始处理 Markdown 文件（双库联动）...")
    processed_count = 0
    for md_file in md_files:
        try:
            process_markdown_file(md_file, conn, cur, mysql_conn)
            processed_count += 1
        except Exception as e:
            print(f"[错误] 处理文件失败 {md_file}: {e}")
            # 继续处理其他文件

    # ================= 第五步：资源清理与统计 =================
    print("\n[阶段5] 资源清理与统计...")
    cur.close()
    conn.close()
    if mysql_conn:
        mysql_conn.close()
        print("[MySQL] 连接已关闭")

    print(f"\n[大功告成] 企业级知识库构建完成！")
    print(f"  总计处理文件: {processed_count}/{len(md_files)}")
    print(f"  安全解压目录: {extract_dir}")
    print(f"  向量表: policy_chunks (包含标准号、分类、实施日期、起草单位字段)")
    print(f"  下次运行将自动执行幂等性清理，确保数据无重复")

if __name__ == "__main__":
    main()