from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lob_mcp.tools import ToolRegistry


class OrderQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(
        min_length=1,
        max_length=64,
        description="要查询的订单号，例如 ORD-20250902-001",
    )


ORDERS: dict[str, dict[str, Any]] = {
    "ORD-20250902-001": {
        "orderId": "ORD-20250902-001",
        "status": "shipped",
        "statusText": "已发货",
        "carrier": "顺丰速运",
        "trackingNumber": "SF1234567890",
    },
    "ORD-20250902-002": {
        "orderId": "ORD-20250902-002",
        "status": "processing",
        "statusText": "处理中",
        "carrier": None,
        "trackingNumber": None,
    },
}


def query_order(params: OrderQueryInput) -> dict[str, Any]:
    order = ORDERS.get(params.order_id)
    if order is None:
        return {
            "orderId": params.order_id,
            "found": False,
            "message": "未找到该订单",
        }
    return {"found": True, **order}


def create_order_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        name="order.query",
        description="根据订单号查询订单状态和物流信息",
        input_model=OrderQueryInput,
        handler=query_order,
    )
    return registry

