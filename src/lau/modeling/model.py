"""PDModel: fixed modeling template (regularized LR baseline, LightGBM, XGBoost) with deterministic preprocessing
and per-feature contributions (log-odds space) for adverse-action reason codes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from lau.data.features import FeatureSpec, apply_features

HIGH_CARD = 30
SEED = 7


class PDModel:
    def __init__(
        self, model_type: str, params: dict, features: list[str], engineered: list[FeatureSpec], definition_version: str
    ) -> None:
        self.model_type = model_type
        self.params = dict(params)
        self.features = list(features)  # model inputs (base + engineered names)
        self.engineered = list(engineered)
        self.definition_version = definition_version
        self.cat_levels: dict[str, list[str]] = {}
        self.freq_maps: dict[str, dict[str, float]] = {}
        self.medians: dict[str, float] = {}
        self.means: dict[str, float] = {}
        self.stds: dict[str, float] = {}
        self.lr_columns: list[str] = []
        self.estimator = None
        self.best_iteration: int | None = None

    # ---- preprocessing ----------------------------------------------------------------------------------
    def _raw(self, df: pd.DataFrame) -> pd.DataFrame:
        need_eng = [s for s in self.engineered if s.name in self.features and s.name not in df.columns]
        if need_eng:
            df = apply_features(df, need_eng)
        missing = [f for f in self.features if f not in df.columns]
        if missing:
            raise KeyError(f"missing model inputs: {missing[:5]}")
        return df[self.features]

    def _fit_prep(self, X: pd.DataFrame) -> None:
        for c in X.columns:
            s = X[c]
            if _is_cat(s):
                vc = s.astype(str).value_counts()
                if len(vc) > HIGH_CARD:
                    self.freq_maps[c] = (vc / len(s)).to_dict()
                else:
                    self.cat_levels[c] = sorted(vc.index.tolist())
            else:
                v = pd.to_numeric(s, errors="coerce").astype(float)
                self.medians[c] = float(v.median()) if v.notna().any() else 0.0

    def _tree_matrix(self, X: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for c in X.columns:
            if c in self.freq_maps:
                out[c] = X[c].astype(str).map(self.freq_maps[c]).fillna(0.0).astype(float)
            elif c in self.cat_levels:
                out[c] = pd.Categorical(X[c].astype(str), categories=self.cat_levels[c])
            else:
                out[c] = pd.to_numeric(X[c], errors="coerce").astype(float)
        return pd.DataFrame(out, index=X.index)

    def _lr_matrix(self, X: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        parts = []
        for c in X.columns:
            if c in self.freq_maps:
                parts.append(X[c].astype(str).map(self.freq_maps[c]).fillna(0.0).astype(float).rename(c))
            elif c in self.cat_levels:
                cat = pd.Categorical(X[c].astype(str), categories=self.cat_levels[c])
                d = pd.get_dummies(cat, prefix=c, prefix_sep="=", dtype=float)
                d.index = X.index
                parts.append(d.iloc[:, 1:])  # drop first level
            else:
                v = pd.to_numeric(X[c], errors="coerce").astype(float)
                parts.append(v.isna().astype(float).rename(f"{c}__missing"))
                parts.append(v.fillna(self.medians[c]).rename(c))
        M = pd.concat(parts, axis=1)
        if fit:
            self.lr_columns = [c for c in M.columns if M[c].std() > 0]
            self.means = {c: float(M[c].mean()) for c in self.lr_columns}
            self.stds = {c: float(M[c].std()) or 1.0 for c in self.lr_columns}
        M = M.reindex(columns=self.lr_columns, fill_value=0.0)
        return (M - pd.Series(self.means)) / pd.Series(self.stds)

    # ---- fit / predict -----------------------------------------------------------------------------------
    def fit(self, df: pd.DataFrame, y: np.ndarray, es_mask: np.ndarray | None = None) -> PDModel:
        X = self._raw(df)
        fit_mask = ~es_mask if es_mask is not None and es_mask.any() else np.ones(len(X), bool)
        self._fit_prep(X[fit_mask])
        y = np.asarray(y)
        if self.model_type == "logreg":
            from sklearn.linear_model import LogisticRegression

            M = self._lr_matrix(X[fit_mask], fit=True)
            C = float(self.params.get("C", 0.1))
            if self.params.get("penalty") == "l1":
                est = LogisticRegression(C=C, l1_ratio=1.0, solver="saga", max_iter=3000, random_state=SEED)
            else:
                est = LogisticRegression(C=C, max_iter=2000, random_state=SEED)
            self.estimator = est.fit(M, y[fit_mask])
        elif self.model_type == "lightgbm":
            import lightgbm as lgb

            T = self._tree_matrix(X)
            p = {
                "objective": "binary",
                "verbose": -1,
                "seed": SEED,
                "deterministic": True,
                "force_row_wise": True,
                "num_threads": 4,
                **{k: v for k, v in self.params.items() if k != "n_estimators"},
            }
            dtrain = lgb.Dataset(T[fit_mask], y[fit_mask], free_raw_data=False)
            valid = [lgb.Dataset(T[~fit_mask], y[~fit_mask], reference=dtrain)] if (~fit_mask).any() else []
            cb = [lgb.early_stopping(50, verbose=False)] if valid else []
            self.estimator = lgb.train(
                p, dtrain, num_boost_round=int(self.params.get("n_estimators", 500)), valid_sets=valid, callbacks=cb
            )
            self.best_iteration = self.estimator.best_iteration or None
        elif self.model_type == "xgboost":
            import xgboost as xgb

            T = self._tree_matrix(X)
            p = {
                "objective": "binary:logistic",
                "eval_metric": "auc",
                "seed": SEED,
                "tree_method": "hist",
                "nthread": 4,
                **{k: v for k, v in self.params.items() if k != "n_estimators"},
            }
            dtrain = xgb.DMatrix(T[fit_mask], y[fit_mask], enable_categorical=True)
            evals = (
                [(xgb.DMatrix(T[~fit_mask], y[~fit_mask], enable_categorical=True), "es")] if (~fit_mask).any() else []
            )
            self.estimator = xgb.train(
                p,
                dtrain,
                num_boost_round=int(self.params.get("n_estimators", 500)),
                evals=evals,
                early_stopping_rounds=50 if evals else None,
                verbose_eval=False,
            )
            self.best_iteration = getattr(self.estimator, "best_iteration", None)
        else:
            raise ValueError(f"unknown model_type {self.model_type}")
        return self

    def predict_pd(self, df: pd.DataFrame) -> np.ndarray:
        X = self._raw(df)
        if self.model_type == "logreg":
            return self.estimator.predict_proba(self._lr_matrix(X))[:, 1]
        if self.model_type == "lightgbm":
            return self.estimator.predict(self._tree_matrix(X), num_iteration=self.best_iteration)
        import xgboost as xgb

        d = xgb.DMatrix(self._tree_matrix(X), enable_categorical=True)
        rng = (0, self.best_iteration + 1) if self.best_iteration is not None else (0, 0)
        return self.estimator.predict(d, iteration_range=rng)

    def contributions(self, df: pd.DataFrame) -> pd.DataFrame:
        """Per-input-feature contribution to log-odds of default (positive = pushes toward default)."""
        X = self._raw(df)
        if self.model_type == "logreg":
            M = self._lr_matrix(X)
            contrib = M * self.estimator.coef_[0]
            groups = {c: c.split("=")[0].replace("__missing", "") for c in contrib.columns}
            return contrib.T.groupby(groups).sum().T.reindex(columns=self.features, fill_value=0.0)
        if self.model_type == "lightgbm":
            arr = self.estimator.predict(self._tree_matrix(X), num_iteration=self.best_iteration, pred_contrib=True)
            return pd.DataFrame(np.asarray(arr)[:, :-1], columns=self.features, index=X.index)
        import xgboost as xgb

        d = xgb.DMatrix(self._tree_matrix(X), enable_categorical=True)
        rng = (0, self.best_iteration + 1) if self.best_iteration is not None else (0, 0)
        arr = self.estimator.predict(d, pred_contribs=True, iteration_range=rng)
        return pd.DataFrame(arr[:, :-1], columns=self.features, index=X.index)

    def feature_importance(self) -> dict[str, float]:
        if self.model_type == "logreg":
            imp = pd.Series(np.abs(self.estimator.coef_[0]), index=self.lr_columns)
            groups = {c: c.split("=")[0].replace("__missing", "") for c in imp.index}
            s = imp.groupby(groups).sum()
        elif self.model_type == "lightgbm":
            s = pd.Series(self.estimator.feature_importance("gain"), index=self.features)
        else:
            s = pd.Series(self.estimator.get_score(importance_type="total_gain")).reindex(self.features).fillna(0)
        total = s.sum() or 1.0
        return {k: float(v / total) for k, v in s.sort_values(ascending=False).items()}

    @property
    def raw_inputs(self) -> list[str]:
        """Columns a caller must supply: base features + source columns of engineered features."""
        eng = {s.name: s for s in self.engineered}
        cols: list[str] = []
        for f in self.features:
            for c in eng[f].source_columns if f in eng else (f,):
                if c not in cols:
                    cols.append(c)
        return cols

    def describe(self) -> dict:
        return {
            "model_type": self.model_type,
            "params": self.params,
            "features": self.features,
            "engineered": [s.name for s in self.engineered],
            "definition_version": self.definition_version,
        }


def _is_cat(s: pd.Series) -> bool:
    return (
        s.dtype == object
        or isinstance(s.dtype, pd.CategoricalDtype)
        or pd.api.types.is_string_dtype(s)
        or pd.api.types.is_bool_dtype(s)
    )
