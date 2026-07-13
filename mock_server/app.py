"""
Mock Server —— Flask 模拟后端服务（模块 9）

设计理念：
1. 模拟真实电商业务：用户管理 + 商品浏览 + 下单支付
2. 覆盖多业务场景：正向、反向（参数缺失/ID不存在）、异常（库存不足）
3. 支持多种传参方式：form-data（POST表单）、JSON body、URL query
4. 用内存 + JSON 文件存储数据，重启不丢失关键数据（订单号）

业务场景覆盖（对标 Test-Automation-Framework）：
┌──────────────┬───────────────────────────────────┐
│ 用户管理      │ 登录 / 新增 / 查询 / 修改 / 删除      │
│ 电商下单      │ 商品列表 → 详情 → 下单 → 支付 → 查状态 │
│ 异常场景      │ 超时 / 500 / 空数据 / 库存不足         │
└──────────────┴───────────────────────────────────┘

为什么用 Flask？
- 轻量级，一个文件搞定所有接口
- 内置 JSON 支持（jsonify），自动处理 Content-Type
- 面试时能讲清楚"请求进来 → 路由匹配 → 取参数 → 校验 → 返回"
"""

import os
import sys
# 把项目根目录加入 Python 路径，确保从 mock_server/ 启动也能 import conf/common
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, '..'))
sys.path.insert(0, _project_root)

import time
import json
import random
import string
import datetime
import threading
from contextlib import contextmanager
from flask import Flask, jsonify, request
from conf.setting import MYSQL_ENABLED, REDIS_ENABLED, MOCK_SERVER_HOST, MOCK_SERVER_PORT, MOCK_SERVER_DEBUG

# 标记当前进程是 Mock Server，让日志系统写独立的 logs/test_mock_server.log，
# 避免和 pytest 主进程 / xdist worker 抢占 test.log，导致 Windows 下日志滚动 rename 失败。
# 必须在 import common.connection 之前设置，因为 connection.py 会触发 record_log.py 初始化。
os.environ['MOCK_SERVER_PROCESS'] = '1'

if MYSQL_ENABLED:
    from common.connection import ConnectMysql
if REDIS_ENABLED:
    from common.connection import ConnectRedis

# 创建 Flask 应用
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # 保持中文原样输出


# ═══════════════════════════════════════════════════
# 0. 基础工具函数
# ═══════════════════════════════════════════════════

_MOCK_DIR = os.path.dirname(os.path.abspath(__file__))

# 物流运单注册表的内存缓存 + 文件持久化锁
_LOGISTICS_REGISTRY = None
_LOGISTICS_LOCK = threading.Lock()


@contextmanager
def _logistics_registry():
    """
    物流运单注册表事务上下文。

    进入时加载/返回内存中的注册表，退出时写回文件。
    整个读-改-写周期加锁，避免 threaded=True 后的并发竞态。
    """
    global _LOGISTICS_REGISTRY
    with _LOGISTICS_LOCK:
        if _LOGISTICS_REGISTRY is None:
            _LOGISTICS_REGISTRY = _read_json('logistics.json')
        yield _LOGISTICS_REGISTRY
        _write_json('logistics.json', _LOGISTICS_REGISTRY)


def _random_token(length=30):
    """生成随机 token"""
    return ''.join(random.choices(string.hexdigits, k=length))


def _random_digits(length=11):
    """生成随机数字串（模拟 ID）"""
    return ''.join(random.choices(string.digits, k=length))


