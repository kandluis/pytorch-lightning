# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import numbers
import warnings
from typing import Any, Optional

import torch
from torch.nn import DataParallel
from torch.nn.parallel import DistributedDataParallel

from pytorch_lightning.core.lightning import LightningModule
from pytorch_lightning.overrides.base import _LightningModuleWrapperBase
from pytorch_lightning.overrides.distributed import LightningDistributedModule
from pytorch_lightning.utilities import rank_zero_warn
from pytorch_lightning.utilities.apply_func import apply_to_collection


class LightningDataParallel(DataParallel):

    def __init__(self, module: LightningModule, *args, **kwargs):
        warnings.warn(
            "The usage of `LightningDataParallel` is deprecated since v1.2 and will be removed in v1.4."
            " From now on we recommend to directly subclass `torch.nn.parallel.DataParallel`.", DeprecationWarning
        )
        super().__init__(LightningParallelModule(module), *args, **kwargs)


class LightningDistributedDataParallel(DistributedDataParallel):

    def __init__(self, module: LightningModule, *args, **kwargs):
        warnings.warn(
            "The usage of `LightningDistributedDataParallel` is deprecated since v1.2 and will be removed in v1.4."
            " From now on we recommend to directly subclass `torch.nn.parallel.DistributedDataParallel`.",
            DeprecationWarning
        )
        super().__init__(LightningDistributedModule(module), *args, **kwargs)


class LightningParallelModule(_LightningModuleWrapperBase):
    """
    Wraps the user's LightningModule and redirects the forward call to the appropriate
    method, either ``training_step``, ``validation_step``, ``test_step`` or ``predict``.
    This class is used in combination with :class:`~torch.nn.parallel.DataParallel` as
    shown in the example. It also takes care of converting Python scalars to Tensors and
    un-squeezes 0-dimensional Tensors as it is required by :class:`~torch.nn.parallel.DataParallel`.

    Example:

        dp_model = torch.nn.DataParallel(
            module=LightningParallelModule(lightning_module),
            device_ids=[3, 4],
            ...
        )

    Args:
        pl_module: the model to wrap

    """

    def __init__(self, pl_module: LightningModule):
        super().__init__(pl_module)

    def forward(self, *inputs, **kwargs):
        self.update_replica_device_attributes(inputs)
        # forward call will redirect to training_step, validation_step, etc.
        output = super().forward(*inputs, **kwargs)

        def output_transform(data: Any):
            data = python_scalar_to_tensor(data, self.module.device)
            data = unsqueeze_scalar_tensor(data)
            return data

        output = apply_to_collection(
            output,
            dtype=(numbers.Number, torch.Tensor),
            function=output_transform,
        )
        return output

    def update_replica_device_attributes(self, inputs: Any) -> None:
        first_parameter = next(self.parameters(), None)
        if first_parameter is None:
            rank_zero_warn(
                "Could not determine on which device the inputs are."
                "When using DataParallel (accelerator='dp'), be aware that in case you are using self.device"
                "in your code it will reference only the root device."
            )

        # by calling .to() we force the update to the self.device property
        self.module.to(device=first_parameter.device)

        # def find_tensor_with_device(tensor: torch.Tensor):
        #     nonlocal replica_device
        #     if replica_device is None and tensor.device != torch.device("cpu"):
        #         replica_device = tensor.device
        #     return tensor
        #
        # apply_to_collection(inputs, dtype=torch.Tensor, function=find_tensor_with_device)
        #
        # if replica_device is not None:
        #     # by calling .to() we force the update to the self.device property
        #     self.module.to(device=replica_device)
        # else:
        #     rank_zero_warn(
        #         "Could not determine on which device the inputs are."
        #         "When using DataParallel (accelerator='dp'), be aware that in case you are using self.device"
        #         "in your code it will reference only the root device."
        #     )


def python_scalar_to_tensor(data: Any, device: torch.device = torch.device("cpu")) -> Any:
    """ Converts a Python scalar number to a torch tensor and places it on the given device. """
    if isinstance(data, numbers.Number):
        data = torch.tensor([data], device=device)
    return data


def unsqueeze_scalar_tensor(data: Any) -> Any:
    """ Un-squeezes a 0-dim tensor. """
    if isinstance(data, torch.Tensor) and data.dim() == 0:
        data = data.unsqueeze(0)
    return data
