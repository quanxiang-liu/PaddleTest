import os
os.environ['FLAGS_cinn_new_group_scheduler'] = '1'
os.environ['FLAGS_group_schedule_tiling_first'] = '1'
os.environ['FLAGS_enable_pir_api'] = '1'
os.environ['FLAGS_cinn_bucket_compile'] = '1'
import sys
import unittest
import numpy as np
from dataclasses import dataclass
import typing as t

@dataclass
class Stage:
    name: str
    env_vars: t.Dict[str, str]

cinn_stages = [
    Stage(
        name="dynamic_to_static",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=False,
            FLAGS_prim_enable_dynamic=False,
        ),
    ),
    Stage(
        name="prim",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
        ),
    ),
    Stage(
        name="infer_symbolic",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=False,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=False,
            FLAGS_check_infer_symbolic=True,
        ),
    ),
	Stage(
        name="frontend",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=True,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=True,
            FLAGS_check_infer_symbolic=False,
            FLAGS_enable_fusion_fallback=True,
        ), 
    ),
    Stage(
        name="backend",
        env_vars=dict(
            PADDLE_DEBUG_ENABLE_CINN=True,
            FLAGS_prim_all=True,
            FLAGS_prim_enable_dynamic=True,
            FLAGS_use_cinn=True,
            FLAGS_check_infer_symbolic=False,
            FLAGS_enable_fusion_fallback=False,
        ), 
    ),
]

def GetCinnStageByName(name):
    for stage in cinn_stages:
        if stage.name == name:
            return stage
    return None

def GetCurrentCinnStage():
    name = os.getenv('PADDLE_DEBUG_CINN_STAGE_NAME')
    if name is None:
        return None
    stage_names = [stage.name for stage in cinn_stages]
    assert name in stage_names, (
        f"PADDLE_DEBUG_CINN_STAGE_NAME should be in {stage_names}"
    )
    return GetCinnStageByName(name)

def GetPrevCinnStage(stage):
    for i in range(1, len(cinn_stages)):
        if stage is cinn_stages[i]:
            return cinn_stages[i - 1]
    return None

def IsCinnStageEnableDiff():
    value = os.getenv('PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF')
    enabled = value in {
        '1',
        'true',
        'True',
    }
    if enabled:
        assert GetCurrentCinnStage() is not None
    return enabled

last_cinn_stage_exit_code = None
def LastCINNStageFailed():
    global last_cinn_stage_exit_code
    if last_cinn_stage_exit_code is not None:
        return last_cinn_stage_exit_code != 0
    last_stage = GetPrevCinnStage(GetCurrentCinnStage())
    if last_stage is None:
        return False
    env_vars = dict(
        PADDLE_DEBUG_CINN_STAGE_NAME=last_stage.name,
        PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF='0',
    )
    env_vars_str = " ".join(
        f"{env_var}={value}"
        for env_var, value in env_vars.items()
    )
    last_cinn_stage_exit_code = os.system(
        f"{env_vars_str} {sys.executable} {__file__} > /dev/null 2>&1"
    )
    return last_cinn_stage_exit_code != 0

def SetDefaultEnv(**env_var2value):
    for env_var, value in env_var2value.items():
        if os.getenv(env_var) is None:
            os.environ[env_var] = str(value)

SetDefaultEnv(
    PADDLE_DEBUG_CINN_STAGE_NAME="backend",
    PADDLE_DEBUG_CINN_STAGE_ENABLE_DIFF=False,
    PADDLE_DEBUG_ENABLE_CINN=True,
    FLAGS_enable_pir_api=True,
    FLAGS_prim_all=True,
    FLAGS_prim_enable_dynamic=True,
    FLAGS_use_cinn=False,
    FLAGS_check_infer_symbolic=False,
    FLAGS_enable_fusion_fallback=False,
)

last_stage_failed = (IsCinnStageEnableDiff() and LastCINNStageFailed())

import paddle

def SetEnvVar(env_var2value):
    for env_var, value in env_var2value.items():
        os.environ[env_var] = str(value)
    paddle.set_flags({
        env_var:value
        for env_var, value in env_var2value.items()
        if env_var.startswith('FLAGS_')
    })

if GetCurrentCinnStage() is not None:
    SetEnvVar(GetCurrentCinnStage().env_vars)

def NumOperationsInBlock(block_idx):
    return [82][block_idx] - 1 # number-of-ops-in-block

def GetPaddleDebugNumAllowedOps():
    try:
        return int(os.getenv('PADDLE_DEBUG_NUM_ALLOWED_OPS'))
    except:
        return None

paddle_debug_num_allowed_ops = GetPaddleDebugNumAllowedOps()