def _now():
    """当前时间标准格式"""
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _read_json(filename):
    """从 mock_data/ 目录读取 JSON 文件"""
    path = os.path.join(_MOCK_DIR, 'mock_data', filename)
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_json(filename, data):
    """
    原子方式写入 JSON 文件到 mock_data/ 目录。

    为什么用临时文件 + os.replace？
    - 直接写入目标文件时，如果进程中途崩溃或被其他进程同时读取，
      可能留下一个半写入的损坏文件。
    - 先写到 .tmp 临时文件，再原子替换（os.replace）目标文件，
      其他进程要么读到旧文件，要么读到新文件，永远不会读到损坏的中间态。
    - Windows 下 os.replace 会覆盖已存在的目标文件，且是原子操作。
    """
    dir_path = os.path.join(_MOCK_DIR, 'mock_data')
    os.makedirs(dir_path, exist_ok=True)
    target_path = os.path.join(dir_path, filename)
    temp_path = target_path + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(temp_path, target_path)


# ═══════════════════════════════════════════════════
# 1. 模拟数据（启动时加载到内存）
# ═══════════════════════════════════════════════════

# 预置用户
VALID_USERS = {'test01': 'admin123'}

# 预置用户 ID（查询/删除用）
VALID_USER_IDS = [
    '123839387391912', '13679000932223434', '89588181111112343',
    '331111456562131', '112576886322112', '213457889904300192'
]

# 会话级 token
SESSION_TOKEN = None

# 当前登录用户 ID
CURRENT_USER_ID = _random_digits(19)

# 按用户名缓存 token：同一账号多次登录返回同一 token，
# 避免 session fixture 登录后，用例里再登录把 token 刷掉
USER_TOKENS = {}

# 商品列表（模拟拼多多商品数据，对标原项目）
PRODUCT_LIST = [
    {
        'goodsId': '18382788819',
        'goods_name': '【2件套】套装秋冬新款仿獭兔毛钉珠皮草毛毛短外套加厚大衣女装',
        'goods_image': 'https://omsproductionimg.yangkeduo.com/images/2017-12-12/bcf848aa71c6389607ae7a84b70f1543.jpeg',
        'unit_price': '¥99.00',
        'goods_count': '233'
    },
    {
        'goodsId': '33809635011',
        'goods_name': '好奇小森林心钻装纸尿裤M22拉拉裤L18/XL14超薄透气裤型尿不湿 1件装',
        'goods_image': 'https://omsproductionimg.yangkeduo.com/images/2017-12-12/176019babfdecffa1d9f98f40b7e99b4.jpeg',
        'unit_price': '¥108.00',
        'goods_count': '521'
    },
    {
        'goodsId': '56996760797',
        'goods_name': '冻干鸡小胸整块增肥营养发腮狗狗零食新手养猫零食幼猫零食100g',
        'goods_image': 'https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg',
        'unit_price': '¥17.80',
        'goods_count': '1181'
    },
    {
        'goodsId': '82193785267',
        'goods_name': '【自营】ISB伊珊娜意大利水果系列宠物犬猫沐浴露除臭香波护毛素',
        'goods_image': 'https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg',
        'unit_price': '¥650.00',
        'goods_count': '3000+'
    },
    {
        'goodsId': '74190550836',
        'goods_name': '【新品零0CM嵌入式】海尔电冰箱410L家用法式四门多门官方正品',
        'goods_image': 'https://omsproductionimg.yangkeduo.com/images/2017-12-12/efb5db42397550bffd3211ca6f197498.jpeg',
        'unit_price': '¥5746.00',
        'goods_count': '1000+'
    }
]

# 所有有效商品 ID（快速判断用）
VALID_GOODS_IDS = [p['goodsId'] for p in PRODUCT_LIST]


# ═══════════════════════════════════════════════════
# 2. 用户管理接口
# ═══════════════════════════════════════════════════

@app.route('/index', methods=['GET'])
def index():
    """首页 —— 验证 Mock Server 是否启动"""
    return jsonify({'msg': '成功访问首页', 'msg_code': 200})


