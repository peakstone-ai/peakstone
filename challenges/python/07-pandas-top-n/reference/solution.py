import pandas as pd


def top_n_per_group(df: pd.DataFrame, group_col: str, value_col: str, n: int) -> pd.DataFrame:
    # Stable sort within each group by value descending, preserving group order
    # of first appearance via a categorical-like key.
    order = {g: i for i, g in enumerate(df[group_col].drop_duplicates())}
    tmp = df.copy()
    tmp["__grp_order__"] = tmp[group_col].map(order)
    tmp = tmp.sort_values(
        ["__grp_order__", value_col],
        ascending=[True, False],
        kind="stable",
    )
    out = tmp.groupby(group_col, sort=False).head(n)
    out = out.drop(columns="__grp_order__")
    return out[df.columns].reset_index(drop=True)
