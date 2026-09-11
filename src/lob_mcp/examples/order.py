from __future__ import annotations

import asyncio
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


class OrderCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=64, description="要取消的订单号")
    reason: str = Field(min_length=2, max_length=200, description="取消原因")


class WaitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seconds: float = Field(ge=0.1, le=30, description="等待秒数，用于验证超时和取消")


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


def cancel_order(params: OrderCancelInput) -> dict[str, Any]:
    order = ORDERS.get(params.order_id)
    if order is None:
        return {"orderId": params.order_id, "cancelled": False, "message": "未找到该订单"}
    if order["status"] == "shipped":
        return {"orderId": params.order_id, "cancelled": False, "message": "订单已发货，不能取消"}
    order["status"] = "cancelled"
    order["statusText"] = "已取消"
    return {
        "orderId": params.order_id,
        "cancelled": True,
        "reason": params.reason,
    }


async def wait_for_cancellation(params: WaitInput) -> dict[str, Any]:
    await asyncio.sleep(params.seconds)
    return {"waitedSeconds": params.seconds}


def create_order_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        name="order.query",
        description="根据订单号查询订单状态和物流信息",
        input_model=OrderQueryInput,
        handler=query_order,
    )
    registry.register(
        name="order.cancel",
        description="取消尚未发货的订单（高风险写操作）",
        input_model=OrderCancelInput,
        handler=cancel_order,
    )
    registry.register(
        name="demo.wait",
        description="等待指定秒数，用于验证超时与协作式取消",
        input_model=WaitInput,
        handler=wait_for_cancellation,
    )
    return registry
