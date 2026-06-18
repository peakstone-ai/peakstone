def group_sum(csv_text: str, key_col: str, val_col: str) -> dict[str, float]:
    lines = [ln for ln in csv_text.splitlines() if ln.strip() != ""]
    if not lines:
        return {}
    header = [h.strip() for h in lines[0].split(",")]
    ki = header.index(key_col)
    vi = header.index(val_col)
    out: dict[str, float] = {}
    for line in lines[1:]:
        cells = line.split(",")
        key = cells[ki].strip()
        val = float(cells[vi].strip())
        out[key] = out.get(key, 0.0) + val
    return out
