"""
模块 10：数据库连接 —— MySQL 操作封装

对标 Test-Automation-Framework 的 common/connection.py（支持 MySQL/Redis/ClickHouse/MongoDB）

为什么需要数据库断言？
- 接口返回 200 不代表数据真落库了 —— 可能异常被吞、缓存未刷、主从延迟
- 查库验证数据确实存在，才是真正的"端到端"验证
- 面试时能讲清楚"接口测试不止于接口返回"是加分项

为什么用 PyMySQL？
- 纯 Python 实现的 MySQL 驱动，pip install 即用
- 接口和 MySQLdb 兼容，未来换 mysql-connector-python 改动极小
"""

import pymysql
import redis
from common.record_log import get_logger
from conf.setting import MYSQL_CONFIG, MYSQL_ENABLED, REDIS_CONFIG, REDIS_ENABLED

logger = get_logger(__name__)


class ConnectMysql:
    """
    MySQL 数据库操作封装。

    使用方式：
        db = ConnectMysql()
        db.execute("INSERT INTO sys_user (...) VALUES (...)")
        result = db.query_one("SELECT * FROM sys_user WHERE username=%s", (name,))
        db.close()

    参数化查询：用 %s 做占位符，PyMySQL 自动处理转义，防 SQL 注入。
    """

    def __init__(self, config=None):
        self.config = config or MYSQL_CONFIG
        self._conn = None
        self._cursor = None

    # ── 连接管理 ──

    def connect(self):
        """建立数据库连接"""
        if not MYSQL_ENABLED:
            logger.warning('MySQL 未启用（config.ini 中 mysql.enabled=false）')
            return False
        try:
            self._conn = pymysql.connect(
                host=self.config['host'],
                port=self.config['port'],
                user=self.config['user'],
                password=self.config['password'],
                database=self.config['database'],
                charset='utf8mb4',
                # 让查询结果返回 dict 而非 tuple，方便断言
                cursorclass=pymysql.cursors.DictCursor
            )
            # _conn 是连接池，_cursor 是游标，用于执行 SQL 语句和获取结果集
            self._cursor = self._conn.cursor()
            logger.debug('MySQL 连接成功: {}:{}/{}',
                         self.config['host'], self.config['port'], self.config['database'])
            return True
        except pymysql.Error as e:
            logger.error('MySQL 连接失败: {}', e)
            return False

    def close(self):
        """关闭连接，释放资源"""
        if self._cursor:
            self._cursor.close()
        if self._conn:
            self._conn.close()
            logger.debug('MySQL 连接已关闭')

    # ── 数据操作 ──

    def execute(self, sql, params=None):
        """
        执行写操作（INSERT/UPDATE/DELETE）。

        为什么参数化查询防 SQL 注入？
        拼接："SELECT * FROM user WHERE name='" + name + "'"
              → name="'; DROP TABLE user; --" → 删表
        参数化：cursor.execute(sql, (name,))
              → PyMySQL 自动转义特殊字符，当普通字符串处理
        """
        if not self.connect():
            return
        try:
            if params:
                self._cursor.execute(sql, params)
            else:
                self._cursor.execute(sql)
            self._conn.commit()  # 提交事务 commit
            logger.debug('执行成功: {}', sql[:80])
        except pymysql.Error as e:
            self._conn.rollback()
            logger.error('执行失败: {}, 错误: {}', sql[:80], e)
            raise
        finally:
            self.close()

    # ── 数据查询 ──

    def query_one(self, sql, params=None):
        """
        查询单条记录。

        :return: dict（找到）或 None（未找到）
        断言引擎用此方法做 db 断言：查到了 = 数据落库成功
        """
        if not self.connect():
            return None
        try:
            if params:
                self._cursor.execute(sql, params)
            else:
                self._cursor.execute(sql)
            return self._cursor.fetchone()
        except pymysql.Error as e:
            logger.error('查询失败: {}', e)
            return None
        finally:
            self.close()

    def query_all(self, sql, params=None):
        """
        查询所有匹配记录。

        :return: list[dict]，未找到返回空列表
        """
        if not self.connect():
            return []
        try:
            if params:
                self._cursor.execute(sql, params)
            else:
                self._cursor.execute(sql)
            return self._cursor.fetchall()
        except pymysql.Error as e:
            logger.error('查询失败: {}', e)
            return []
        finally:
            self.close()

    # ── 测试辅助 ──

    def delete(self, sql, params=None):
        """
        删除数据 —— 用于数据清理（测试后删掉测试数据）。

        为什么需要数据清理？
        测试往数据库里插了脏数据，不清理会越积越多，
        甚至影响下次测试（同名唯一约束冲突）。
        """
        self.execute(sql, params)


