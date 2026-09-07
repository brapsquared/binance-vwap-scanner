import pandas as pd

x = pd.read_csv("results/events_with_baseline.csv", parse_dates=["signal_date"])
for strategy, side in [
    ("cross_7_30_regime", "short"),
    ("fresh_stack", "short"),
    ("pullback_recapture", "short"),
    ("cross_7_30_regime", "long"),
]:
    group = x[(x.strategy == strategy) & (x.side == side) & (x.split == "test")]
    print("\n", strategy, side, "events", len(group), "dates", group.signal_date.nunique(), "symbols", group.symbol.nunique())
    for horizon in [1, 3, 5, 10, 20, 30]:
        returns = group[f"ret_{horizon}d"]
        edge = group[f"edge_{horizon}d"]
        print(horizon, "median", round(returns.median() * 100, 2), "hit", round((returns > 0).mean() * 100, 1), "edge", round(edge.median() * 100, 2), "edgehit", round((edge > 0).mean() * 100, 1))
    print("MFE20", round(group.mfe_20d.median() * 100, 2), "MAE20", round(group.mae_20d.median() * 100, 2))
    print("top symbols", group.symbol.value_counts().head(8).to_dict())

quarterly = x[(x.strategy == "cross_7_30_regime") & (x.side == "short")].copy()
quarterly["quarter"] = quarterly.signal_date.dt.to_period("Q").astype(str)
print("\nquarterly short cross 20d")
print(quarterly.groupby(["split", "quarter"]).ret_20d.agg(["count", "median", "mean"]).to_string())
