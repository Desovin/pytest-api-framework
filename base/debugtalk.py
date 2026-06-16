"""
模块 7：热加载函数（对标 Test-Automation-Framework 的 DebugTalk）

作用：提供 YAML 中 ${函数名()} 占位符的运行时实现。

Token 管理设计（模块 7 核心）：
1. 配置化：账号密码从 config.ini 读取，不再硬编码
2. 三层缓存：
   - 内存缓存（_cache）：同进程最快
   - Redis 缓存：支持 pytest-xdist 多进程共享 token
   - extract.yaml：兼容原项目 ${get_extract_data(token)} 用法
3. 过期检测：token 带过期时间，过期自动刷新
4. 401 兜底：SendRequest 检测到 401 时回调刷新 token

面试拓展（暂未实现，可聊）：
- 多角色支持：get_token(role='admin') 从配置读取不同账号
- Mock Server 端 token 持久化：用 Redis 替代全局变量 SESSION_TOKEN
"""

import time
from common.send_request import SendRequest
from common.read_yaml import get_extract, write_extract
from common.connection import ConnectRedis
from common.record_log import get_logger
from conf.setting import API_HOST, LOGIN_CONFIG, TOKEN_EXPIRE_SECONDS, REDIS_ENABLED

logger = get_logger(__name__)

_client = SendRequest(base_url=API_HOST)

# Token 缓存：内存级，同进程内共享
# 结构：{'token': str, 'expire_at': float}
_cache = {}


def _redis_token_key():
    """Redis 中缓存 token 的 key，按用户名区分"""
    return f"auto_test:token:{LOGIN_CONFIG['user_name']}"


def _get_token_from_redis():
    """从 Redis 读取 token。Redis 未启用或读取失败返回 None。"""
    if not REDIS_ENABLED:
        return None
    try:
        r = ConnectRedis()
        value = r.get(_redis_token_key())
        if value:
            logger.debug('从 Redis 命中 token')
        return value
    except Exception as e:
        logger.warning('从 Redis 读取 token 失败: %s', e)
        return None


def _save_token_to_redis(token):
    """将 token 写入 Redis，带过期时间。"""
    if not REDIS_ENABLED or not token:
        return
    try:
        r = ConnectRedis()
        # Redis 自动过期，避免脏 token 长期残留
        r.set(_redis_token_key(), token, expire=TOKEN_EXPIRE_SECONDS)
        logger.debug('token 已写入 Redis，过期时间 %s 秒', TOKEN_EXPIRE_SECONDS)
    except Exception as e:
        logger.warning('token 写入 Redis 失败: %s', e)


class DebugTalk:
    """
    热加载函数集合。
    每个方法对应 YAML 中的一个 ${方法名(参数)} 占位符。
    """

    @staticmethod
    def get_login_user():
        """
        获取配置文件中的登录用户名。

        对应 YAML: ${get_login_user()}
        """
        return LOGIN_CONFIG['user_name']

    @staticmethod
    def get_login_pass():
        """
        获取配置文件中的登录密码。

        对应 YAML: ${get_login_pass()}
        """
        return LOGIN_CONFIG['password']

    @staticmethod
    def get_token(refresh=False):
        """
        获取登录 token，支持内存缓存、Redis 缓存、过期自动刷新。

        :param refresh: 是否强制刷新（比如收到 401 后重试）
        :return: token 字符串

        查找顺序：
        1. 强制刷新 → 直接登录
        2. 内存缓存未过期 → 直接返回
        3. Redis 缓存存在 → 写回内存并返回
        4. 以上都未命中 → 调登录接口重新获取
        """
        # 1. 强制刷新：跳过所有缓存
        if refresh:
            logger.info('强制刷新 token')
            return DebugTalk._login_and_cache()

        # 2. 内存缓存 + 过期判断
        now = time.time()
        cached_token = _cache.get('token')
        expire_at = _cache.get('expire_at', 0)
        if cached_token and now < expire_at:
            logger.debug('从内存缓存命中 token')
            return cached_token

        # 3. Redis 缓存（支持多进程共享）
        redis_token = _get_token_from_redis()
        if redis_token:
            _cache['token'] = redis_token
            _cache['expire_at'] = now + TOKEN_EXPIRE_SECONDS
            logger.debug('从 Redis 命中 token 并写回内存缓存')
            return redis_token

        # 4. 缓存全部未命中，重新登录
        logger.info('token 缓存未命中，执行登录')
        return DebugTalk._login_and_cache()

    @staticmethod
    def _login_and_cache():
        """
        调登录接口，并将 token 写入内存缓存 + Redis + extract.yaml。

        为什么同时写 extract.yaml？
        兼容原项目 ${get_extract_data(token)} 占位符用法。
        """
        resp = _client.post(
            "/dar/user/login",
            data={
                "user_name": LOGIN_CONFIG['user_name'],
                "passwd": LOGIN_CONFIG['password']
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if resp is None:
            logger.error('登录请求失败')
            return ''

        token = resp['json'].get('token', '')
        if not token:
            logger.error('登录响应中未找到 token')
            return ''

        now = time.time()
        _cache['token'] = token
        _cache['expire_at'] = now + TOKEN_EXPIRE_SECONDS

        # 写入 Redis，多进程共享
        _save_token_to_redis(token)

        # 写入 extract.yaml，兼容原项目占位符
        write_extract({'token': token})
        logger.info('登录成功，token 已缓存')
        return token

    @staticmethod
    def get_extract_data(key):
        """
        从 extract.yaml 读取指定 key 的值。

        对应 YAML 中的 ${get_extract_data(token)} 占位符。
        用于接口依赖场景：上一个接口提取了 token 到 extract.yaml，
        下一个接口通过此方法读取。

        :param key: extract.yaml 中的键名
        :return: 值，未找到则返回空字符串
        """
        value = get_extract(key)
        return value if value is not None else ''
