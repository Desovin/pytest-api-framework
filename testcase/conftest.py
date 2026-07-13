"""
用例层 conftest.py（对标 Test-Automation-Framework 的 testcase/conftest.py）
"""

import pytest
import allure
import requests
from common.record_log import get_logger
from common.read_yaml import get_testcase_yaml, clear_extract, write_extract
from common.connection import ConnectMysql, ConnectRedis
from conf.setting import MYSQL_ENABLED, REDIS_ENABLED, API_HOST
from base.apiutil import RequestBase

logger = get_logger(__name__)


@pytest.fixture(scope='session', autouse=True)
def clear_extract_file():
    """
    会话级清空 extract.yaml。

    为什么需要？
    工作流用例通过 extract.yaml 在多个接口之间传递数据（token、orderNumber、waybillNo）。
    如果会话开始前不清空，上次测试残留的数据会污染本次工作流，导致断言失败。
    """
    clear_extract()
    logger.info('extract.yaml 已清空')
    yield


@pytest.fixture(autouse=True)
def start_test_and_end():
    """每个用例前后打印日志分隔线"""
    logger.info('------------- 用例开始 -------------')
    yield
    logger.info('------------- 用例结束 -------------')


@pytest.fixture(scope='session', autouse=True)
@allure.story("登录")
def system_login():
    """session 级别登录前置 —— 一次登录全局复用"""
    try:
        api_info = get_testcase_yaml('./data/login_data.yaml')
        logger.info('执行 session 级登录...')
        RequestBase().specification_yaml(api_info[0][0], api_info[0][1])
    except Exception as e:
        logger.error('登录失败，后续接口可能无法运行: {}', e)


@pytest.fixture(scope='session', autouse=True)
def logistics_seed(system_login):
    """
    创建一个物流运单种子，供只读类单接口（track/cost/exception）使用。

    单接口用例若按 (baseInfo,testCase) 独立参数化，则无法像工作流那样在 YAML 内创建运单。
    因此由 session fixture 预先创建一个运单，提取到 wb_seed 供 YAML 占位符使用。
    """
    try:
        resp = requests.post(
            f'{API_HOST}/logistics/create',
            json={
                'goodsId': '18382788819',
                'quantity': 1,
                'fromAddr': '深圳市',
                'toAddr': '北京市',
                'consignee': '种子用户'
            },
            timeout=10
        )
        data = resp.json()
        wb_seed = data.get('waybillNo')
        if wb_seed:
            write_extract({'wb_seed': wb_seed})
            logger.info('物流种子运单已创建: {}', wb_seed)
    except Exception as e:
        logger.warning('物流种子运单创建失败: {}', e)


@pytest.fixture(scope='session', autouse=True)
def db_init():
    """
    数据库前置/后置处理。

    前置：建表（如果表不存在）
    后置：清理本次测试产生的脏数据

    为什么需要数据清理？
    测试往数据库插了测试数据，不清理会越积越多，
    影响下次测试（如唯一约束冲突）、占用磁盘空间。
    """
    if not MYSQL_ENABLED:
        logger.info('MySQL 未启用，跳过数据库 fixture')
        yield
        return

    db = ConnectMysql()
    # 前置：建表
    db.execute("""
        CREATE TABLE IF NOT EXISTS sys_user (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL,
            password VARCHAR(100) NOT NULL,
            role_id INT,
            phone VARCHAR(20),
            create_time VARCHAR(50)
        )
    """)
    logger.info('sys_user 表已就绪')

    yield  # ← 测试在这里执行

    # 后置：清理测试数据
    db.execute("DELETE FROM sys_user WHERE username LIKE 'test_%'")
    logger.info('测试数据已清理')


@pytest.fixture(scope='session', autouse=True)
def redis_cleanup():
    """
    Redis 数据清理。

    测试结束后删除所有 test_ 前缀的 key。
    和 MySQL 清理同理——不清理的话 Redis 里越积越多。
    """
    yield  # 等所有测试执行完
    if REDIS_ENABLED:
        r = ConnectRedis()
        if r.connect():
            # KEYS * 是危险操作（生产环境会阻塞 Redis），
            # 但测试环境 Redis 只有我们自己的 key，安全
            r._client.delete('token:test01')
            logger.info('Redis 测试数据已清理')
            r.close()
