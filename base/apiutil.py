"""
模块 7：编排列核心（对标 Test-Automation-Framework 的 base/apiutil.py）

RequestBase 是框架的"大脑"——负责把 YAML 数据"翻译"成一次完整的接口测试。

specification_yaml() 的执行流程：
1. 从配置读 API_HOST
2. replace_load() → 替换 YAML 中的 ${函数名()} 占位符
3. 构造 HTTP 请求（拼接 URL、合并 headers、处理参数）
4. 调用 SendRequest 发送请求
5. extract_data() → 从响应中提取字段（模块 8 对接 extract.yaml）
6. assert_result() → 执行断言验证

为什么叫 specification_yaml？
原项目命名，"规格说明"的意思——YAML 定义了接口的规格，这个方法按规格执行测试。
"""

import json
import re
import jsonpath
import allure
from common.send_request import SendRequest
from common.assertions import Assertions
from common.record_log import get_logger
from common.read_yaml import write_extract
from base.debugtalk import DebugTalk
from conf.setting import API_HOST

logger = get_logger(__name__)


class RequestBase:
    """
    接口测试编排器。

    把 YAML 中的 baseInfo（接口定义）和 testCase（测试数据）
    转化为实际的 HTTP 请求 + 断言验证。
    """

    def __init__(self):
        # SendRequest 实例：base_url=None，因为 specification_yaml 里已拼好完整 URL
        # 传入 token 刷新回调，遇到 401 可自动刷新 token 并重试
        self.client = SendRequest(
            base_url=None,
            token_refresh_callback=DebugTalk.get_token,
            auth_param_key='token'  # Mock Server 用 form-data 的 token 字段鉴权
        )
        # Assertions 实例：负责断言验证（模块 5）
        self.asserts = Assertions()

    # ═══════════════════════════════════════════════════
    # 核心方法：YAML → 请求 → 断言
    # ═══════════════════════════════════════════════════

    def specification_yaml(self, base_info, test_case):
        """
        执行一次完整的接口测试。

        :param base_info: YAML 中的 baseInfo 部分
              包含：api_name, url, method, header
        :param test_case: YAML 中的 testCase 数组元素
              包含：case_name, data/params/json, validation, extract(可选)
        """
        try:
            # ── Step 1: 读取接口基本信息 ──
            api_name = base_info['api_name']
            url = API_HOST + base_info['url']
            method = base_info['method']
            header = dict(base_info['header'])  # 复制一份，避免修改原始数据

            # 将接口信息附加到 Allure 报告
            allure.attach(api_name, f'接口名称：{api_name}', allure.attachment_type.TEXT)
            allure.attach(url, f'请求地址：{url}', allure.attachment_type.TEXT)
            allure.attach(method, f'请求方法：{method}', allure.attachment_type.TEXT)

            # ── Step 2: 替换请求头中的占位符 ──
            header = self.replace_load(header)

            # ── Step 3: 取出断言规则（.get 而非 .pop，避免修改原始数据）──
            validation = test_case.get('validation', [])

            # ── Step 4: 取出数据提取规则（模块 8 对接 extract.yaml）──
            extract = test_case.get('extract', None)

            # ── Step 5: 取出用例名 ──
            case_name = test_case.get('case_name', '')
            allure.attach(case_name, f'测试用例：{case_name}', allure.attachment_type.TEXT)

            # ── Step 6: 替换请求参数中的占位符 ──
            # 只处理请求参数 key（data/json/params），跳过 case_name/validation/extract
            params_type = ['data', 'json', 'params']
            request_params = {}
            for key, value in test_case.items():
                if key in params_type:
                    request_params[key] = self.replace_load(value)

            # ── Step 6.5: 读取超时时间（可选，模块 12 异常场景用）──
            # YAML 中可写 timeout: 1 表示期望 1 秒内返回，用于测试超时场景
            timeout = test_case.get('timeout', None)
            if timeout is not None:
                request_params['timeout'] = timeout

            # ── Step 7: 发送请求 ──
            # SendRequest base_url=None, path 传完整 URL
            resp = self.client._send(
                method=method,
                path=url,
                headers=header,
                **request_params
            )

            # 检查当前用例是否期望超时（validation 里有 timeout 模式）
            expect_timeout = False
            if validation:
                for rule in validation:
                    if 'timeout' in rule:
                        expect_timeout = True
                        break

            if resp is None:
                if expect_timeout:
                    # 预期超时的场景：请求返回 None 是符合预期的
                    logger.info('%s 请求超时（符合预期）', api_name)
                    allure.attach('请求超时（符合预期）', '响应信息', allure.attachment_type.TEXT)
                else:
                    # 非预期超时：按原有逻辑报错
                    logger.error('%s 请求失败', api_name)
                    raise Exception(f'{case_name}: 请求失败')

                # 执行断言（timeout 模式）
                if validation:
                    self.asserts.assert_result(
                        validation=validation,
                        response=None,
                        status_code=None
                    )
                return

            # 将响应信息附加到 Allure 报告
            allure.attach(
                json.dumps(resp['json'], ensure_ascii=False, indent=2),
                '响应体',
                allure.attachment_type.JSON
            )

            # ── Step 7.5: 提取响应字段到 extract.yaml（模块 8 新增）──
            if extract:
                self.extract_data(extract, resp['text'])

            # ── Step 8: 执行断言 ──
            if validation:
                self.asserts.assert_result(
                    validation=validation,
                    response=resp['json'],
                    status_code=resp['status_code']
                )

        except Exception as e:
            logger.error('specification_yaml 执行异常: %s', e)
            raise

    # ═══════════════════════════════════════════════════
    # 占位符替换：${函数名(参数)} → 实际值
    # ═══════════════════════════════════════════════════

    def replace_load(self, data):
        """
        扫描数据中的 ${函数名(参数)} 占位符，替换为运行时实际值。

        工作原理：
        1. 将 data 转为字符串（如果是 dict，先 json.dumps）
        2. 用正则找到所有 ${...} 模式
        3. 解析出函数名和参数
        4. 通过 Python 反射 getattr(DebugTalk(), func_name)(*params) 调用
        5. 把返回值替换回原字符串
        6. 如果原数据是 dict，json.loads 还原类型

        例子：
            '${get_token}' → DebugTalk.get_token() → 'AbCdEf123'
            '${get_timestamp}' → DebugTalk.get_timestamp() → '1779630972'
        """
        if data is None:
            return data

        # 将数据转为字符串（如果是 dict 类型，先序列化）
        str_data = data
        # 判断 data是不是str的实例（instance）
        if not isinstance(data, str):
            # json.dumps : 把字典、列表等转成json格式的字符串
            # default=str: 遇到 datetime.date 等 JSON 不认识的对象时，转成字符串
            str_data = json.dumps(data, ensure_ascii=False, default=str)
        # 例如 # str_data = '{"token": "${get_token}", "username": "张三"}'

        # 计算占位符数量 range生成序列 '_'表示我们不关心具体的值，只关心次数
        for _ in range(str_data.count('${')):
            if '${' not in str_data or '}' not in str_data:
                break

            # 定位 ${ 到 } 的范围
            start = str_data.index('${')
            end = str_data.index('}', start)
            placeholder = str_data[start:end + 1]  # 完整占位符，如 '${get_token}'

            # 提取函数名：'${get_token}' → 'get_token'
            # inner的类型是str
            inner = placeholder[2:-1]  # 去掉 ${ 和 }
            # 提取函数参数：'get_token(x,y)' → func='get_token', params=['x','y']
            if '(' in inner:
                func_name = inner[:inner.index('(')]
                params_str = inner[inner.index('(') + 1:inner.index(')')]
                # params_str的示例 "admin, 123, test"
                # split(',')方法根据逗号分隔字符串，返回一个列表
                # 对列表中的每个元素进行strip()方法，去掉首尾空格
                # 如果去空后不为空，才添加到params列表中
                params = [p.strip() for p in params_str.split(',') if p.strip()]
            else:
                func_name = inner
                params = []

            # 反射调用 DebugTalk 中的同名方法
            # 注意：DebugTalk() 是 DebugTalk 类的实例，不是类本身
            try:
                # getattr()函数根据字符串名获取返回对象的属性或方法(这里是方法)
                # *params 表示将 params 列表中的元素解包作为参数传递给方法
                result = getattr(DebugTalk(), func_name)(*params)
            except AttributeError:
                logger.warning('DebugTalk 中未找到方法: %s，保持原占位符', func_name)
                result = placeholder
            except Exception as e:
                logger.error('调用 DebugTalk.%s 失败: %s', func_name, e)
                result = placeholder

            # 替换
            str_data = str_data.replace(placeholder, str(result) if result else '')

        # 还原数据类型（dict → dict，保持原始类型）
        if isinstance(data, dict):
            # json.loads : 把json格式的字符串转成字典、列表等
            return json.loads(str_data)
        return str_data

    # ═══════════════════════════════════════════════════
    # 响应字段提取：jsonpath → extract.yaml（模块 8）
    # ═══════════════════════════════════════════════════

    def extract_data(self, extract_rules, response_text):
        """
        从接口响应中提取字段，写入 extract.yaml。

        工作原理（对标原项目 RequestBase.extract_data()）：
        1. 将响应文本解析为 JSON
        2. 遍历 extract 规则，每个规则是 {变量名: jsonpath表达式}
        3. 对每个变量名，用 jsonpath 从响应 JSON 中提取值
        4. 将 {变量名: 提取值} 写入 extract.yaml

        jsonpath 语法示例：
          $.token           → 根目录下的 token 字段："abc123"
          $.data.userId     → 嵌套字段：data 下的 userId
          $..goodsId        → 递归搜索：响应中任意位置的 goodsId（返回列表）

        :param extract_rules: YAML 中的 extract 字段
              如 {'token': '$.token', 'userId': '$.userId'}
        :param response_text: 接口响应的原始文本（JSON 字符串）
        """
        try:
            resp_json = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error('响应不是有效 JSON，无法提取字段')
            return

        # var_name 是提取的字段名（如 token）
        # jsonpath_expr 是提取的字段的jsonpath表达式 如$.data.userId
        for var_name, jsonpath_expr in extract_rules.items():
            try:
                # jsonpath.jsonpath() 返回匹配结果的列表
                # 如 $.token → ['abc123']，$..goodsId → ['id1', 'id2', 'id3']
                result = jsonpath.jsonpath(resp_json, jsonpath_expr)
                if result:
                    # 单值取第一个元素，多值保留列表
                    value = result[0] if len(result) == 1 else result
                    write_extract({var_name: value}) # 目录已经写在方法中
                    logger.info('提取字段: %s = %s', var_name, value)
                else:
                    logger.warning('jsonpath 未匹配到数据: %s', jsonpath_expr)
            except Exception as e:
                logger.error('提取字段 %s 失败: %s', var_name, e)

