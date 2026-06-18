from solution import group_sum


def test_basic_sum():
    csv_text = "name,amount\nalice,10\nbob,5\nalice,2.5\n"
    assert group_sum(csv_text, "name", "amount") == {"alice": 12.5, "bob": 5.0}


def test_returns_floats():
    csv_text = "k,v\na,1\na,2\n"
    out = group_sum(csv_text, "k", "v")
    assert out == {"a": 3.0}
    assert all(isinstance(v, float) for v in out.values())


def test_ignores_blank_lines():
    csv_text = "\n\nname,amount\nalice,1\n\nbob,2\n\n\n"
    assert group_sum(csv_text, "name", "amount") == {"alice": 1.0, "bob": 2.0}


def test_header_only():
    assert group_sum("name,amount\n", "name", "amount") == {}


def test_empty_input():
    assert group_sum("", "name", "amount") == {}
    assert group_sum("\n\n", "name", "amount") == {}


def test_column_order_independent():
    csv_text = "amount,name\n10,x\n5,y\n3,x\n"
    assert group_sum(csv_text, "name", "amount") == {"x": 13.0, "y": 5.0}


def test_three_columns_picks_right_ones():
    csv_text = "region,product,sales\neast,a,100\nwest,b,50\neast,c,25\n"
    assert group_sum(csv_text, "region", "sales") == {"east": 125.0, "west": 50.0}


def test_negative_and_float_values():
    csv_text = "g,n\nx,-1.5\nx,0.5\ny,4\n"
    assert group_sum(csv_text, "g", "n") == {"x": -1.0, "y": 4.0}
