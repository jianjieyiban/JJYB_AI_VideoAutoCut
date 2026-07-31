# -*- coding: utf-8 -*-
"""硬件能力 API。"""

from flask import Blueprint, jsonify

from backend.services.hardware_capability_service import hardware_capability_service

hardware_capability_bp = Blueprint("hardware_capability", __name__)


def register_hardware_capability_routes(app):
    app.register_blueprint(hardware_capability_bp, url_prefix="/api/hardware")


@hardware_capability_bp.route("/capabilities", methods=["GET"])
def capabilities():
    return jsonify({"code": 0, "msg": "已获取硬件能力", "data": hardware_capability_service.capabilities()})
