"""
并发 benchmark 用例：大量只读接口，可被 pytest-xdist 安全并行。

为什么单独一个文件？
- 物流/电商单接口用例大多涉及共享状态或 extract.yaml，需要串行。
- 为了真实测量 xdist 加速比，需要一组无状态、可并行的只读用例。
"""

import os
import allure
import pytest
from common.read_yaml import get_testcase_yaml
from base.apiutil import RequestBase

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_BENCHMARK_CASES = []
for base_info, testcase in get_testcase_yaml('data/benchmark/concurrent_reads.yaml'):
    _BENCHMARK_CASES.append(
        pytest.param(
            base_info,
            testcase,
            id=testcase['case_name']
        )
    )


@allure.feature('并发 benchmark')
class TestConcurrentReads:

    @allure.story('只读接口并发')
    @pytest.mark.parametrize('base_info,testcase', _BENCHMARK_CASES)
    def test_concurrent_read(self, base_info, testcase):
        allure.dynamic.title(testcase['case_name'])
        RequestBase().specification_yaml(base_info, testcase)
