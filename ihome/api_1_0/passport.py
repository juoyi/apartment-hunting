# coding=utf-8

# 导入正则模块,用于校验手机号
import re
# 导入flask内置的对象
from flask import request, jsonify, current_app, session, g
# 导入自定义的状态码
from ihome.utils.response_code import RET
# 导入模型类User
from ihome.models import User
# 导入登陆验证装饰器
from ihome.utils.commons import login_required
# 导入七牛云接口
from ihome.utils.image_storage import storage
# 导入七牛云的空间域名
from ihome.constants import QINIU_DOMIN_PREFIX
from ihome import db

# 导入蓝图对象api
from . import api


@api.route('/sessions', methods=['POST'])
def login():
    """用户登陆"""
    # 1.获取参数
    user_data = request.get_json()
    # 2.校验参数
    if not user_data:
        return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
    # 3.获取详细的参数信息
    mobile = user_data.get('mobile')
    password = user_data.get('password')
    # 4.参数完整性校验
    if not all([mobile, password]):
        return jsonify(errno=RET.PARAMERR, errmsg='参数不完整')
    # 5.验证手机号码
    if not re.match(r'1[3456789]\d{9}', mobile):
        return jsonify(errno=RET.PARAMERR, errmsg='手机号码格式有误')
    # 6.根据手机号码查询数据库,确认密码是否正确
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询用户信息异常')
    if user is None or not user.check_password(password):
        return jsonify(errno=RET.DATAERR, errmsg='用户名或密码错误')
    # 缓存用户信息
    session['user_id'] = user.id
    session['user_name'] = user.name
    session['user_mobile'] = mobile
    # 返回结果
    return jsonify(errno=RET.OK, errmsg='OK', data={'user_id':user.id})


@api.route('/user', methods=["GET"])
@login_required
def get_user_info():
    # 获取用户id, login_required 装饰器中会获取用户id,并且将其赋值给g变量
    user_id = g.user_id
    # 根据用户id查询用户信息
    try:
        user = User.query.filter_by(id=user_id).first()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='查询数据库异常')
    # 校验查询结果
    if user is None:
        return jsonify(errno=RET.NODATA, errmsg='无效操作')
    # 调用User实例对象的to_dict方法,获取user信息(封装)
    return jsonify(errno=RET.OK, errmsg='OK', data=user.to_dict())


@api.route('/user/avatar', methods=['POST'])
@login_required
def set_user_avatar():
    """设置用户头像"""
    user_id = g.user_id
    # 获取参数(使用 request.files.get 获取的是form表单页面的name字段,不是ajax中的data数据)
    avatar = request.files.get('avatar')
    # 校验参数
    if not avatar:
        return jsonify(errno=RET.PARAMERR, errmsg='未上传图片')

    # 读取图片数据
    avatar_data = avatar.read()
    # 调用七牛云接口,上传头像
    try:
        image_name = storage(avatar_data)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR, errmsg='上传七牛云失败')
    # 保存头像图片名到数据库
    try:
        User.query.filter_by(id=user_id).update({'avatar_url': image_name})
        db.session.commit()
    except Exception as e:
        # 保存图片名到数据库失败 --> 失败回滚
        db.session.rollback()
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR, errmsg='保存图片名失败')
    avatar_url = QINIU_DOMIN_PREFIX + image_name
    # 返回图片的绝对路径
    return jsonify(errno=RET.OK, errmsg='OK', data={'avatar_url': avatar_url})


@api.route('/user/name', methods=['PUT'])
@login_required
def set_user_name():
    user_id = g.user_id
    # 接收json数据
    user_data = request.get_json()
    # 校验json数据
    if not user_data:
        return jsonify(errno=RET.PARAMERR, errmsg='用户名参数错误')
    # 获取参数(要修改的用户名)
    name = user_data.get('name')
    # 校验参数
    if not name:
        return jsonify(errno=RET.PARAMERR, errmsg='用户名不能为空')
    # 业务处理
    try:

        User.query.filter_by(id=user_id).update({'name': name})
        db.session.commit()
    except Exception as e:
        # 失败回滚
        db.session.rollback()
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg='更新用户名失败')
    # 更新缓存中用户信息
    session['name'] = name
    # 返回结果
    return jsonify(errno=RET.OK, errmsg='OK', data={'name': name})


@api.route('/user/auth', methods=['POST'])
@login_required
def user_auth():
    user_id = g.user_id
    # 获取json数据
    user_data = request.get_json()
    if not user_data:
        return jsonify(errno=RET.PARAMERR, errmsg='参数错误')
    # 获取参数
    real_name = user_data.get('real_name')
    id_card = user_data.get('id_card')
    if not all([real_name, id_card]):
        return jsonify(errno=RET.PARAMERR, errmsg='参数不完整')
    try:
        # 确保只能实名认证一次,所以要加上两个限制条件,real_name=None, id_card=None
        User.query.filter_by(id=user_id, real_name=None, id_card=None).update({'real_name':real_name, 'id_card':id_card})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR, errmsg='实名认证失败')
    return jsonify(errno=RET.OK, errmsg='OK')


@api.route('/user/auth', methods=['GET'])
@login_required
def get_user_auth():
    user_id = g.user_id
    # 查询数据库
    try:
        user = User.query.get(user_id)
        data = user.auth_to_dict()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR, errmsg='查询用户实名信息失败')
    # 校验查询结果
    if not user:
        return jsonify(errno=RET.DATAERR, errmsg='无效操作')
    # 返回
    return jsonify(errno=RET.OK, errmsg='OK', data=data)


@api.route('/session', methods=['DELETE'])
@login_required
def logout():
    """
    退出:
    通过请求上下文对象session来清空用户缓存信息
    :return:
    """
    # bug: csrf_token missing
    # 在清除csrf_token之前,先保存csrf_token
    csrf_token = session.get('csrf_token')
    session.clear()
    # 在清空redis缓存信息之后再次设置csrf_token
    session['csrf_token'] = csrf_token
    return jsonify(errno=0, errmsg='OK')


@api.route('/session', methods=['GET'])
def check_user_login():
    """
    检查用户登陆状态
    1/使用session对象来获取name,redis缓存
    2/判断获取结果,如果有登陆信息,返回name
    3/如果未登录,默认返回false
    :return:
    """
    # 获取用户登陆信息
    user_name = session.get('user_name')
    # 判断获取结果
    if user_name is not None:
        return jsonify(errno=RET.OK, errmsg='true', data={'name': user_name})
    else:
        return jsonify(errno=RET.SESSIONERR, errmsg='false')












