from pydantic import BaseModel, Field, computed_field


class Order(BaseModel):
    id: int
    customer: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)

    @computed_field
    @property
    def total(self) -> float:
        return self.quantity * self.unit_price


def parse_orders(rows: list[dict]) -> list[Order]:
    return [Order(**row) for row in rows]