@app.route('/dar/user/login', methods=['POST'])
def user_login():
    """
    用户登录（form-data 表单提交）。

    请求：POST，Content-Type: application/x-www-form-urlencoded
    参数：user_name, passwd
    返回：token, userId, orgId, msg, msg_code

    测试点：用户名不存在、密码错误、参数缺失
    """
    global SESSION_TOKEN, CURRENT_USER_ID

    user_name = request.form.get('user_name')
    passwd = request.form.get('passwd')

    if not all([user_name, passwd]):
        return jsonify({'msg': '参数错误', 'msg_code': -1})

    if VALID_USERS.get(user_name) == passwd:
        # 同一用户多次登录复用同一 token，避免 fixture 登录后用例再登录刷新 token
        # 导致之前写入 extract.yaml 的 token 失效
        if user_name not in USER_TOKENS:
            USER_TOKENS[user_name] = _random_token()
            CURRENT_USER_ID = _random_digits(19)
        SESSION_TOKEN = USER_TOKENS[user_name]

        # 写入 Redis 缓存（演示 token 的三层存储：内存→extract.yaml→Redis）
        if REDIS_ENABLED:
            try:
                r = ConnectRedis()
                r.set(f'token:{user_name}', SESSION_TOKEN, expire=3600)  # 1小时过期
            except Exception as e:
                print(f'[Mock] Redis 写入失败: {e}')

        return jsonify({
            'msg': '登录成功',
            'msg_code': 200,
            'token': SESSION_TOKEN,
            'userId': CURRENT_USER_ID,
            'orgId': random.choice(['4140913758110176843', '6140913758128971280']),
            'error_code': None
        })
    else:
        return jsonify({
            'msg': '登录失败,用户名或密码错误',
            'msg_code': 9001,
            'token': None,
            'userId': None
        })


@app.route('/dar/user/addUser', methods=['POST'])
def add_user():
    """
    新增用户（form-data 提交，需 token 鉴权）。

    测试点：正常新增、缺 token、缺必填参数
    """
    token = request.form.get('token')
    username = request.form.get('username')
    password = request.form.get('password')
    role_id = request.form.get('role_id')
    dates = request.form.get('dates')
    phone = request.form.get('phone')

    if token != SESSION_TOKEN:
        return jsonify({'msg': '新增失败', 'msg_code': 9001})

    if not all([username, password, role_id, dates, phone]):
        return jsonify({'msg': '新增失败', 'msg_code': 9001})

    # 数据库写入（config.ini 中 mysql.enabled=true 时生效）
    if MYSQL_ENABLED:
        try:
            db = ConnectMysql()
            db.execute(
                "INSERT INTO sys_user (username, password, role_id, phone, create_time) "
                "VALUES (%s, %s, %s, %s, %s)",
                (username, password, role_id, phone, _now())
            )
        except Exception as e:
            # 数据库写入失败不回滚接口返回 —— 这正是我们要测试的场景
            # 后续用 db 断言查库，发现没有数据 → 断言失败 → 定位问题
            print(f'[Mock] MySQL 写入失败: {e}')

    return jsonify({'msg': '新增成功', 'msg_code': 200, 'error_code': None})


@app.route('/dar/user/queryUser', methods=['POST'])
def query_user():
    """查询用户"""
    user_id = request.form.get('user_id')
    if user_id in VALID_USER_IDS:
        return jsonify({'msg': '查询成功!', 'msg_code': 200, 'error_code': None})
    return jsonify({'msg': '查询失败，用户id不存在!', 'msg_code': 9001})


@app.route('/dar/user/deleteUser', methods=['POST'])
def delete_user():
    """删除用户"""
    user_id = request.form.get('user_id')
    if user_id in VALID_USER_IDS:
        return jsonify({'msg': '删除成功!', 'msg_code': 200, 'error_code': None})
    return jsonify({'msg': '删除失败，用户id不存在!', 'msg_code': 9001})


@app.route('/dar/user/updateUser', methods=['POST'])
def update_user():
    """
    修改用户 —— 需要参数完全匹配预置数据。

    测试点：数据匹配成功、数据不匹配失败
    """
    params = ['username', 'password', 'role_id', 'dates', 'phone']
    vals = [request.form.get(p) for p in params]
    expected = ['testadduser', 'tset6789#$123', '89588181111112343', '2023-12-31', '13800000000']

    if vals == expected:
        return jsonify({'msg': '更新成功', 'msg_code': 200, 'error_code': None})
    return jsonify({'msg': '更新失败', 'msg_code': 9001})


