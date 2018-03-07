# coding=utf-8
from datetime import datetime, timedelta
from flask import current_app
from flask import request, g, jsonify

from ihome import db, redis_store
from ihome.models import House, Order
from ihome.utils.commons import login_required
from ihome.utils.response_code import RET
from . import api


@api.route('/orders', methods=["POST"])
@login_required
def save_order():
    """保存订单"""
    # 获取参数  下单用户/房屋id/起始时间/终止时间
    user_id = g.user_id
    req_dict = request.get_json()
    house_id = req_dict.get('house_id')
    start_date_str = req_dict.get('start_date')
    end_date_str = req_dict.get('end_date')

    # 校验参数
    # 参数完整性校验
    if not all([house_id, start_date_str, end_date_str]):
        return jsonify(errno=RET.PARAMERR, errmsg='参数不完整')

    # 房屋id是否存在
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询房屋信息失败')

    # 时间格式
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        assert end_date >= start_date
        # 时间格式可以直接加减
        days = (end_date - start_date).days + 1
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR, errmsg='日期格式有误')

    # 判断房屋是否冲突,是否可以预定
    # 查询当前要预定的房屋是否有冲突的订单
    try:
        conflict_count = Order.query.filter(Order.house_id == house_id, Order.begin_date <= end_date, Order.end_date >= start_date).count()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询房屋订单数据失败')
    if conflict_count:
        # 如果有与当前房屋冲突的订单
        return jsonify(errno=RET.DATAEXIST, errmsg='当前房屋已被预定')

    # 判断下单人是否是房东本人
    if user_id == house.user_id:
        return jsonify(errno=RET.ROLEERR, errmsg='无法预定本人发布的房屋')

    # 保存订单数据
    # 生成订单对象
    order = Order()
    order.user_id = user_id,
    order.house_id = house_id,
    order.begin_date = start_date,
    order.end_date = end_date,
    order.days = days,
    order.house_price = house.price,
    order.amount = (days * house.price)
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.rollback()
        return jsonify(errno=RET.DBERR, errmsg='保存订单失败')

    # 返回
    return jsonify(errno=RET.OK, errmsg='保存订单成功', data={"order_id":order.id})


@api.route('/user/orders', methods=['GET'])
@login_required
def get_user_orders():
    """获取用户订单数据"""
    # 获取参数  用户id/用户类别(房东/房客)
    user_id = g.user_id
    role = request.args.get('role')
    # 校验参数 role
    # 根据用户身份查询数据库
    try:
        if 'custom' == role:
            # 如果是以房客的身份查询订单
            orders = Order.query.filter(Order.user_id==user_id).order_by(Order.create_time.desc()).all()
        else:
            # 如果是已房东的身份查询客户订单(查看有谁预定了自己的房屋)
            # 先查询自己发布了哪些房屋
            houses = House.query.filter(House.user_id==user_id).all()
            # 获取所有房屋id的列表
            houses_id = [house.id for house in houses]
            # 根据房屋的id信息查询订单信息
            orders = Order.query.filter(Order.house_id.in_(houses_id)).order_by(Order.create_time.desc()).all()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询数据库异常')

    # 将订单对象转换为字典数据
    order_dict_list = []
    if orders:
        for order in orders:
            order_dict_list.append(order.to_dict())
    # 返回
    return jsonify(errno=RET.OK, errmsg='OK', data={"orders":order_dict_list})


@api.route('/orders/<int:order_id>/status', methods=['PUT'])
@login_required
def accept_reject_order(order_id):
    """接单,拒单"""
    # 获取参数
    user_id = g.user_id
    req_data = request.get_json()
    if not req_data:
        return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
    # action 参数表示客户端请求的是接单还是拒单的行为
    action = req_data.get('action')
    if action not in ('accept', 'reject'):
        return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
    try:
        # 根据订单号查询订单,并且要求订单处于等待接单状态
        order = Order.query.filter(Order.id == order_id, Order.status == 'WAIT_ACCEPT').first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='无法获取订单数据')
    # 确保房东只能修改属于自己房子的订单
    if not order or house.user_id != user_id:
        return jsonify(errno=RET.REQERR, errmsg='操作无效')
    if action == "accept":
        # 接单,将订单状态设置为等待支付
        order.status = 'WAIT_PAYMENT'
    elif action == 'reject':
        # 拒单,要求用户提供拒单原因
        reason = req_data.get('reason')
        if not reason:
            return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
        order.status = 'REJECTED'
        order.comment = reason
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg='操作失败')
    return jsonify(errno=RET.OK, errmsg='OK')


@api.route('/orders/<int:order_id>/comment', methods=['PUT'])
@login_required
def save_order_comment(order_id):
    """保存订单评论信息"""
    user_id = g.user_id
    # 获取参数
    req_data = request.get_json()
    comment = req_data.get('comment')
    # 检查参数
    if not comment:
        return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
    try:
        # 需要确保只能评论自己下的订单,而且订单处于待评价状态才可以
        order = Order.query.filter(Order.id == order_id, Order.user_id == user_id,
                                   Order.status == 'WAIT_COMMENT').first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='无法获取订单数据')
    if not order:
        return jsonify(errno=RET.REQERR, errmsg='操作无效')
    try:
        # 将订单的状态设置为已完成
        order.status = 'COMPLETE'
        # 保存订单的评价信息
        order.comment = comment
        # 将房屋的完成订单数加一
        house.order_count += 1
        db.session.add(order)
        db.session.add(house)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg='操作失败')
    # 因为房屋详情中有订单的评价信息,为了让最新的评价信息展示在房屋详情中,所以删除redis中关于本订单房屋的详情缓存
    try:
        redis_store.delete('house_info_%s' % order.house.id)
    except Exception as e:
        current_app.logger.error(e)
    return jsonify(errno=RET.OK, errmsg='OK')








