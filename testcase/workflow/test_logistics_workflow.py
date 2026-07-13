"""
物流业务场景工作流测试。

覆盖：物流全生命周期、异常与退货、拆单。
每个工作流 YAML 独立创建 waybillNo，避免状态串扰。
"""

import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('物流业务场景')
class TestLogisticsWorkflow:

    @allure.story('物流全生命周期')
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/workflow/logistics_full_lifecycle.yaml'))
    def test_logistics_full_lifecycle(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story('物流异常与退货')
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/workflow/logistics_exception_flow.yaml'))
    def test_logistics_exception_flow(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story('物流拆单')
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/workflow/logistics_split_flow.yaml'))
    def test_logistics_split_flow(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