# ═══════════════════════════════════════════════════
# 3. 电商下单接口（核心业务场景）
# ═══════════════════════════════════════════════════

@app.route('/coupApply/cms/goodsList', methods=['GET'])
def product_list():
    """
    商品列表（GET，URL query 参数）。

    请求：?msgType=getHandsetListOfCust
    返回：商品列表 JSON

    测试点：正常获取、错误的 msgType
    """
    msg_type = request.args.get('msgType')
    if not msg_type:
        return jsonify({'error_code': '9001', 'msg': '参数错误'})

    if msg_type == 'getHandsetListOfCust':
        return jsonify({
            'error_code': '0000',
            'goodsList': PRODUCT_LIST,
            'secache_date': _now(),
            'translate_language': 'zh-CN'
        })
    else:
        return jsonify({
            'error_code': '4000',
            'goodsList': [],
            'secache_date': _now()
        })


@app.route('/coupApply/cms/productDetail', methods=['POST'])
def product_detail():
    """
    商品详情（POST，JSON body）。

    请求体 JSON：{"pro_id": "18382788819"}
    返回：商品详情 JSON

    测试点：正常获取、商品 ID 不存在
    """
    pro_id = request.json.get('pro_id')

    if pro_id in VALID_GOODS_IDS:
        product = next(p for p in PRODUCT_LIST if p['goodsId'] == pro_id)
        return jsonify({
            'error': '',
            'error_code': '0000',
            'goodsId': pro_id,
            'item': {
                'Subject': product['goods_name'],
                'SellCount': '已拼4.2万件',
                'ShopName': '果果家气质女装',
                'AmountOnSale': 3188,
            },
            'secache_date': _now(),
            'translate_language': 'zh-CN'
        })
    else:
        return jsonify({
            'error': '不存在该商品',
            'error_code': '4000',
            'goodsId': '',
            'item': {},
            'secache_date': _now()
        })


@app.route('/coupApply/cms/shoppingInventory', methods=['POST'])
def check_inventory():
    """
    校验商品库存（POST，JSON body）。

    请求体 JSON：{"goodsId": "...", "count": 5}
    返回：status "0"=有货, "1"=库存不足

    测试点：库存充足、库存不足（count >= 5）
    """
    goods_id = request.json.get('goodsId')
    count = int(request.json.get('count', 0))

    if goods_id not in VALID_GOODS_IDS:
        return jsonify({'error_code': '4000', 'error': '商品id不存在'})

    if count < 5:
        return jsonify({
            'error': '',
            'error_code': '0000',
            'status': '0',          # 有货
            'createTime': _now()
        })
    else:
        return jsonify({
            'error': '商品库存不足',
            'error_code': '0000',
            'status': '1',          # 库存不足
            'createTime': _now()
        })


@app.route('/coupApply/cms/placeAnOrder', methods=['POST'])
def place_order():
    """
    提交订单（POST，JSON body）。

    请求体 JSON：{
        "goods_id": "33809635011",
        "number": 2,
        "price": "239.00",
        "consignee_info": {"name": "张三", "phone": 13800000000, "address": "..."}
    }
    返回：orderNumber（21位数字）

    设计要点：
    - 订单号写入 JSON 文件持久化，后续支付接口需要读取
    - 这样即使 Mock Server 重启，订单号不丢失
    """
    goods_id = request.json.get('goods_id')
    number = request.json.get('number')
    price = request.json.get('price')

    if not all([goods_id, number is not None, price]):
        return jsonify({'error': '参数错误或必填参数为空', 'error_code': '9001'})

    try:
        number = int(number)
        if number <= 0:
            return jsonify({'error': '商品数量必须大于0', 'error_code': '9001'})
    except (ValueError, TypeError):
        return jsonify({'error': '商品数量格式错误', 'error_code': '9001'})

    if goods_id not in VALID_GOODS_IDS:
        return jsonify({'error_code': '4000', 'error': '商品id不存在'})

    # 生成订单号并持久化到 JSON 文件
    order_num = _random_digits(21)
    _write_json('order.json', {
        'orderNumber': order_num,
        'userId': CURRENT_USER_ID
    })

    return jsonify({
        'orderNumber': order_num,
        'userId': CURRENT_USER_ID,
        'crateTime': _now(),
        'error': '',
        'error_code': '0000',
        'message': '提交订单成功',
        'translate_language': 'zh-CN'
    })


