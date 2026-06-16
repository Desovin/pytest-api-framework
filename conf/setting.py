"""
读取 config.ini，提供全局配置对象。

为什么单独开 setting.py 而不是到处 import configparser？
1. 如果配置文件格式变了（ini → yaml → 环境变量），只改这一个文件
2. setting.API_HOST 比每次 conf.get('api_env', 'host') 简洁
3. 可以在此做类型转换和默认值处理
"""

import os
import configparser     #读取.ini配置文件的库

# 项目根目录（conf/ 的上级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 读取 config.ini
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
MYSQL_CONFIG = {
    'host': _ini.get('mysql', 'host'),
    'port': _ini.getint('mysql', 'port'),
    'user': _ini.get('mysql', 'user'),
    'password': _ini.get('mysql', 'password'),
    'database': _ini.get('mysql', 'database'),
}
MYSQL_ENABLED = _ini.getboolean('mysql', 'enabled')

# ══ Redis 配置 ══
REDIS_CONFIG = {
    'host': _ini.get('redis', 'host'),
    'port': _ini.getint('redis', 'port'),
    'password': _ini.get('redis', 'password') or None,  # 空字符串 → None（无密码连接）
    'db': _ini.getint('redis', 'db'),
}
REDIS_ENABLED = _ini.getboolean('redis', 'enabled')

# ══ 登录账号配置 ══
LOGIN_CONFIG = {
    'user_name': _ini.get('login', 'user_name'),
    'password': _ini.get('login', 'password'),
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

# 常用路径，统一管理
FILE_PATH = {
    'LOG': os.path.join(BASE_DIR, LOG_DIR),
    'CONFIG': _ini_path,
}
