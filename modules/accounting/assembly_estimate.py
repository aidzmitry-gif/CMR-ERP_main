"""Non-posting assembly estimate. Exact BYN inputs are assumptions, not book cost."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from modules.accounting.schemas import Input, Money, Quantity, exact

Price = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, max_digits=18, decimal_places=6)]
Percent = Annotated[Decimal, BeforeValidator(exact), Field(ge=0, le=100, decimal_places=4)]


class Component(Input):
    name: str = Field(min_length=1, max_length=255)
    unit: str = Field(default="шт", min_length=1, max_length=32)
    per_unit: Quantity
    loss_percent: Percent = Decimal(0)
    unit_cost_byn: Price | None = None
    price_basis: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def price_evidence(self):
        if self.unit_cost_byn is not None and not self.price_basis:
            raise ValueError("Укажите источник плановой цены комплектующего")
        return self


class BatchCosts(Input):
    labor_byn: Money
    contributions_byn: Money
    subcontract_byn: Money
    overhead_byn: Money
    packaging_byn: Money


CostCategory = Literal[
    "labor_byn", "contributions_byn", "subcontract_byn", "overhead_byn", "packaging_byn"
]


class CostArticleBinding(Input):
    category: CostCategory
    article_id: int = Field(gt=0, strict=True)


class AssemblyEstimateInput(Input):
    product: str = Field(min_length=1, max_length=255)
    quantity: Quantity
    purpose: Literal["customer_order", "stock"]
    reference: str = Field(min_length=1, max_length=200)
    specification: str = Field(min_length=1, max_length=200)
    as_of: date
    components: list[Component] = Field(min_length=1, max_length=300)
    batch_costs: BatchCosts
    batch_cost_articles: list[CostArticleBinding] = Field(default_factory=list, max_length=5)
    sale_unit_net_byn: Price | None = None

    @model_validator(mode="after")
    def unique_cost_article_categories(self):
        categories = [row.category for row in self.batch_cost_articles]
        if len(categories) != len(set(categories)):
            raise ValueError("Выберите не более одной статьи на каждый вид затрат партии")
        return self


def money(value):
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def calculate(data: AssemblyEstimateInput):
    """Loss is an explicit extra consumption allowance, not a yield percentage."""
    with localcontext() as context:
        context.prec = 80
        lines, missing, known = [], [], Decimal(0)
        for index, row in enumerate(data.components, 1):
            quantity = data.quantity * row.per_unit * (1 + row.loss_percent / 100)
            amount = None if row.unit_cost_byn is None else money(quantity * row.unit_cost_byn)
            if amount is None:
                missing.append(index)
            else:
                known += Decimal(amount)
            lines.append({"line_no": index, "name": row.name, "unit": row.unit,
                          "quantity": format(quantity, "f"), "cost_byn": amount})
        extra = sum(data.batch_costs.model_dump().values(), Decimal(0))
        total = None if missing else known + extra
        revenue = None if data.sale_unit_net_byn is None else Decimal(money(data.quantity * data.sale_unit_net_byn))
        profit = None if total is None or revenue is None else revenue - total
        return {
            "version": "assembly-estimate-v1", "status": "incomplete" if missing else "estimated",
            "currency": "BYN", "input": data.model_dump(mode="json"), "lines": lines,
            "missing_price_lines": missing, "known_components_byn": money(known),
            "batch_costs_byn": money(extra), "total_cost_byn": None if total is None else money(total),
            "unit_cost_byn": None if total is None else format((total / data.quantity).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP), ".6f"),
            "revenue_net_byn": None if revenue is None else money(revenue),
            "gross_profit_byn": None if profit is None else money(profit),
            "margin_percent": None if profit is None or not revenue else money(profit / revenue * 100),
            "posted": False,
        }