@app.route('/coupApply/cms/orderPay', methods=['POST'])
def order_pay():
    """
    订单支付（POST，JSON body）。

    请求体 JSON：{"orderNumber": "...", "userId": "..."}
    返回：message

    设计要点：
    - 从 order.json 读取上一次下单的订单号进行比对
    - 这就是接口依赖的 Mock 端实现：上一个接口写，下一个接口读
    """
    order_num = request.json.get('orderNumber')
    user_id = request.json.get('userId')

    if not all([order_num, user_id]):
        return jsonify({'msg': '参数错误', 'error_code': '9001'})

    # 读取持久化的订单数据
    saved = _read_json('order.json')

    if order_num == saved.get('orderNumber') and user_id == saved.get('userId'):
        return jsonify({
            'createTime': _now(),
            'error': '',
            'error_code': '0000',
            'message': '订单支付成功',
            'translate_language': 'zh-CN'
        })
    else:
        return jsonify({
            'error_code': '4000',
            'error': '订单编号或用户id不存在'
        })


@app.route('/coupApply/cms/checkOrderStatus', methods=['POST'])
def check_order_status():
    """
    校验订单状态（POST，JSON body）。

    请求体 JSON：{"orderNumber": "..."}
    返回：status "0"=正常
    """
    order_num = request.json.get('orderNumber')
    saved = _read_json('order.json')

    if order_num == saved.get('orderNumber'):
        return jsonify({
            'status': '0',
            'queryTime': _now(),
            'error': '',
            'error_code': '',
            'translate_language': 'zh-CN'
        })
    return jsonify({'error_code': '4000', 'error': '订单编号不存在'})


# 承运商静态数据（物流查询用）
CARRIER_MAP = {
    'C001': {'carrierId': 'C001', 'carrierName': '顺丰速运', 'rating': 4.8, 'fleetSize': 12000},
    'C002': {'carrierId': 'C002', 'carrierName': '中通快递', 'rating': 4.6, 'fleetSize': 15000},
    'C003': {'carrierId': 'C003', 'carrierName': '韵达速递', 'rating': 4.5, 'fleetSize': 11000},
    'C004': {'carrierId': 'C004', 'carrierName': '德邦物流', 'rating': 4.4, 'fleetSize': 8000},
}


# ═══════════════════════════════════════════════════
# 4. 物流调度接口（模块 7/9 扩展）
# ═══════════════════════════════════════════════════

def _get_logistics_registry():
    """读取物流运单注册表（线程安全，带内存缓存）。"""
    global _LOGISTICS_REGISTRY
    with _LOGISTICS_LOCK:
        if _LOGISTICS_REGISTRY is None:
            _LOGISTICS_REGISTRY = _read_json('logistics.json')
        return _LOGISTICS_REGISTRY


def _save_logistics_registry(registry):
    """保存物流运单注册表（线程安全）。"""
    global _LOGISTICS_REGISTRY
    with _LOGISTICS_LOCK:
        _LOGISTICS_REGISTRY = registry
        _write_json('logistics.json', registry)


