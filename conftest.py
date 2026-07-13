"""
项目根级 pytest 配置（conftest.py）。

pytest 作用域说明：
- function：每个测试函数执行一次（默认）
- session：整个测试会话执行一次（跨文件共享）
"""

import os
import time
import pytest
import allure
from common.record_log import get_logger
from common.read_yaml import clear_extract
from common.ding_robot import send_dingtalk, build_summary_from_terminalreporter

logger = get_logger(__name__)

# 模块加载时记录会话开始时间，用于计算总耗时
# 不依赖 pytest 内部属性（pytest 9.x 中 _sessionstarttime 已改名且类型变化）
_SESSION_START = time.time()


@pytest.fixture(scope="session", autouse=True)
def global_setup():
    """
    session 级别前置/后置。

    前置：清空 extract.yaml（避免上次运行残留数据干扰）
    后置：打印会话结束标记
    """
    clear_extract()
    logger.info('========== 测试会话开始 ==========')
    yield
    logger.info('========== 测试会话结束 ==========')


@pytest.fixture(autouse=True)
def case_log():
    """每个用例前后打印日志分隔线"""
    logger.info('------------- 用例开始 -------------')
    yield
    logger.info('------------- 用例结束 -------------')


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    pytest 会话结束时发送钉钉通知（模块 13）。

    这个 hook 在测试全部跑完之后、pytest 退出之前执行，
    可以拿到最终的通过/失败/跳过统计。

    :param terminalreporter: pytest 的 TerminalReporter，包含测试结果统计
    :param exitstatus: pytest 退出码
    :param config: pytest 配置对象
    """
    duration = time.time() - _SESSION_START
    summary = build_summary_from_terminalreporter(terminalreporter, duration)

    # CI/CD 环境下，GitHub Actions 会把报告链接注入 REPORT_URL；
    # 本地跑时默认给 Allure HTTP 服务地址，方便点击链接查看报告。
    summary['report_url'] = os.getenv(
        'REPORT_URL',
        'http://127.0.0.1:19200/index.html'
    )

    logger.info(
        '测试会话结束统计: 总={}, 通过={}, 失败={}, 跳过={}, 耗时={:.2f}s',
        summary['total'], summary['passed'], summary['failed'],
        summary['skipped'], duration
    )

    # 发送钉钉通知（如果未启用或配置不完整，内部会记录日志并跳过）
    send_dingtalk(summary)
