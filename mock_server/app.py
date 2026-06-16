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
from flask import Flask, jsonify, request
from conf.setting import MYSQL_ENABLED, REDIS_ENABLED
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
    """写入 JSON 文件到 mock_data/ 目录"""
    dir_path = os.path.join(_MOCK_DIR, 'mock_data')
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, filename), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


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

    if not all([goods_id, number, price]):
        return jsonify({'error': '参数错误或必填参数为空', 'error_code': '9001'})

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


# ═══════════════════════════════════════════════════
# 4. 异常场景模拟（模块 12 使用）
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
    print('Mock Server 启动中...')
    print('用户管理接口: /dar/user/login | addUser | queryUser | deleteUser | updateUser')
    print('电商接口:     /coupApply/cms/goodsList | productDetail | shoppingInventory | placeAnOrder | orderPay | checkOrderStatus')
    print('异常测试:     /test/error-500 | /test/timeout | /test/empty')
    print()
    app.run(host='127.0.0.1', port=8787, debug=True)