def _new_logistics_record(goods_id, quantity, from_addr, to_addr, consignee):
    """创建一条新的运单记录"""
    return {
        'status': 'CREATED',
        'goodsId': goods_id,
        'quantity': quantity,
        'fromAddr': from_addr,
        'toAddr': to_addr,
        'consignee': consignee,
        'createTime': _now(),
        'carrier': None,
        'pickup': None,
        'dispatch': None,
        'schedule': None,
        'sign': None,
        'exception': None,
        'returnInfo': None,
        'subWaybillNos': [],
        'history': [{'status': 'CREATED', 'time': _now()}]
    }


def _append_history(record, status):
    """在运单历史中追加状态节点"""
    record['history'].append({'status': status, 'time': _now()})


@app.route('/logistics/create', methods=['POST'])
def create_waybill():
    """
    创建运单。
    请求体：{goodsId, quantity, fromAddr, toAddr, consignee}
    """
    data = request.json or {}
    goods_id = data.get('goodsId')
    quantity = data.get('quantity')
    from_addr = data.get('fromAddr')
    to_addr = data.get('toAddr')
    consignee = data.get('consignee')

    if not all([goods_id, quantity is not None, from_addr, to_addr, consignee]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    try:
        quantity = int(quantity)
        if quantity <= 0:
            return jsonify({'msg': '数量必须大于0', 'msg_code': 9001, 'error_code': '9001', 'data': None})
    except (ValueError, TypeError):
        return jsonify({'msg': '数量格式错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    waybill_no = _random_digits(18)
    registry[waybill_no] = _new_logistics_record(goods_id, quantity, from_addr, to_addr, consignee)
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '运单创建成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'CREATED',
        'createTime': registry[waybill_no]['createTime']
    })


@app.route('/logistics/assign', methods=['POST'])
def assign_carrier():
    """分配承运商：CREATED -> ASSIGNED"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    carrier_id = data.get('carrierId')
    carrier_name = data.get('carrierName')

    if not all([waybill_no, carrier_id, carrier_name]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'CREATED':
        return jsonify({'msg': '运单状态不允许分配承运商', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'ASSIGNED'
    record['carrier'] = {'carrierId': carrier_id, 'carrierName': carrier_name, 'assignTime': _now()}
    _append_history(record, 'ASSIGNED')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '承运商分配成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'ASSIGNED',
        'carrierInfo': record['carrier']
    })


@app.route('/logistics/pickup', methods=['POST'])
def pickup_waybill():
    """确认揽收：ASSIGNED -> PICKED_UP"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    pickup_time = data.get('pickupTime')
    driver_id = data.get('driverId')

    if not all([waybill_no, pickup_time, driver_id]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'ASSIGNED':
        return jsonify({'msg': '运单状态不允许揽收', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'PICKED_UP'
    record['pickup'] = {'pickupTime': pickup_time, 'driverId': driver_id}
    _append_history(record, 'PICKED_UP')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '揽收成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'PICKED_UP',
        'pickupInfo': record['pickup']
    })


@app.route('/logistics/dispatch', methods=['POST'])
def dispatch_waybill():
    """发往中转仓：PICKED_UP -> IN_TRANSIT"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    hub_id = data.get('hubId')
    hub_name = data.get('hubName')

    if not all([waybill_no, hub_id, hub_name]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'PICKED_UP':
        return jsonify({'msg': '运单状态不允许发运', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'IN_TRANSIT'
    record['dispatch'] = {'hubId': hub_id, 'hubName': hub_name}
    _append_history(record, 'IN_TRANSIT')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '发运成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'IN_TRANSIT',
        'dispatchInfo': record['dispatch']
    })


@app.route('/logistics/track', methods=['GET', 'POST'])
def track_waybill():
    """查询物流轨迹"""
    if request.method == 'GET':
        waybill_no = request.args.get('waybillNo')
    else:
        waybill_no = (request.json or {}).get('waybillNo')

    if not waybill_no:
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    return jsonify({
        'msg': '查询成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': record['status'],
        'currentLocation': record['dispatch']['hubName'] if record['dispatch'] else '始发地',
        'history': record['history']
    })


@app.route('/logistics/schedule', methods=['POST'])
def schedule_delivery():
    """预约派送：IN_TRANSIT -> SCHEDULED"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    delivery_date = data.get('deliveryDate')
    time_window = data.get('timeWindow')

    if not all([waybill_no, delivery_date, time_window]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'IN_TRANSIT':
        return jsonify({'msg': '运单状态不允许预约派送', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'SCHEDULED'
    record['schedule'] = {'deliveryDate': delivery_date, 'timeWindow': time_window}
    _append_history(record, 'SCHEDULED')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '预约派送成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'SCHEDULED',
        'scheduleInfo': record['schedule']
    })


@app.route('/logistics/sign', methods=['POST'])
def sign_waybill():
    """确认签收：SCHEDULED -> DELIVERED"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    signer_name = data.get('signerName')
    sign_time = data.get('signTime')

    if not all([waybill_no, signer_name, sign_time]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'SCHEDULED':
        return jsonify({'msg': '运单状态不允许签收', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'DELIVERED'
    record['sign'] = {'signerName': signer_name, 'signTime': sign_time}
    _append_history(record, 'DELIVERED')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '签收成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'DELIVERED',
        'signInfo': record['sign']
    })


@app.route('/logistics/exception', methods=['POST'])
def report_exception():
    """异常上报：任意状态 -> EXCEPTION"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    exception_type = data.get('exceptionType')
    description = data.get('description')

    if not all([waybill_no, exception_type, description]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    record['status'] = 'EXCEPTION'
    exception_id = _random_digits(18)
    record['exception'] = {'exceptionId': exception_id, 'exceptionType': exception_type, 'description': description}
    _append_history(record, 'EXCEPTION')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '异常上报成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'EXCEPTION',
        'exceptionId': exception_id,
        'exceptionType': exception_type,
        'description': description
    })


@app.route('/logistics/split', methods=['POST'])
def split_waybill():
    """拆单：CREATED 或 ASSIGNED -> SPLIT"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    split_items = data.get('splitItems')

    if not all([waybill_no, split_items]) or not isinstance(split_items, list):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    if len(split_items) < 2 or len(split_items) > 4:
        return jsonify({'msg': '拆单数量必须在2-4之间', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] not in ('CREATED', 'ASSIGNED'):
        return jsonify({'msg': '运单状态不允许拆单', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    sub_waybill_nos = []
    for item in split_items:
        sub_no = _random_digits(18)
        sub_record = _new_logistics_record(
            record['goodsId'], item.get('quantity', 1),
            record['fromAddr'], item.get('toAddr', record['toAddr']),
            record['consignee']
        )
        sub_record['status'] = 'CREATED'
        sub_record['parentWaybillNo'] = waybill_no
        registry[sub_no] = sub_record
        sub_waybill_nos.append(sub_no)

    record['status'] = 'SPLIT'
    record['subWaybillNos'] = sub_waybill_nos
    _append_history(record, 'SPLIT')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '拆单成功',
        'msg_code': 200,
        'error_code': '0000',
        'originalWaybillNo': waybill_no,
        'subWaybillNos': sub_waybill_nos,
        'status': 'SPLIT'
    })


@app.route('/logistics/return', methods=['POST'])
def return_waybill():
    """退货：DELIVERED -> RETURNED"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    reason = data.get('reason')
    return_type = data.get('returnType')

    if not all([waybill_no, reason, return_type]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    record = registry.get(waybill_no)
    if not record:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})
    if record['status'] != 'DELIVERED':
        return jsonify({'msg': '运单状态不允许退货', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    return_no = _random_digits(18)
    record['status'] = 'RETURNED'
    record['returnInfo'] = {'returnNo': return_no, 'reason': reason, 'returnType': return_type}
    _append_history(record, 'RETURNED')
    _save_logistics_registry(registry)

    return jsonify({
        'msg': '退货成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'status': 'RETURNED',
        'returnNo': return_no,
        'reason': reason,
        'returnType': return_type
    })


@app.route('/logistics/cost', methods=['POST'])
def calculate_cost():
    """运费计算（只读）"""
    data = request.json or {}
    waybill_no = data.get('waybillNo')
    weight = data.get('weight')
    distance = data.get('distance')
    service_type = data.get('serviceType')

    if not all([waybill_no, weight is not None, distance is not None, service_type]):
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    registry = _get_logistics_registry()
    if waybill_no not in registry:
        return jsonify({'msg': '运单不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    try:
        weight = float(weight)
        distance = float(distance)
    except (ValueError, TypeError):
        return jsonify({'msg': '重量或距离格式错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    base = 5.0
    weight_fee = round(max(0, weight) * 2, 2)
    distance_fee = round(max(0, distance) * 0.5, 2)
    total = round(base + weight_fee + distance_fee, 2)

    return jsonify({
        'msg': '运费计算成功',
        'msg_code': 200,
        'error_code': '0000',
        'waybillNo': waybill_no,
        'cost': total,
        'currency': 'CNY',
        'breakdown': {
            'base': base,
            'weightFee': weight_fee,
            'distanceFee': distance_fee
        }
    })


@app.route('/logistics/carrier', methods=['GET'])
def query_carrier():
    """查询承运商信息"""
    carrier_id = request.args.get('carrierId')
    if not carrier_id:
        return jsonify({'msg': '参数错误', 'msg_code': 9001, 'error_code': '9001', 'data': None})

    info = CARRIER_MAP.get(carrier_id)
    if not info:
        return jsonify({'msg': '承运商不存在', 'msg_code': 4000, 'error_code': '4000', 'data': None})

    return jsonify({
        'msg': '查询成功',
        'msg_code': 200,
        'error_code': '0000',
        **info
    })


# ═══════════════════════════════════════════════════
# 5. 并发 benchmark 专用接口
# ═══════════════════════════════════════════════════

@app.route('/benchmark/slow_read', methods=['GET'])
def benchmark_slow_read():
    """
    模拟真实接口延迟，用于并发 benchmark。

    故意 sleep 50ms，让 pytest-xdist 的并行优势能够体现出来。
    如果接口都是亚毫秒级本地响应，xdist 的进程启动开销反而会拖慢总时间。
    """
    time.sleep(0.05)
    return jsonify({'msg': '慢查询返回', 'msg_code': 200, 'error_code': '0000'})


# ═══════════════════════════════════════════════════
# 6. 异常场景模拟（模块 12 使用）
# ═══════════════════════════════════════════════════

@app.route('/test/error-500', methods=['GET'])
def error_500():
    """模拟服务器内部错误"""
    return jsonify({'msg': '服务器内部错误'}), 500


@app.route('/test/timeout', methods=['GET'])
def timeout():
    """模拟超时（sleep 超过框架 timeout）"""
    time.sleep(5)
    return jsonify({'msg': '超时测试'})


@app.route('/test/empty', methods=['GET'])
def empty_response():
    """模拟空响应体"""
    return '', 200


# ═══════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════

if __name__ == '__main__':
    print('Mock Server 启动中...（threaded=True 支持并发请求）')
    print(f'配置来源: conf/config.ini  [mock_server] debug={MOCK_SERVER_DEBUG}')
    print('用户管理接口: /dar/user/login | addUser | queryUser | deleteUser | updateUser')
    print('电商接口:     /coupApply/cms/goodsList | productDetail | shoppingInventory | placeAnOrder | orderPay | checkOrderStatus')
    print('物流接口:     /logistics/create | assign | pickup | dispatch | track | schedule | sign | exception | split | return | cost | carrier')
    print('Benchmark:    /benchmark/slow_read')
    print('异常测试:     /test/error-500 | /test/timeout | /test/empty')
    print()
    app.run(host=MOCK_SERVER_HOST, port=MOCK_SERVER_PORT, debug=MOCK_SERVER_DEBUG, threaded=True)
