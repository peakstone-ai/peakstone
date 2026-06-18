import pytest
from pydantic import ValidationError

from solution import Order, parse_orders


def test_valid_parse():
    orders = parse_orders([
        {"id": 1, "customer": "Acme", "quantity": 3, "unit_price": 2.5},
        {"id": 2, "customer": "Beta", "quantity": 1, "unit_price": 10.0},
    ])
    assert len(orders) == 2
    assert isinstance(orders[0], Order)
    assert orders[0].id == 1
    assert orders[0].customer == "Acme"


def test_computed_total():
    orders = parse_orders([
        {"id": 1, "customer": "Acme", "quantity": 3, "unit_price": 2.5},
    ])
    assert orders[0].total == pytest.approx(7.5)


def test_total_zero_price():
    orders = parse_orders([
        {"id": 1, "customer": "Acme", "quantity": 4, "unit_price": 0.0},
    ])
    assert orders[0].total == pytest.approx(0.0)


def test_invalid_quantity_zero_raises():
    with pytest.raises(ValidationError):
        parse_orders([{"id": 2, "customer": "X", "quantity": 0, "unit_price": 1.0}])


def test_invalid_negative_quantity_raises():
    with pytest.raises(ValidationError):
        parse_orders([{"id": 2, "customer": "X", "quantity": -1, "unit_price": 1.0}])


def test_invalid_negative_price_raises():
    with pytest.raises(ValidationError):
        parse_orders([{"id": 3, "customer": "Y", "quantity": 1, "unit_price": -0.01}])


def test_empty_customer_raises():
    with pytest.raises(ValidationError):
        parse_orders([{"id": 4, "customer": "", "quantity": 1, "unit_price": 1.0}])


def test_one_bad_row_in_batch_raises():
    rows = [
        {"id": 1, "customer": "Acme", "quantity": 3, "unit_price": 2.5},
        {"id": 2, "customer": "Beta", "quantity": 0, "unit_price": 1.0},  # bad
    ]
    with pytest.raises(ValidationError):
        parse_orders(rows)


def test_total_serialized_in_dump():
    o = parse_orders([{"id": 1, "customer": "Acme", "quantity": 2, "unit_price": 3.0}])[0]
    data = o.model_dump()
    assert data["total"] == pytest.approx(6.0)
