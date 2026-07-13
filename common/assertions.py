"""
模块 5：断言引擎

为什么封装断言而不用裸写 assert？
1. 报错信息包含上下文（接口名、期望值、实际值），一眼定位问题
2. 一次执行所有断言再报错（不因第一个失败就停止）
3. 支持 YAML 数据驱动 —— 断言规则写在 YAML 的 validation 字段里
4. 6 种断言模式覆盖不同验证场景（模块 12 新增 timeout 超时断言）

六种断言模式：
┌──────────┬──────────────────────────────────────┐
│ contains │ 响应中包含某字符串（宽松匹配）          │
│ eq       │ 精确相等                              │
│ ne       │ 不相等                                │
│ rv       │ 响应体任意字段值校验                    │
│ db       │ 数据库断言（模块 10 实现）              │
│ redis    │ Redis 缓存断言（模块 10 实现）          │
│ timeout  │ 超时断言（模块 12 异常场景）            │
└──────────┴──────────────────────────────────────┘
"""

from common.record_log import get_logger
from common.connection import ConnectMysql, ConnectRedis

logger = get_logger(__name__)


class Assertions:
    """
    接口断言引擎。

    使用方式（在测试用例中）：
        engine = Assertions()
        engine.assert_result(
            validation=[{'contains': {'msg': '新增成功'}}, {'eq': {'msg_code': 200}}],
            response=resp['json'],
            status_code=resp['status_code']
        )
    """

    def assert_result(self, validation, response, status_code):
        """
        执行所有断言规则，收集全部失败后一次性报错。

        设计要点：all_flag 累加所有断言失败数，最后 all_flag == 0 才算通过。
        这样第一个断言失败不会阻止后续断言，一次测试看到所有失败点。

        :param validation: YAML 中的 validation 列表
              格式: [{'contains': {'msg': '成功'}}, {'eq': {'code': 200}}]
        :param response: 接口响应体（dict）
        :param status_code: HTTP 状态码（int）
        """
        all_flag = 0  # 失败计数器，0 = 全部通过

        # rule 对应 {'contains': {'msg': '新增成功'}, 'eq': {'code': 200} 等} 
        for rule in validation:
            # mode 对应 'contains' , expected 对应 {'msg': '新增成功'}
            for mode, expected in rule.items(): #items() 返回一个可迭代对象，包含字典的键值对
                if mode == 'contains':
                    all_flag += self._assert_contains(expected, response, status_code)
                elif mode == 'eq':
                    all_flag += self._assert_eq(expected, response)
                elif mode == 'ne':
                    all_flag += self._assert_ne(expected, response)
                elif mode == 'rv':
                    all_flag += self._assert_rv(expected, response)
                elif mode == 'db':
                    all_flag += self._assert_db(expected)
                elif mode == 'redis':
                    all_flag += self._assert_redis(expected)
                elif mode == 'timeout':
                    all_flag += self._assert_timeout(expected)
                else:
                    logger.warning('不支持的断言模式: {}', mode)

        if all_flag == 0:
            logger.info('断言通过')
            assert True
        else:
            # assert False 会触发 pytest 的失败报告
            assert False, f'断言失败: {all_flag} 项不通过'

    # ── 六种断言模式的具体实现 ──

    def _assert_contains(self, expected, response, status_code):
        """
        contains 模式：验证响应中是否包含期望的内容。

        特殊处理：
        - key 为 'status_code' 时，验证 HTTP 状态码而非响应体字段
        - response 为 None 时（如空响应体/超时），只校验 status_code

        例子：
        - {'msg': '新增成功'}  → 检查 resp['msg'] 是否包含 '新增成功'
        - {'status_code': 200}  → 检查 HTTP 状态码 == 200
        - {'error_code': 'none'} → 检查 resp['error_code'] 是否为 None
        """
        flag = 0
        # key 对应 'msg'，exp_value 对应 '新增成功'
        for key, exp_value in expected.items():
            if key == 'status_code':
                # 验证 HTTP 状态码
                if exp_value != status_code:
                    flag += 1
                    logger.error(
                        'contains 断言失败 | {}: 期望={}, 实际={}',
                        key, exp_value, status_code
                    )
            elif response is None:
                # 响应体为 None（空响应/超时），无法做字段包含判断
                flag += 1
                logger.error(
                    'contains 断言失败 | {}: response 为 None，无法验证 "{}"',
                    key, exp_value
                )
            else:
                # key不是'status_code' ，从响应体中取对应字段的值，没取到返回空字符串
                actual = response.get(key, '')
                # None 转字符串 'None' 以与 YAML 中的 'none' 匹配
                # 如果if 成立 就是空字符串 不成立就是 else 后的值
                exp_str = '' if exp_value is None else str(exp_value)
                act_str = '' if actual is None else str(actual)

                if exp_str.upper() == 'NONE':   #upper() 将字符串中所有字母转换成大写
                    # 期望值为 None 时，实际值也必须为 None
                    if actual is not None:
                        flag += 1
                        logger.error(
                            'contains 断言失败 | %s: 期望=None, 实际=%s', key, actual
                        )
                elif exp_str not in act_str:
                    # 常规字符串包含判断
                    flag += 1
                    logger.error(
                        'contains 断言失败 | %s: 期望包含"%s", 实际="%s"',
                        key, exp_value, actual
                    )
        return flag

    def _assert_eq(self, expected, response):
        """
        eq 模式：验证响应字段与期望值严格相等。

        例子：{'msg': '登录成功'} → response['msg'] == '登录成功'
        """
        flag = 0
        if response is None:
            logger.error('eq 断言失败 | response 为 None')
            return len(expected)

        for key, exp_value in expected.items():
            actual = response.get(key)
            if actual != exp_value:
                flag += 1
                logger.error(
                    'eq 断言失败 | %s: 期望=%s, 实际=%s', key, exp_value, actual
                )
        return flag

    def _assert_ne(self, expected, response):
        """
        ne 模式：验证响应字段与期望值不相等。

        用于验证"不是某状态"，如：{'status': 'error'} → status 不是 'error'
        """
        flag = 0
        if response is None:
            logger.error('ne 断言失败 | response 为 None')
            return len(expected)

        for key, exp_value in expected.items():
            actual = response.get(key)
            if actual == exp_value:
                flag += 1
                logger.error(
                    'ne 断言失败 | %s: 不期望值=%s, 实际=%s', key, exp_value, actual
                )
        return flag

    def _assert_rv(self, expected, response):
        """
        rv (return value) 模式：验证响应体的任意值。

        与 eq 的区别：rv 只检查键值对的相等性，不做额外的类型或结构处理。
        用于快速校验单个字段的值。

        例子：{'msg_code': 200} → response['msg_code'] == 200
        """
        # 后期可能让eq做业务验证
        flag = 0
        if response is None:
            logger.error('rv 断言失败 | response 为 None')
            return len(expected)

        for key, exp_value in expected.items():
            actual = response.get(key)
            if actual != exp_value:
                flag += 1
                logger.error(
                    'rv 断言失败 | %s: 期望=%s, 实际=%s', key, exp_value, actual
                )
        return flag

    def _assert_timeout(self, expected):
        """
        timeout 模式：验证请求是否按预期超时（模块 12 新增）。

        YAML 写法：
            validation:
              - timeout: true   # 期望超时
              - timeout: false  # 期望不超时

        为什么需要这个模式？
        超时场景下 SendRequest 返回 None，没有 response/status_code，
        普通断言无法处理，需要专门的 timeout 断言。
        """
        flag = 0
        # expected 是 bool 值（PyYAML 解析 true/false 为 Python bool）
        expect_timeout = bool(expected)

        # 调用 timeout 断言时，说明请求已经返回 None（在 apiutil.py 中判断）
        # 所以 actual_timeout 一定是 True
        actual_timeout = True

        if expect_timeout != actual_timeout:
            flag += 1
            logger.error(
                'timeout 断言失败 | 期望超时=%s, 实际=%s',
                expect_timeout, actual_timeout
            )
        else:
            logger.info('timeout 断言通过 | 请求按预期超时')

        return flag

    def _assert_db(self, expected):
        """
        db 模式：数据库断言 —— 查库验证数据确实落库。

        YAML 中的 validation 写法：
            validation:
              - db: { 'sql': "SELECT * FROM sys_user WHERE username='testadduser'" }

        执行逻辑：
        1. 执行 SQL
        2. 有返回结果 → 数据确实在库里 → 断言通过
        3. 无返回结果 → 数据没写进去 → 断言失败

        为什么不能只断言接口返回？
        - 接口返回 200 但数据库写入失败（异常被吞）
        - 接口返回 200 但数据写进了缓存还没刷到磁盘
        - 接口返回 200 但主库写了从库还没同步
        """
        flag = 0
        sql = expected.get('sql', '')
        if not sql:
            logger.error('db 断言缺少 sql 字段')
            return 1

        db = ConnectMysql()
        result = db.query_one(sql)

        if result is not None:
            logger.info('数据库断言成功: 查到数据')
        else:
            flag += 1
            logger.error('数据库断言失败: 未查到数据，SQL={}', sql)
        return flag

    def _assert_redis(self, expected):
        """
        redis 模式：Redis 缓存断言 —— 验证键值对是否存在/不存在/值是否正确。

        YAML 中的 validation 写法：
            validation:
              - redis: { 'key': 'token:test01', 'exists': true }

        三种验证维度：
        1. exists=true: 确认 key 存在（如 token 已缓存到 Redis）
        2. exists=false: 确认 key 不存在（如缓存已过期被删除）
        3. value=xxx: 确认 key 的值等于期望值（如验证码是 '9527'）

        为什么需要 Redis 断言？
        - 登录后 token 应该写入 Redis —— 验证缓存写入
        - 退出登录后 token 应该删除 —— 验证缓存清除
        - 验证码存入 Redis —— 验证值正确且有过期时间
        """
        flag = 0
        key = expected.get('key', '')
        expect_exists = expected.get('exists', None)
        expect_value = expected.get('value', None)

        if not key:
            logger.error('redis 断言缺少 key 字段')
            return 1

        redis_client = ConnectRedis()
        actual = redis_client.get(key)

        # 验证存在性
        if expect_exists is True and actual is None:
            flag += 1
            logger.error('redis 断言失败 | key={}: 期望存在, 实际不存在', key)
        elif expect_exists is False and actual is not None:
            flag += 1
            logger.error('redis 断言失败 | key={}: 期望不存在, 实际值={}', key, actual)
        elif expect_value is not None:
            if str(actual) != str(expect_value):
                flag += 1
                logger.error('redis 断言失败 | key={}: 期望值={}, 实际值={}',
                             key, expect_value, actual)
            else:
                logger.info('redis 断言成功 | key={} 值正确', key)
        elif actual is not None:
            logger.info('redis 断言成功 | key={} 存在', key)

        return flag
