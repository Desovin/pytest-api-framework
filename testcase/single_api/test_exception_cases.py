"""
异常场景覆盖（模块 12）

覆盖类型：
1. 服务端异常：HTTP 500
2. 网络异常：请求超时
3. 数据异常：空响应体
4. 参数异常：缺少必填参数
5. 业务异常：库存不足、商品不存在

为什么这些用例不打 @pytest.mark.serial？
- 异常接口都是只读或失败返回，不会产生脏数据
- 可以安全并发执行
"""

import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('异常场景覆盖')
class TestExceptionCases:

    @allure.story('服务端/网络/参数/业务异常')
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/exception_cases.yaml'))
    def test_exception(self, base_info, testcase):
        """异常场景 —— 6 大类异常统一覆盖"""
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
