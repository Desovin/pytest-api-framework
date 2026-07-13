"""
读取 config.ini，提供全局配置对象。

为什么单独开 setting.py 而不是到处 import configparser？
1. 如果配置文件格式变了（ini → yaml → 环境变量），只改这一个文件
2. setting.API_HOST 比每次 conf.get('api_env', 'host') 简洁
3. 可以在此做类型转换和默认值处理
"""

import os
import configparser     #读取.ini配置文件的库
from dotenv import load_dotenv    #从 .env 文件加载敏感配置

# 项目根目录（conf/ 的上级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 加载 .env 文件（敏感信息不写入 config.ini，不提交到 Git）
# .env 不存在时 load_dotenv 静默跳过，不影响运行
load_dotenv(os.path.join(BASE_DIR, '.env'))

# 读取 config.ini（非敏感配置仍然走 ini）
_ini_path = os.path.join(BASE_DIR, 'conf', 'config.ini')    #拼接路径
_ini = configparser.ConfigParser()  # 创建一个配置对象
_ini.read(_ini_path, encoding='utf-8')  

# ── 暴露给外部的配置 ──
API_HOST = _ini.get('api_env', 'host')
API_TIMEOUT = _ini.getint('timeout', 'api_timeout')
LOG_LEVEL = _ini.get('log', 'level')
LOG_DIR = _ini.get('log', 'dir')
REPORT_TYPE = _ini.get('report', 'type')

# ══ MySQL 配置 ══
# 密码走环境变量（.env / CI Secrets），不硬编码在 config.ini
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', _ini.get('mysql', 'host')),
    'port': int(os.getenv('MYSQL_PORT', _ini.get('mysql', 'port'))),
    'user': os.getenv('MYSQL_USER', _ini.get('mysql', 'user')),
    'password': os.getenv('MYSQL_PASSWORD', _ini.get('mysql', 'password', fallback='')),
    'database': os.getenv('MYSQL_DATABASE', _ini.get('mysql', 'database')),
}
MYSQL_ENABLED = _ini.getboolean('mysql', 'enabled')

# ══ Redis 配置 ══
# 密码走环境变量（.env / CI Secrets），空字符串 → None（无密码连接）
REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', _ini.get('redis', 'host')),
    'port': int(os.getenv('REDIS_PORT', _ini.get('redis', 'port'))),
    'password': (os.getenv('REDIS_PASSWORD', _ini.get('redis', 'password', fallback='')) or None),
    'db': int(os.getenv('REDIS_DB', _ini.get('redis', 'db'))),
}
REDIS_ENABLED = _ini.getboolean('redis', 'enabled')

# ══ 登录账号配置 ══
# 密码走环境变量（.env / CI Secrets），不硬编码在 config.ini
LOGIN_CONFIG = {
    'user_name': os.getenv('LOGIN_USER_NAME', _ini.get('login', 'user_name')),
    'password': os.getenv('LOGIN_PASSWORD', _ini.get('login', 'password', fallback='')),
}

# Token 缓存过期时间（秒）
TOKEN_EXPIRE_SECONDS = _ini.getint('token', 'token_expire_seconds')

# ══ 钉钉通知配置 ══
# CI/CD 环境下通过环境变量覆盖，避免把真实 webhook 写入配置文件
DINGTALK_ENABLED = os.getenv(
    'DINGTALK_ENABLED',
    _ini.get('dingtalk', 'enabled', fallback='false')
).lower() in ('true', '1', 'yes', 'on')
DINGTALK_WEBHOOK = os.getenv('DINGTALK_WEBHOOK', _ini.get('dingtalk', 'webhook', fallback=''))
DINGTALK_SECRET = os.getenv('DINGTALK_SECRET', _ini.get('dingtalk', 'secret', fallback=''))
DINGTALK_ONLY_ON_FAILURE = os.getenv(
    'DINGTALK_ONLY_ON_FAILURE',
    _ini.get('dingtalk', 'only_on_failure', fallback='false')
).lower() in ('true', '1', 'yes', 'on')

# ══ Mock Server 启动配置 ══
# 测试框架和被测服务共用 config.ini，方便后续统一切换 debug/端口
MOCK_SERVER_HOST = _ini.get('mock_server', 'host', fallback='127.0.0.1')
MOCK_SERVER_PORT = _ini.getint('mock_server', 'port', fallback=8787)
MOCK_SERVER_DEBUG = _ini.getboolean('mock_server', 'debug', fallback=False)

# 常用路径，统一管理
FILE_PATH = {
    'LOG': os.path.join(BASE_DIR, LOG_DIR),
    'CONFIG': _ini_path,
}
