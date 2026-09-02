from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lob_mcp.prompts import PromptRegistry
from lob_mcp.resources import ResourceRegistry, TextResource


class OrderAssistantPromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, description="需要查询的订单号")


def create_resource_registry() -> ResourceRegistry:
    registry = ResourceRegistry()
    registry.register(
        TextResource(
            uri="docs://orders/status-guide",
            name="订单状态说明",
            description="订单状态代码及其中文含义",
            mime_type="text/markdown",
            text=(
                "# 订单状态说明\n\n"
                "- `processing`：订单处理中\n"
                "- `shipped`：订单已发货\n"
                "- `delivered`：订单已签收\n"
                "- `cancelled`：订单已取消\n"
            ),
        )
    )
    registry.register_template(
        uri_template="orders://{order_id}",
        name="订单详情资源",
        description="按订单号定位订单详情的 URI 模板",
        mime_type="application/json",
    )
    return registry


def create_prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.register(
        name="order.assistant",
        description="生成订单查询助手的任务消息",
        arguments_model=OrderAssistantPromptInput,
        renderer=lambda params: (
            f"请调用 order.query 查询订单 {params.order_id}，"
            "结合订单状态说明，用简洁中文回答用户。"
        ),
    )
    return registry