# ═══════════════════════════════════════════════════
# Redis 连接封装
# ═══════════════════════════════════════════════════


class ConnectRedis:
    """
    Redis 内存数据库操作封装。

    Redis 和 MySQL 的区别（面试常问）：
    - MySQL：关系型数据库，存磁盘，用 SQL 查询，适合持久化存储
    - Redis：键值对内存库，读写极快，适合缓存、Session、计数器、消息队列

    测试场景示例：
    1. 登录成功后 token 写入 Redis → 查 Redis 验证 token 存在
    2. 验证码存入 Redis → 查 Redis 验证验证码正确性
    3. 用户操作频率限制（Redis 计数器）→ 验证限制生效
    """

    def __init__(self, config=None):
        self.config = config or REDIS_CONFIG
        self._client = None

    def connect(self):
        """建立 Redis 连接"""
        if not REDIS_ENABLED:
            logger.warning('Redis 未启用（config.ini 中 redis.enabled=false）')
            return False
        try:
            self._client = redis.Redis(
                host=self.config['host'],
                port=self.config['port'],
                password=self.config['password'],
                db=self.config['db'],
                decode_responses=True  # 自动把 bytes 解码成 str，告别 b'xxx'
            )
            # ping 一下确认连接真的通了
            self._client.ping()
            logger.debug('Redis 连接成功: {}:{}', self.config['host'], self.config['port'])
            return True
        except redis.RedisError as e:
            logger.error('Redis 连接失败: {}', e)
            return False

    def close(self):
        """关闭连接"""
        if self._client:
            self._client.close()
            logger.debug('Redis 连接已关闭')

    # ── 字符串操作（最常用）──

    def set(self, key, value, expire=None):
        """
        写入键值对。expire 是过期秒数，如 3600=1小时后自动删除。
        token 通常设过期时间，防止 Redis 无限膨胀。
        """
        if not self.connect():
            return
        try:
            self._client.set(key, value, ex=expire)
            logger.debug('Redis SET: {} = {}', key, value)
        except redis.RedisError as e:
            logger.error('Redis SET 失败: {}', e)
        finally:
            self.close()

    def get(self, key):
        """
        读取键值，键不存在返回 None。
        断言引擎用此方法做 Redis 断言：get 到值 = 缓存写入成功。
        """
        if not self.connect():
            return None
        try:
            value = self._client.get(key)
            return value
        except redis.RedisError as e:
            logger.error('Redis GET 失败: {}', e)
            return None
        finally:
            self.close()

    def delete(self, key):
        """
        删除键，用于测试数据清理。
        数据清理和 MySQL 同理 —— 测试产生的 key 要清理，防止越积越多。
        """
        if not self.connect():
            return
        try:
            self._client.delete(key)
            logger.debug('Redis DELETE: {}', key)
        except redis.RedisError as e:
            logger.error('Redis DELETE 失败: {}', e)
        finally:
            self.close()

    # ── 哈希操作 ──

    def hset(self, name, key, value):
        """
        Redis Hash —— 给一个 hash 表（name）里的某个字段（key）赋值。

        场景：存储用户 Session 信息
          hset('session:userId:xxx', 'token', 'abc123')
          hset('session:userId:xxx', 'login_time', '2026-06-01')
        """
        if not self.connect():
            return
        try:
            self._client.hset(name, key, value)
        except redis.RedisError as e:
            logger.error('Redis HSET 失败: {}', e)
        finally:
            self.close()

    def hget(self, name, key):
        """读取 Hash 表中的字段值"""
        if not self.connect():
            return None
        try:
            return self._client.hget(name, key)
        except redis.RedisError as e:
            logger.error('Redis HGET 失败: {}', e)
            return None
        finally:
            self.close()