if type(paddle_debug_num_allowed_ops) is not int:
    def EarlyReturn(block_idx, op_idx):
        return False      
else:
    def EarlyReturn(block_idx, op_idx):
        return op_idx >= paddle_debug_num_allowed_ops

class BlockEntries:

    def builtin_module_0_0_0(self, parameter_0, data_0, data_1):

        # pd_op.full_int_array: (4xi64) <- ()
        full_int_array_0 = [22, 16, 12, 64]

        # pd_op.reshape: (22x16x12x64xf32, 0x-1x-1x-1xi64) <- (-1x-1x-1xf32, 4xi64)
        reshape_0, reshape_1 = paddle.reshape(data_0, full_int_array_0), None

        # pd_op.full_int_array: (3xi64) <- ()
        full_int_array_1 = [16, 16, 32]

        # pd_op.full: (1xi32) <- ()
        full_0 = paddle._C_ops.full([1], 3, paddle.int32, paddle.core.CPUPlace())

        # pd_op.split: ([22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32]) <- (22x16x12x64xf32, 3xi64, 1xi32)
        split_0 = paddle.split(reshape_0, full_int_array_1, full_0)

        # builtin.split: (22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32) <- ([22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32])
        split_1, split_2, split_3, = split_0

        # pd_op.transpose: (22x12x16x16xf32) <- (22x16x12x16xf32)
        transpose_0 = paddle.transpose(split_1, perm=[0, 2, 1, 3])

        # pd_op.transpose: (22x12x16x16xf32) <- (22x16x12x16xf32)
        transpose_1 = paddle.transpose(split_2, perm=[0, 2, 1, 3])

        # pd_op.transpose: (22x12x16x32xf32) <- (22x16x12x32xf32)
        transpose_2 = paddle.transpose(split_3, perm=[0, 2, 1, 3])

        # pd_op.transpose: (22x12x16x16xf32) <- (22x12x16x16xf32)
        transpose_3 = paddle.transpose(transpose_1, perm=[0, 1, 3, 2])

        # pd_op.transpose: (16x12xf32) <- (12x16xf32)
        transpose_4 = paddle.transpose(parameter_0, perm=[1, 0])

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_2 = [0]

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_3 = [1]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_0 = paddle._C_ops.slice(data_1, [0], full_int_array_2, full_int_array_3, [1], [0])

        # pd_op.full: (1xi32) <- ()
        full_1 = paddle._C_ops.full([1], 0, paddle.int32, paddle.core.CPUPlace())

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_0 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_1 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_2 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_3 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_4 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_5 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_6 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_7 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_8 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_9 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_10 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_11 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_12 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_13 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_14 = full_1

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_15 = full_1

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_0 = paddle._C_ops.gather(transpose_4, slice_0, full_1)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_4 = [2]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_1 = paddle._C_ops.slice(data_1, [0], full_int_array_3, full_int_array_4, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_1 = paddle._C_ops.gather(transpose_4, slice_1, assign_15)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_5 = [3]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_2 = paddle._C_ops.slice(data_1, [0], full_int_array_4, full_int_array_5, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_2 = paddle._C_ops.gather(transpose_4, slice_2, assign_14)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_6 = [4]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_3 = paddle._C_ops.slice(data_1, [0], full_int_array_5, full_int_array_6, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_3 = paddle._C_ops.gather(transpose_4, slice_3, assign_13)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_7 = [5]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_4 = paddle._C_ops.slice(data_1, [0], full_int_array_6, full_int_array_7, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_4 = paddle._C_ops.gather(transpose_4, slice_4, assign_12)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_8 = [6]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_5 = paddle._C_ops.slice(data_1, [0], full_int_array_7, full_int_array_8, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_5 = paddle._C_ops.gather(transpose_4, slice_5, assign_11)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_9 = [7]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_6 = paddle._C_ops.slice(data_1, [0], full_int_array_8, full_int_array_9, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_6 = paddle._C_ops.gather(transpose_4, slice_6, assign_10)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_10 = [8]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_7 = paddle._C_ops.slice(data_1, [0], full_int_array_9, full_int_array_10, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_7 = paddle._C_ops.gather(transpose_4, slice_7, assign_9)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_11 = [9]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_8 = paddle._C_ops.slice(data_1, [0], full_int_array_10, full_int_array_11, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_8 = paddle._C_ops.gather(transpose_4, slice_8, assign_8)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_12 = [10]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_9 = paddle._C_ops.slice(data_1, [0], full_int_array_11, full_int_array_12, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_9 = paddle._C_ops.gather(transpose_4, slice_9, assign_7)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_13 = [11]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_10 = paddle._C_ops.slice(data_1, [0], full_int_array_12, full_int_array_13, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_10 = paddle._C_ops.gather(transpose_4, slice_10, assign_6)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_14 = [12]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_11 = paddle._C_ops.slice(data_1, [0], full_int_array_13, full_int_array_14, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_11 = paddle._C_ops.gather(transpose_4, slice_11, assign_5)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_15 = [13]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_12 = paddle._C_ops.slice(data_1, [0], full_int_array_14, full_int_array_15, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_12 = paddle._C_ops.gather(transpose_4, slice_12, assign_4)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_16 = [14]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_13 = paddle._C_ops.slice(data_1, [0], full_int_array_15, full_int_array_16, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_13 = paddle._C_ops.gather(transpose_4, slice_13, assign_3)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_17 = [15]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_14 = paddle._C_ops.slice(data_1, [0], full_int_array_16, full_int_array_17, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_14 = paddle._C_ops.gather(transpose_4, slice_14, assign_2)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_18 = [16]

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_15 = paddle._C_ops.slice(data_1, [0], full_int_array_17, full_int_array_18, [1], [0])

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_15 = paddle._C_ops.gather(transpose_4, slice_15, assign_1)

        # builtin.combine: ([-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32]) <- (-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32)
        combine_0 = [gather_0, gather_1, gather_2, gather_3, gather_4, gather_5, gather_6, gather_7, gather_8, gather_9, gather_10, gather_11, gather_12, gather_13, gather_14, gather_15]

        # pd_op.concat: (-1x12xf32) <- ([-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32], 1xi32)
        concat_0 = paddle._C_ops.concat(combine_0, assign_0)

        # pd_op.transpose: (12x-1xf32) <- (-1x12xf32)
        transpose_5 = paddle.transpose(concat_0, perm=[1, 0])

        # pd_op.full_int_array: (3xi64) <- ()
        full_int_array_19 = [0, 16, 16]

        # pd_op.reshape: (12x16x16xf32, 0x12x-1xi64) <- (12x-1xf32, 3xi64)
        reshape_2, reshape_3 = paddle.reshape(transpose_5, full_int_array_19), None
        return reshape_1, full_0, transpose_4, slice_0, full_1, gather_0, slice_1, assign_15, gather_1, slice_2, assign_14, gather_2, slice_3, assign_13, gather_3, slice_4, assign_12, gather_4, slice_5, assign_11, gather_5, slice_6, assign_10, gather_6, slice_7, assign_9, gather_7, slice_8, assign_8, gather_8, slice_9, assign_7, gather_9, slice_10, assign_6, gather_10, slice_11, assign_5, gather_11, slice_12, assign_4, gather_12, slice_13, assign_3, gather_13, slice_14, assign_2, gather_14, slice_15, assign_1, gather_15, assign_0, reshape_3, transpose_0, transpose_3, reshape_2, transpose_2



def GetEnvVarEnableJit():
    enable_jit = os.getenv('PADDLE_DEBUG_ENABLE_JIT')
    return enable_jit not in {
        "0",
        "False",
        "false",
        "OFF",
    }

def GetEnvVarEnableCinn():
    enable_cinn = os.getenv('PADDLE_DEBUG_ENABLE_CINN')
    return enable_cinn not in {
        "0",
        "False",
        "false",
        "OFF",
    }


def GetTolerance(dtype):
    if dtype == np.float16:
        return GetFloat16Tolerance()
    if dtype == np.float32:
        return GetFloat32Tolerance()
    return 1e-6

def GetFloat16Tolerance():
    try:
        return float(os.getenv('PADDLE_DEBUG_FLOAT16_TOL'))
    except:
        return 1e-3

def GetFloat32Tolerance():
    try:
        return float(os.getenv('PADDLE_DEBUG_FLOAT32_TOL'))
    except:
        return 1e-6

def IsInteger(dtype):
    return np.dtype(dtype).char in np.typecodes['AllInteger']


class CinnTestBase:
    def setUp(self):
        paddle.seed(2024)
        self.prepare_data()

    def test_train(self):
        dy_outs = self.train(use_cinn=False)
        cinn_outs = self.train(use_cinn=GetEnvVarEnableCinn())

        for cinn_out, dy_out in zip(cinn_outs, dy_outs):
          if type(cinn_out) is list and type(dy_out) is list:
            for x, y in zip(cinn_out, dy_out):
              self.assert_all_close(x, y)
          else:
            self.assert_all_close(cinn_out, dy_out)

    def assert_all_close(self, x, y):
        if (hasattr(x, "numpy") and hasattr(y, "numpy")):
            x_numpy = x.numpy()
            y_numpy = y.numpy()
            assert x_numpy.dtype == y_numpy.dtype
            if IsInteger(x_numpy.dtype):
                np.testing.assert_equal(x_numpy, y_numpy)
            else:
                tol = GetTolerance(x_numpy.dtype)
                np.testing.assert_allclose(x_numpy, y_numpy, atol=tol, rtol=tol)
        else:
            assert x == y

class Block_builtin_module_0_0_0(paddle.nn.Layer, BlockEntries):
    def __init__(self):
        super().__init__()

    def forward(self, parameter_0, data_0, data_1):
        args = [parameter_0, data_0, data_1]
        for op_idx, op_func in enumerate(self.get_op_funcs()):
            if EarlyReturn(0, op_idx):
                return args
            args = op_func(*args)
        return args

    def get_op_funcs(self):
        return [
            self.op_full_int_array_0,
            self.op_reshape_0,
            self.op_full_int_array_1,
            self.op_full_0,
            self.op_split_0,
            self.op_split_1,
            self.op_transpose_0,
            self.op_transpose_1,
            self.op_transpose_2,
            self.op_transpose_3,
            self.op_transpose_4,
            self.op_full_int_array_2,
            self.op_full_int_array_3,
            self.op_slice_0,
            self.op_full_1,
            self.op_assign_0,
            self.op_assign_1,
            self.op_assign_2,
            self.op_assign_3,
            self.op_assign_4,
            self.op_assign_5,
            self.op_assign_6,
            self.op_assign_7,
            self.op_assign_8,
            self.op_assign_9,
            self.op_assign_10,
            self.op_assign_11,
            self.op_assign_12,
            self.op_assign_13,
            self.op_assign_14,
            self.op_assign_15,
            self.op_gather_0,
            self.op_full_int_array_4,
            self.op_slice_1,
            self.op_gather_1,
            self.op_full_int_array_5,
            self.op_slice_2,
            self.op_gather_2,
            self.op_full_int_array_6,
            self.op_slice_3,
            self.op_gather_3,
            self.op_full_int_array_7,
            self.op_slice_4,
            self.op_gather_4,
            self.op_full_int_array_8,
            self.op_slice_5,
            self.op_gather_5,
            self.op_full_int_array_9,
            self.op_slice_6,
            self.op_gather_6,
            self.op_full_int_array_10,
            self.op_slice_7,
            self.op_gather_7,
            self.op_full_int_array_11,
            self.op_slice_8,
            self.op_gather_8,
            self.op_full_int_array_12,
            self.op_slice_9,
            self.op_gather_9,
            self.op_full_int_array_13,
            self.op_slice_10,
            self.op_gather_10,
            self.op_full_int_array_14,
            self.op_slice_11,
            self.op_gather_11,
            self.op_full_int_array_15,
            self.op_slice_12,
            self.op_gather_12,
            self.op_full_int_array_16,
            self.op_slice_13,
            self.op_gather_13,
            self.op_full_int_array_17,
            self.op_slice_14,
            self.op_gather_14,
            self.op_full_int_array_18,
            self.op_slice_15,
            self.op_gather_15,
            self.op_combine_0,
            self.op_concat_0,
            self.op_transpose_5,
            self.op_full_int_array_19,
            self.op_reshape_1,
        ]

    def op_full_int_array_0(self, parameter_0, data_0, data_1):
    
        # EarlyReturn(0, 0)

        # pd_op.full_int_array: (4xi64) <- ()
        full_int_array_0 = [22, 16, 12, 64]

        return [parameter_0, data_0, data_1, full_int_array_0]

    def op_reshape_0(self, parameter_0, data_0, data_1, full_int_array_0):
    
        # EarlyReturn(0, 1)

        # pd_op.reshape: (22x16x12x64xf32, 0x-1x-1x-1xi64) <- (-1x-1x-1xf32, 4xi64)
        reshape_0, reshape_1 = paddle.reshape(data_0, full_int_array_0), None

        return [parameter_0, data_1, reshape_0, reshape_1]

    def op_full_int_array_1(self, parameter_0, data_1, reshape_0, reshape_1):
    
        # EarlyReturn(0, 2)

        # pd_op.full_int_array: (3xi64) <- ()
        full_int_array_1 = [16, 16, 32]

        return [parameter_0, data_1, reshape_0, reshape_1, full_int_array_1]

    def op_full_0(self, parameter_0, data_1, reshape_0, reshape_1, full_int_array_1):
    
        # EarlyReturn(0, 3)

        # pd_op.full: (1xi32) <- ()
        full_0 = paddle._C_ops.full([1], 3, paddle.int32, paddle.core.CPUPlace())

        return [parameter_0, data_1, reshape_0, reshape_1, full_int_array_1, full_0]

    def op_split_0(self, parameter_0, data_1, reshape_0, reshape_1, full_int_array_1, full_0):
    
        # EarlyReturn(0, 4)

        # pd_op.split: ([22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32]) <- (22x16x12x64xf32, 3xi64, 1xi32)
        split_0 = paddle.split(reshape_0, full_int_array_1, full_0)

        return [parameter_0, data_1, reshape_1, full_0, split_0]

    def op_split_1(self, parameter_0, data_1, reshape_1, full_0, split_0):
    
        # EarlyReturn(0, 5)

        # builtin.split: (22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32) <- ([22x16x12x16xf32, 22x16x12x16xf32, 22x16x12x32xf32])
        split_1, split_2, split_3, = split_0

        return [parameter_0, data_1, reshape_1, full_0, split_1, split_2, split_3]

    def op_transpose_0(self, parameter_0, data_1, reshape_1, full_0, split_1, split_2, split_3):
    
        # EarlyReturn(0, 6)

        # pd_op.transpose: (22x12x16x16xf32) <- (22x16x12x16xf32)
        transpose_0 = paddle.transpose(split_1, perm=[0, 2, 1, 3])

        return [parameter_0, data_1, reshape_1, full_0, split_2, split_3, transpose_0]

    def op_transpose_1(self, parameter_0, data_1, reshape_1, full_0, split_2, split_3, transpose_0):
    
        # EarlyReturn(0, 7)

        # pd_op.transpose: (22x12x16x16xf32) <- (22x16x12x16xf32)
        transpose_1 = paddle.transpose(split_2, perm=[0, 2, 1, 3])

        return [parameter_0, data_1, reshape_1, full_0, split_3, transpose_0, transpose_1]

    def op_transpose_2(self, parameter_0, data_1, reshape_1, full_0, split_3, transpose_0, transpose_1):
    
        # EarlyReturn(0, 8)

        # pd_op.transpose: (22x12x16x32xf32) <- (22x16x12x32xf32)
        transpose_2 = paddle.transpose(split_3, perm=[0, 2, 1, 3])

        return [parameter_0, data_1, reshape_1, full_0, transpose_0, transpose_1, transpose_2]

    def op_transpose_3(self, parameter_0, data_1, reshape_1, full_0, transpose_0, transpose_1, transpose_2):
    
        # EarlyReturn(0, 9)

        # pd_op.transpose: (22x12x16x16xf32) <- (22x12x16x16xf32)
        transpose_3 = paddle.transpose(transpose_1, perm=[0, 1, 3, 2])

        return [parameter_0, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3]

    def op_transpose_4(self, parameter_0, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3):
    
        # EarlyReturn(0, 10)

        # pd_op.transpose: (16x12xf32) <- (12x16xf32)
        transpose_4 = paddle.transpose(parameter_0, perm=[1, 0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4]

    def op_full_int_array_2(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4):
    
        # EarlyReturn(0, 11)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_2 = [0]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_2]

    def op_full_int_array_3(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_2):
    
        # EarlyReturn(0, 12)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_3 = [1]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_2, full_int_array_3]

    def op_slice_0(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_2, full_int_array_3):
    
        # EarlyReturn(0, 13)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_0 = paddle._C_ops.slice(data_1, [0], full_int_array_2, full_int_array_3, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0]

    def op_full_1(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0):
    
        # EarlyReturn(0, 14)

        # pd_op.full: (1xi32) <- ()
        full_1 = paddle._C_ops.full([1], 0, paddle.int32, paddle.core.CPUPlace())

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1]

    def op_assign_0(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1):
    
        # EarlyReturn(0, 15)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_0 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0]

    def op_assign_1(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0):
    
        # EarlyReturn(0, 16)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_1 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1]

    def op_assign_2(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1):
    
        # EarlyReturn(0, 17)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_2 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2]

    def op_assign_3(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2):
    
        # EarlyReturn(0, 18)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_3 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3]

    def op_assign_4(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3):
    
        # EarlyReturn(0, 19)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_4 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4]

    def op_assign_5(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4):
    
        # EarlyReturn(0, 20)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_5 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5]

    def op_assign_6(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5):
    
        # EarlyReturn(0, 21)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_6 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6]

    def op_assign_7(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6):
    
        # EarlyReturn(0, 22)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_7 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7]

    def op_assign_8(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7):
    
        # EarlyReturn(0, 23)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_8 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8]

    def op_assign_9(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8):
    
        # EarlyReturn(0, 24)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_9 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9]

    def op_assign_10(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9):
    
        # EarlyReturn(0, 25)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_10 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10]

    def op_assign_11(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10):
    
        # EarlyReturn(0, 26)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_11 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11]

    def op_assign_12(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11):
    
        # EarlyReturn(0, 27)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_12 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12]

    def op_assign_13(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12):
    
        # EarlyReturn(0, 28)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_13 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13]

    def op_assign_14(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13):
    
        # EarlyReturn(0, 29)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_14 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14]

    def op_assign_15(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14):
    
        # EarlyReturn(0, 30)

        # pd_op.assign: (1xi32) <- (1xi32)
        assign_15 = full_1

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15]

    def op_gather_0(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15):
    
        # EarlyReturn(0, 31)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_0 = paddle._C_ops.gather(transpose_4, slice_0, full_1)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0]

    def op_full_int_array_4(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0):
    
        # EarlyReturn(0, 32)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_4 = [2]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4]

    def op_slice_1(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, full_int_array_3, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4):
    
        # EarlyReturn(0, 33)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_1 = paddle._C_ops.slice(data_1, [0], full_int_array_3, full_int_array_4, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1]

    def op_gather_1(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1):
    
        # EarlyReturn(0, 34)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_1 = paddle._C_ops.gather(transpose_4, slice_1, assign_15)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1, gather_1]

    def op_full_int_array_5(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1, gather_1):
    
        # EarlyReturn(0, 35)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_5 = [3]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1, gather_1, full_int_array_5]

    def op_slice_2(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, full_int_array_4, slice_1, gather_1, full_int_array_5):
    
        # EarlyReturn(0, 36)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_2 = paddle._C_ops.slice(data_1, [0], full_int_array_4, full_int_array_5, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2]

    def op_gather_2(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2):
    
        # EarlyReturn(0, 37)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_2 = paddle._C_ops.gather(transpose_4, slice_2, assign_14)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2, gather_2]

    def op_full_int_array_6(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2, gather_2):
    
        # EarlyReturn(0, 38)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_6 = [4]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2, gather_2, full_int_array_6]

    def op_slice_3(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, full_int_array_5, slice_2, gather_2, full_int_array_6):
    
        # EarlyReturn(0, 39)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_3 = paddle._C_ops.slice(data_1, [0], full_int_array_5, full_int_array_6, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3]

    def op_gather_3(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3):
    
        # EarlyReturn(0, 40)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_3 = paddle._C_ops.gather(transpose_4, slice_3, assign_13)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3, gather_3]

    def op_full_int_array_7(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3, gather_3):
    
        # EarlyReturn(0, 41)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_7 = [5]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3, gather_3, full_int_array_7]

    def op_slice_4(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, full_int_array_6, slice_3, gather_3, full_int_array_7):
    
        # EarlyReturn(0, 42)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_4 = paddle._C_ops.slice(data_1, [0], full_int_array_6, full_int_array_7, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4]

    def op_gather_4(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4):
    
        # EarlyReturn(0, 43)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_4 = paddle._C_ops.gather(transpose_4, slice_4, assign_12)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4, gather_4]

    def op_full_int_array_8(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4, gather_4):
    
        # EarlyReturn(0, 44)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_8 = [6]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4, gather_4, full_int_array_8]

    def op_slice_5(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, full_int_array_7, slice_4, gather_4, full_int_array_8):
    
        # EarlyReturn(0, 45)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_5 = paddle._C_ops.slice(data_1, [0], full_int_array_7, full_int_array_8, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5]

    def op_gather_5(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5):
    
        # EarlyReturn(0, 46)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_5 = paddle._C_ops.gather(transpose_4, slice_5, assign_11)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5, gather_5]

    def op_full_int_array_9(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5, gather_5):
    
        # EarlyReturn(0, 47)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_9 = [7]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5, gather_5, full_int_array_9]

    def op_slice_6(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, full_int_array_8, slice_5, gather_5, full_int_array_9):
    
        # EarlyReturn(0, 48)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_6 = paddle._C_ops.slice(data_1, [0], full_int_array_8, full_int_array_9, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6]

    def op_gather_6(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6):
    
        # EarlyReturn(0, 49)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_6 = paddle._C_ops.gather(transpose_4, slice_6, assign_10)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6, gather_6]

    def op_full_int_array_10(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6, gather_6):
    
        # EarlyReturn(0, 50)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_10 = [8]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6, gather_6, full_int_array_10]

    def op_slice_7(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, full_int_array_9, slice_6, gather_6, full_int_array_10):
    
        # EarlyReturn(0, 51)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_7 = paddle._C_ops.slice(data_1, [0], full_int_array_9, full_int_array_10, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7]

    def op_gather_7(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7):
    
        # EarlyReturn(0, 52)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_7 = paddle._C_ops.gather(transpose_4, slice_7, assign_9)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7, gather_7]

    def op_full_int_array_11(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7, gather_7):
    
        # EarlyReturn(0, 53)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_11 = [9]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7, gather_7, full_int_array_11]

    def op_slice_8(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, full_int_array_10, slice_7, gather_7, full_int_array_11):
    
        # EarlyReturn(0, 54)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_8 = paddle._C_ops.slice(data_1, [0], full_int_array_10, full_int_array_11, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8]

    def op_gather_8(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8):
    
        # EarlyReturn(0, 55)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_8 = paddle._C_ops.gather(transpose_4, slice_8, assign_8)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8, gather_8]

    def op_full_int_array_12(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8, gather_8):
    
        # EarlyReturn(0, 56)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_12 = [10]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8, gather_8, full_int_array_12]

    def op_slice_9(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, full_int_array_11, slice_8, gather_8, full_int_array_12):
    
        # EarlyReturn(0, 57)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_9 = paddle._C_ops.slice(data_1, [0], full_int_array_11, full_int_array_12, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9]

    def op_gather_9(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9):
    
        # EarlyReturn(0, 58)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_9 = paddle._C_ops.gather(transpose_4, slice_9, assign_7)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9, gather_9]

    def op_full_int_array_13(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9, gather_9):
    
        # EarlyReturn(0, 59)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_13 = [11]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9, gather_9, full_int_array_13]

    def op_slice_10(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, full_int_array_12, slice_9, gather_9, full_int_array_13):
    
        # EarlyReturn(0, 60)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_10 = paddle._C_ops.slice(data_1, [0], full_int_array_12, full_int_array_13, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10]

    def op_gather_10(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10):
    
        # EarlyReturn(0, 61)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_10 = paddle._C_ops.gather(transpose_4, slice_10, assign_6)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10, gather_10]

    def op_full_int_array_14(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10, gather_10):
    
        # EarlyReturn(0, 62)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_14 = [12]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10, gather_10, full_int_array_14]

    def op_slice_11(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, full_int_array_13, slice_10, gather_10, full_int_array_14):
    
        # EarlyReturn(0, 63)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_11 = paddle._C_ops.slice(data_1, [0], full_int_array_13, full_int_array_14, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11]

    def op_gather_11(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11):
    
        # EarlyReturn(0, 64)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_11 = paddle._C_ops.gather(transpose_4, slice_11, assign_5)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11, gather_11]

    def op_full_int_array_15(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11, gather_11):
    
        # EarlyReturn(0, 65)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_15 = [13]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11, gather_11, full_int_array_15]

    def op_slice_12(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, full_int_array_14, slice_11, gather_11, full_int_array_15):
    
        # EarlyReturn(0, 66)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_12 = paddle._C_ops.slice(data_1, [0], full_int_array_14, full_int_array_15, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12]

    def op_gather_12(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12):
    
        # EarlyReturn(0, 67)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_12 = paddle._C_ops.gather(transpose_4, slice_12, assign_4)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12, gather_12]

    def op_full_int_array_16(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12, gather_12):
    
        # EarlyReturn(0, 68)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_16 = [14]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12, gather_12, full_int_array_16]

    def op_slice_13(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, full_int_array_15, slice_12, gather_12, full_int_array_16):
    
        # EarlyReturn(0, 69)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_13 = paddle._C_ops.slice(data_1, [0], full_int_array_15, full_int_array_16, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13]

    def op_gather_13(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13):
    
        # EarlyReturn(0, 70)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_13 = paddle._C_ops.gather(transpose_4, slice_13, assign_3)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13, gather_13]

    def op_full_int_array_17(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13, gather_13):
    
        # EarlyReturn(0, 71)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_17 = [15]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13, gather_13, full_int_array_17]

    def op_slice_14(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, full_int_array_16, slice_13, gather_13, full_int_array_17):
    
        # EarlyReturn(0, 72)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_14 = paddle._C_ops.slice(data_1, [0], full_int_array_16, full_int_array_17, [1], [0])

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14]

    def op_gather_14(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14):
    
        # EarlyReturn(0, 73)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_14 = paddle._C_ops.gather(transpose_4, slice_14, assign_2)

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14, gather_14]

    def op_full_int_array_18(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14, gather_14):
    
        # EarlyReturn(0, 74)

        # pd_op.full_int_array: (1xi64) <- ()
        full_int_array_18 = [16]

        return [data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14, gather_14, full_int_array_18]

    def op_slice_15(self, data_1, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, full_int_array_17, slice_14, gather_14, full_int_array_18):
    
        # EarlyReturn(0, 75)

        # pd_op.slice: (-1xi64) <- (-1x-1xi64, 1xi64, 1xi64)
        slice_15 = paddle._C_ops.slice(data_1, [0], full_int_array_17, full_int_array_18, [1], [0])

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15]

    def op_gather_15(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15):
    
        # EarlyReturn(0, 76)

        # pd_op.gather: (-1x12xf32) <- (16x12xf32, -1xi64, 1xi32)
        gather_15 = paddle._C_ops.gather(transpose_4, slice_15, assign_1)

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15]

    def op_combine_0(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15):
    
        # EarlyReturn(0, 77)

        # builtin.combine: ([-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32]) <- (-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32)
        combine_0 = [gather_0, gather_1, gather_2, gather_3, gather_4, gather_5, gather_6, gather_7, gather_8, gather_9, gather_10, gather_11, gather_12, gather_13, gather_14, gather_15]

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, combine_0]

    def op_concat_0(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, combine_0):
    
        # EarlyReturn(0, 78)

        # pd_op.concat: (-1x12xf32) <- ([-1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32, -1x12xf32], 1xi32)
        concat_0 = paddle._C_ops.concat(combine_0, assign_0)

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, concat_0]

    def op_transpose_5(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, concat_0):
    
        # EarlyReturn(0, 79)

        # pd_op.transpose: (12x-1xf32) <- (-1x12xf32)
        transpose_5 = paddle.transpose(concat_0, perm=[1, 0])

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, transpose_5]

    def op_full_int_array_19(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, transpose_5):
    
        # EarlyReturn(0, 80)

        # pd_op.full_int_array: (3xi64) <- ()
        full_int_array_19 = [0, 16, 16]

        return [reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, transpose_5, full_int_array_19]

    def op_reshape_1(self, reshape_1, full_0, transpose_0, transpose_2, transpose_3, transpose_4, slice_0, full_1, assign_0, assign_1, assign_2, assign_3, assign_4, assign_5, assign_6, assign_7, assign_8, assign_9, assign_10, assign_11, assign_12, assign_13, assign_14, assign_15, gather_0, slice_1, gather_1, slice_2, gather_2, slice_3, gather_3, slice_4, gather_4, slice_5, gather_5, slice_6, gather_6, slice_7, gather_7, slice_8, gather_8, slice_9, gather_9, slice_10, gather_10, slice_11, gather_11, slice_12, gather_12, slice_13, gather_13, slice_14, gather_14, slice_15, gather_15, transpose_5, full_int_array_19):
    
        # EarlyReturn(0, 81)

        # pd_op.reshape: (12x16x16xf32, 0x12x-1xi64) <- (12x-1xf32, 3xi64)
        reshape_2, reshape_3 = paddle.reshape(transpose_5, full_int_array_19), None

        return [reshape_1, full_0, transpose_4, slice_0, full_1, gather_0, slice_1, assign_15, gather_1, slice_2, assign_14, gather_2, slice_3, assign_13, gather_3, slice_4, assign_12, gather_4, slice_5, assign_11, gather_5, slice_6, assign_10, gather_6, slice_7, assign_9, gather_7, slice_8, assign_8, gather_8, slice_9, assign_7, gather_9, slice_10, assign_6, gather_10, slice_11, assign_5, gather_11, slice_12, assign_4, gather_12, slice_13, assign_3, gather_13, slice_14, assign_2, gather_14, slice_15, assign_1, gather_15, assign_0, reshape_3, transpose_0, transpose_3, reshape_2, transpose_2]

is_module_block_and_last_stage_passed = (
    True and not last_stage_failed
)
@unittest.skipIf(not is_module_block_and_last_stage_passed, "last stage failed")
class Test_builtin_module_0_0_0(CinnTestBase, unittest.TestCase):
    def prepare_data(self):
        self.inputs = [
            # parameter_0
            paddle.uniform([12, 16], dtype='float32', min=0, max=0.5),
            # data_0
            paddle.uniform([22, 16, 768], dtype='float32', min=0, max=0.5),
            # data_1
            paddle.randint(low=0, high=3, shape=[16, 16], dtype='int64'),
        ]
        for input in self.inputs:
            input.stop_gradient = True

    def apply_to_static(self, net, use_cinn):
        build_strategy = paddle.static.BuildStrategy()
        input_spec = [
            # parameter_0
            paddle.static.InputSpec(shape=[12, 16], dtype='float32'),
            # data_0
            paddle.static.InputSpec(shape=[None, None, None], dtype='float32'),
            # data_1
            paddle.static.InputSpec(shape=[None, None], dtype='int64'),
        ]
        build_strategy.build_cinn_pass = use_cinn
        return paddle.jit.to_static(
            net,
            input_spec=input_spec,
            build_strategy=build_strategy,
            full_graph=True,
        )

    def train(self, use_cinn):
        net = Block_builtin_module_0_0_0()
        if GetEnvVarEnableJit():
            net = self.apply_to_static(net, use_cinn)
        paddle.seed(2024)
        out = net(*self.inputs)
        return out

if __name__ == '__main__':
    unittest.main()