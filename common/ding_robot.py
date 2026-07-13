"""
模块 13：钉钉机器人通知

功能：测试结束后把结果推送到钉钉群。

为什么用钉钉机器人而不是邮件？
1. 实时性强 —— 测试结果一出就推送到群
2. 触达率高 —— 开发/测试都在群里，不容易漏看
3. 格式丰富 —— 支持 markdown、链接、@指定人

安全机制：
钉钉自定义机器人支持三种安全设置：
1. 自定义关键词
2. 加签（sign）—— 我们用的方式
3. IP 白名单

加签算法：
- timestamp = 当前时间戳（毫秒）
- string_to_sign = f"{timestamp}\n{secret}"
- sign = base64(hmac_sha256(string_to_sign, secret))
- sign = urlencode(sign)
"""

import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from common.record_log import get_logger
from conf.setting import DINGTALK_ENABLED, DINGTALK_WEBHOOK, DINGTALK_SECRET, DINGTALK_ONLY_ON_FAILURE

logger = get_logger(__name__)


def _sign(secret: str) -> tuple:
    """
    生成钉钉加签参数。

    :param secret: 钉钉机器人安全设置里的加签密钥
    :return: (timestamp, sign)
    """
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = base64.b64encode(
        hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
    ).decode('utf-8')
    sign = urllib.parse.quote(sign)
    return timestamp, sign


def _build_markdown_content(summary: dict) -> str:
    """
    构造 markdown 格式的通知内容。

    :param summary: {
        'total': 总用例数,
        'passed': 通过数,
        'failed': 失败数,
        'skipped': 跳过数,
        'duration': 耗时秒数,
        'report_url': 报告链接,
        'failed_cases': 失败用例名列表（可选）
    }
    :return: markdown 字符串
    """
    total = summary['total']
    passed = summary['passed']
    failed = summary['failed']
    skipped = summary['skipped']
    duration = summary.get('duration', 0)
    report_url = summary.get('report_url', '')
    failed_cases = summary.get('failed_cases', [])

    # 根据失败情况决定标题颜色
    if failed == 0:
        title = "🟢 接口自动化测试全部通过"
    elif failed == total:
        title = "🔴 接口自动化测试全部失败"
    else:
        title = "🟡 接口自动化测试部分失败"

    content = (
        f"## {title}\n\n"
        f"**总用例数**：{total}\n\n"
        f"**通过**：{passed}  |  **失败**：{failed}  |  **跳过**：{skipped}\n\n"
        f"**耗时**：{duration:.2f} 秒\n\n"
    )

    if report_url:
        content += f"**[点击查看 Allure 报告]({report_url})**\n\n"

    if failed > 0 and failed_cases:
        content += "**失败用例**：\n\n"
        # 最多列出 10 个失败用例，避免消息太长被钉钉截断
        for case in failed_cases[:10]:
            content += f"- {case}\n"
        if len(failed_cases) > 10:
            content += f"- ... 还有 {len(failed_cases) - 10} 个失败用例\n"
        content += "\n请尽快排查。"
    elif failed > 0:
        content += "请尽快排查失败用例。"

    return content


def send_dingtalk(summary: dict) -> bool:
    """
    发送钉钉群通知。

    :param summary: 测试结果摘要
    :return: 是否发送成功
    """
    if not DINGTALK_ENABLED:
        logger.info('钉钉通知未启用（config.ini 中 dingtalk.enabled=false）')
        return False

    if not DINGTALK_WEBHOOK:
        logger.warning('钉钉 webhook 未配置，跳过通知')
        return False

    # 防刷屏：配置 only_on_failure=true 时，只有失败才发送
    if DINGTALK_ONLY_ON_FAILURE and summary.get('failed', 0) == 0:
        logger.info('全部通过且配置了 only_on_failure，不发送钉钉通知')
        return False

    try:
        timestamp, sign = _sign(DINGTALK_SECRET) if DINGTALK_SECRET else (str(round(time.time() * 1000)), '')

        # 拼接 webhook + 加签参数
        webhook = DINGTALK_WEBHOOK
        if DINGTALK_SECRET:
            separator = '&' if '?' in webhook else '?'
            webhook = f"{webhook}{separator}timestamp={timestamp}&sign={sign}"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": "接口自动化测试报告",
                "text": _build_markdown_content(summary)
            }
        }

        logger.info('正在发送钉钉通知...')
        resp = requests.post(
            webhook,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        resp.raise_for_status()

        result = resp.json()
        if result.get('errcode') == 0:
            logger.info('钉钉通知发送成功')
            return True
        else:
            logger.error('钉钉通知发送失败: {}', result)
            return False

    except requests.RequestException as e:
        logger.error('钉钉通知请求异常: {}', e)
        return False
    except Exception as e:
        logger.error('钉钉通知发送异常: {}', e)
        return False


def build_summary_from_terminalreporter(terminalreporter, duration: float = 0) -> dict:
    """
    从 pytest 的 terminalreporter 提取测试结果摘要。

    :param terminalreporter: pytest 的 TerminalReporter 对象
    :param duration: 测试总耗时（秒）
    :return: summary 字典
    """
    stats = terminalreporter.stats
    passed = len(stats.get('passed', []))
    failed_reports = stats.get('failed', [])
    skipped = len(stats.get('skipped', []))
    error_reports = stats.get('error', [])

    # 收集失败用例名（nodeid），用于钉钉消息展示
    failed_cases = []
    for report in failed_reports:
        failed_cases.append(report.nodeid)
    for report in error_reports:
        failed_cases.append(report.nodeid)

    failed = len(failed_reports) + len(error_reports)

    return {
        'total': passed + failed + skipped,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'duration': duration,
        'report_url': '',  # 外部可填充报告链接
        'failed_cases': failed_cases
    }
