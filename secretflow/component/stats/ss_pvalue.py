# Copyright 2023 Ant Group Co., Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import numpy as np

from secretflow.component.component import CompEvalError, Component, IoType
from secretflow.component.data_utils import DistDataType, load_table
from secretflow.component.ml.linear.ss_sgd import load_ss_sgd_model
from secretflow.device.device.spu import SPU
from secretflow.protos.component.comp_pb2 import Attribute, AttrType
from secretflow.protos.component.data_pb2 import DistData
from secretflow.protos.component.report_pb2 import Descriptions, Div, Report, Tab
from secretflow.stats.ss_pvalue_v import PVlaue

ss_pvalue_comp = Component(
    "ss_pvalue",
    domain="stats",
    version="0.0.1",
    desc="""Calculate P-Value for LR model training on vertical partitioning dataset by using secret sharing.

    For large dataset(large than 10w samples & 200 features),
    recommend to use [Ring size: 128, Fxp: 40] options for SPU device.
    """,
)
ss_pvalue_comp.io(
    io_type=IoType.INPUT,
    name="model",
    desc="Input model.",
    types=[DistDataType.SS_SGD_MODEL],
)
ss_pvalue_comp.io(
    io_type=IoType.INPUT,
    name="input_data",
    desc="Input dataset.",
    types=[DistDataType.VERTICAL_TABLE],
)
ss_pvalue_comp.io(
    io_type=IoType.OUTPUT,
    name="report",
    desc="Output report.",
    types=[DistDataType.REPORT],
)


@ss_pvalue_comp.eval_fn
def ss_pearsonr_eval_fn(
    *,
    ctx,
    model,
    input_data,
    report,
):
    if ctx.spu_configs is None or len(ctx.spu_configs) == 0:
        raise CompEvalError("spu config is not found.")
    if len(ctx.spu_configs) > 1:
        raise CompEvalError("only support one spu")
    spu_config = next(iter(ctx.spu_configs.values()))

    spu = SPU(spu_config["cluster_def"], spu_config["link_desc"])

    model = load_ss_sgd_model(ctx, spu, model)

    x = load_table(ctx, input_data, load_features=True)
    y = load_table(ctx, input_data, load_labels=True)

    with ctx.tracer.trace_running():
        pv: np.ndarray = PVlaue(spu).pvalues(x, y, model)

    feature_names = x.columns

    assert pv.shape[0] == len(feature_names) + 1  # last one is bias

    r_desc = Descriptions(
        items=[
            Descriptions.Item(
                name=feature_names[i], type=AttrType.AT_FLOAT, value=Attribute(f=pv[i])
            )
            for i in range(len(feature_names))
        ]
        + [
            Descriptions.Item(
                name="bias",
                type=AttrType.AT_FLOAT,
                value=Attribute(f=pv[len(feature_names)]),
            )
        ],
    )

    report_mate = Report(
        name="pvalue",
        desc="pvalue list",
        tabs=[
            Tab(
                divs=[
                    Div(
                        children=[
                            Div.Child(
                                type="descriptions",
                                descriptions=r_desc,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    report_dd = DistData(
        name=report,
        type=str(DistDataType.REPORT),
        sys_info=input_data.sys_info,
    )
    report_dd.meta.Pack(report_mate)

    return {"report": report_dd}
