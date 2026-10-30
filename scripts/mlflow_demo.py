#!/usr/bin/env python3
"""Train a tiny churn model and register it in MLflow, so FlowMind's ML nodes have something real to use.

    pip install mlflow scikit-learn pandas
    mlflow server --host 127.0.0.1 --port 5000            # terminal 1: the tracking server + registry
    python scripts/mlflow_demo.py http://127.0.0.1:5000    # terminal 2: registers 'churn-model' versions 1 and 2
    mlflow models serve -m "models:/churn-model/1" -p 5001 --env-manager local --no-conda   # terminal 3: a scoring endpoint

Everything is synthetic. Version 2 is trained on slightly better data, so promotion gates have something to compare.
"""
import sys

import mlflow
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

FEATURES = ["tenure_months", "monthly_spend", "support_tickets"]


def make_data(n: int, seed: int, noise: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "tenure_months": rng.integers(1, 72, n),
        "monthly_spend": rng.normal(60, 20, n).round(2).clip(10, None),
        "support_tickets": rng.poisson(1.5, n),
    })
    score = -0.04 * df.tenure_months + 0.35 * df.support_tickets + 0.01 * df.monthly_spend + rng.normal(0, noise, n)
    df["churned"] = (score > np.median(score)).astype(int)
    return df


def main(uri: str) -> None:
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("churn")
    for version, noise in ((1, 1.2), (2, 0.4)):
        df = make_data(2000, seed=version, noise=noise)
        X_tr, X_te, y_tr, y_te = train_test_split(df[FEATURES], df.churned, test_size=0.25, random_state=0)
        with mlflow.start_run(run_name=f"churn-v{version}"):
            model = LogisticRegression(max_iter=500).fit(X_tr, y_tr)
            acc = accuracy_score(y_te, model.predict(X_te))
            mlflow.log_metric("accuracy", acc)
            mlflow.log_param("noise", noise)
            mlflow.sklearn.log_model(model, name="model", registered_model_name="churn-model", input_example=X_tr.head(3))
            print(f"registered churn-model v{version}  accuracy={acc:.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000")
