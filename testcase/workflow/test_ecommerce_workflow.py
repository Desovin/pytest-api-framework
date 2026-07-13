"""
电商下单完整链路工作流测试。

流程：登录 → 商品列表 → 商品详情 → 校验库存 → 提交订单 → 订单支付 → 查询订单状态。
数据通过 extract.yaml 在步骤间传递：token / userId / goodsIds / orderNumber。
"""

import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase


@allure.feature('电商业务场景')
class TestEcommerceWorkflow:

    @allure.story('登录到下单支付完整流程')
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/workflow/ecommerce_order_flow.yaml'))
    def test_ecommerce_order_flow(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)

    @allure.story('电商下单反向场景')
    @pytest.mark.serial
    @pytest.mark.parametrize('base_info,testcase',
                             get_testcase_yaml('data/workflow/ecommerce_order_negative.yaml'))
    def test_ecommerce_order_negative(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
