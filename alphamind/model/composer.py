# -*- coding: utf-8 -*-
"""
Created on 2017-9-27

@author: cheng.li
"""

import copy
import bisect
from typing import Iterable
import pandas as pd
from alphamind.model.modelbase import ModelBase
from alphamind.model.data_preparing import fetch_train_phase
from alphamind.model.data_preparing import fetch_predict_phase
from alphamind.data.engines.universe import Universe
from alphamind.data.engines.sqlengine import SqlEngine
from alphamind.data.winsorize import winsorize_normal
from alphamind.data.standardize import standardize

PROCESS_MAPPING = {
    'winsorize_normal': winsorize_normal,
    'standardize': standardize
}


def _map_process(processes):
    if processes:
        return [p if hasattr(p, '__call__') else PROCESS_MAPPING[p] for p in processes]
    else:
        return None


class DataMeta(object):

    def __init__(self,
                 freq: str,
                 universe: Universe,
                 batch: int,
                 neutralized_risk: Iterable[str] = None,
                 risk_model: str = 'short',
                 pre_process: Iterable[object] = None,
                 post_process: Iterable[object] = None,
                 warm_start: int = 0,
                 data_source: str = None):
        self.data_source = data_source
        self.engine = SqlEngine(self.data_source)
        self.freq = freq
        self.universe = universe
        self.batch = batch
        self.neutralized_risk = neutralized_risk
        self.risk_model = risk_model
        self.pre_process = _map_process(pre_process)
        self.post_process = _map_process(post_process)
        self.warm_start = warm_start

    def save(self) -> dict:
        return dict(
            freq=self.freq,
            universe=self.universe.save(),
            batch=self.batch,
            neutralized_risk=neutralized_risk,
            risk_model=self.risk_model,
            pre_process=[p.__name__ for p in self.pre_process] if pre_process else None,
            post_process=[p.__name__ for p in self.post_process] if pre_process else None,
            warm_start=self.warm_start,
            data_source=self.data_source
        )

    @classmethod
    def load(cls, data_desc: dict):
        freq = data_desc['freq']
        universe = Universe.load(data_desc['universe'])
        batch = data_desc['batch']
        neutralized_risk = data_desc['neutralized_risk']
        risk_model = data_desc['risk_model']
        pre_process = data_desc['pre_process']
        post_process = data_desc['post_process']
        warm_start = data_desc['warm_start']
        data_source = data_desc['data_source']

        return cls(freq=freq,
                   universe=universe,
                   batch=batch,
                   neutralized_risk=neutralized_risk,
                   risk_model=risk_model,
                   pre_process=pre_process,
                   post_process=post_process,
                   warm_start=warm_start,
                   data_source=data_source)


def train_model(ref_date: str,
                alpha_model: ModelBase,
                data_meta: DataMeta):
    train_data = fetch_train_phase(data_meta.engine,
                                   alpha_model.formulas,
                                   ref_date,
                                   data_meta.freq,
                                   data_meta.universe,
                                   data_meta.batch,
                                   data_meta.neutralized_risk,
                                   data_meta.risk_model,
                                   data_meta.pre_process,
                                   data_meta.post_process,
                                   data_meta.warm_start)

    x_values = train_data['train']['x']
    y_values = train_data['train']['y']
    alpha_model.fit(x_values, y_values)
    return copy.deepcopy(alpha_model)


def predict_by_model(ref_date: str,
                     alpha_model: ModelBase,
                     data_meta):
    predict_data = fetch_predict_phase(data_meta.engine,
                                       alpha_model.formulas,
                                       ref_date,
                                       data_meta.freq,
                                       data_meta.universe,
                                       data_meta.batch,
                                       data_meta.neutralized_risk,
                                       data_meta.risk_model,
                                       data_meta.pre_process,
                                       data_meta.post_process,
                                       data_meta.warm_start)

    x_values = predict_data['predict']['x']
    codes = predict_data['predict']['code']

    return pd.DataFrame(alpha_model.predict(x_values).flatten(), index=codes)


class ModelComposer(object):
    def __init__(self,
                 alpha_model: ModelBase,
                 data_meta: DataMeta):
        self.alpha_model = alpha_model
        self.data_meta = data_meta

        self.models = {}
        self.is_updated = False
        self.sorted_keys = None

    def train(self, ref_date: str):
        self.models[ref_date] = train_model(ref_date, self.alpha_model, self.data_meta)
        self.is_updated = False

    def predict(self, ref_date: str, x: pd.DataFrame = None) -> pd.DataFrame:
        model = self._fetch_latest_model(ref_date)
        if x is None:
            return predict_by_model(ref_date, model, self.data_meta)
        else:
            x_values = x.values
            codes = x.index
            return pd.DataFrame(model.predict(x_values).flatten(), index=codes)

    def _fetch_latest_model(self, ref_date) -> ModelBase:
        if self.is_updated:
            sorted_keys = self.sorted_keys
        else:
            sorted_keys = sorted(self.models.keys())
            self.sorted_keys = sorted_keys
            self.is_updated = True

        latest_index = bisect.bisect_left(sorted_keys, ref_date) - 1
        return self.models[sorted_keys[latest_index]]


if __name__ == '__main__':
    import numpy as np
    from alphamind.data.standardize import standardize
    from alphamind.data.winsorize import winsorize_normal
    from alphamind.data.engines.sqlengine import industry_styles
    from alphamind.model.linearmodel import ConstLinearModel

    data_source = "postgres+psycopg2://postgres:we083826@localhost/alpha"
    alpha_model = ConstLinearModel(['EPS'], np.array([1.]))
    alpha_factors = ['EPS']
    freq = '1w'
    universe = Universe('zz500', ['zz500'])
    batch = 4
    neutralized_risk = ['SIZE'] + industry_styles
    risk_model = 'short'
    pre_process = [winsorize_normal, standardize]
    pos_process = [winsorize_normal, standardize]

    data_meta = DataMeta(freq,
                         universe,
                         batch,
                         neutralized_risk,
                         risk_model,
                         pre_process,
                         pos_process,
                         data_source=data_source)

    composer = ModelComposer(alpha_model, data_meta)

    composer.train('2017-09-20')
    composer.train('2017-09-22')
    composer.train('2017-09-25')
    composer.predict('2017-09-21')
