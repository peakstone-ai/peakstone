# Order validation (pydantic v2)

Implement **`solution.py`** using **pydantic v2**
(`from pydantic import BaseModel, ...`).

Define a model `Order` and a parsing helper:

```python
from pydantic import BaseModel

class Order(BaseModel):
    id: int
    customer: str
    quantity: int
    unit_price: float
    # plus a derived `total`

def parse_orders(rows: list[dict]) -> list[Order]:
    ...
```

### `Order` field rules

- `id: int`
- `customer: str` — must be **non-empty** (after no special trimming required; an
  empty string `""` is invalid).
- `quantity: int` — must be **strictly greater than 0**.
- `unit_price: float` — must be **greater than or equal to 0**.
- `total: float` — a **derived/computed** value equal to `quantity * unit_price`.
  Callers should be able to read `order.total`. You may implement it as a
  `@computed_field` property or as a validated field that is always recomputed —
  but it must reflect `quantity * unit_price` and not be settable to an arbitrary
  inconsistent value.

Use pydantic's standard constraint mechanisms (e.g. `Field(gt=0)`,
`Field(ge=0)`, `Field(min_length=1)`, or `field_validator`).

### `parse_orders(rows)`

- Takes a list of dicts and returns a list of validated `Order` instances, one per
  input row, in order.
- If **any** row is invalid, it must raise pydantic's
  `pydantic.ValidationError` (do not catch and swallow it; do not return partial
  results in that case — letting the exception propagate from the first invalid
  row is fine).

Example:

```python
orders = parse_orders([
    {"id": 1, "customer": "Acme", "quantity": 3, "unit_price": 2.5},
])
orders[0].total           # 7.5

parse_orders([{"id": 2, "customer": "X", "quantity": 0, "unit_price": 1.0}])
# raises pydantic.ValidationError  (quantity must be > 0)
```
