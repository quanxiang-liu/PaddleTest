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
    return [30][block_idx] - 1 # number-of-ops-in-block

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

    def builtin_module_0_0_0(self, parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, parameter_0, data_3, data_2, data_1, data_0):

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x2048x-1x-1xf32, 256x2048x1x1xf32)
        conv2d_0 = paddle._C_ops.conv2d(data_0, parameter_0, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x1024x-1x-1xf32, 256x1024x1x1xf32)
        conv2d_1 = paddle._C_ops.conv2d(data_1, parameter_1, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x512x-1x-1xf32, 256x512x1x1xf32)
        conv2d_2 = paddle._C_ops.conv2d(data_2, parameter_2, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, 256x256x1x1xf32)
        conv2d_3 = paddle._C_ops.conv2d(data_3, parameter_3, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_0 = paddle._C_ops.nearest_interp(conv2d_0, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_0 = conv2d_1 + nearest_interp_0

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_1 = paddle._C_ops.nearest_interp(add_0, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_1 = conv2d_2 + nearest_interp_1

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_2 = paddle._C_ops.nearest_interp(add_1, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_2 = conv2d_3 + nearest_interp_2

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_4 = paddle._C_ops.conv2d(conv2d_0, parameter_4, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_5 = paddle._C_ops.conv2d(add_0, parameter_5, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_6 = paddle._C_ops.conv2d(add_1, parameter_6, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_7 = paddle._C_ops.conv2d(add_2, parameter_7, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_8 = paddle._C_ops.conv2d(conv2d_7, parameter_8, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_3 = conv2d_6 + conv2d_8

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_9 = paddle._C_ops.conv2d(add_3, parameter_9, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_4 = conv2d_5 + conv2d_9

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_10 = paddle._C_ops.conv2d(add_4, parameter_10, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_5 = conv2d_4 + conv2d_10

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_11 = paddle._C_ops.conv2d(conv2d_7, parameter_11, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_12 = paddle._C_ops.conv2d(add_3, parameter_12, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_13 = paddle._C_ops.conv2d(add_4, parameter_13, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_14 = paddle._C_ops.conv2d(add_5, parameter_14, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_3 = paddle._C_ops.nearest_interp(conv2d_14, None, None, None, 'NCHW', -1, -1, -1, [8, 8], 'nearest', False, 1)

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_4 = paddle._C_ops.nearest_interp(conv2d_13, None, None, None, 'NCHW', -1, -1, -1, [4, 4], 'nearest', False, 1)

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_5 = paddle._C_ops.nearest_interp(conv2d_12, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        # pd_op.full: (1xi32) <- ()
        full_0 = paddle._C_ops.full([1], 1, paddle.int32, paddle.core.CPUPlace())

        # builtin.combine: ([-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32]) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32)
        combine_0 = [nearest_interp_3, nearest_interp_4, nearest_interp_5, conv2d_11]

        # pd_op.concat: (-1x256x-1x-1xf32) <- ([-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32], 1xi32)
        concat_0 = paddle._C_ops.concat(combine_0, full_0)
        return conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0, concat_0



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

    def forward(self, parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, parameter_0, data_3, data_2, data_1, data_0):
        args = [parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, parameter_0, data_3, data_2, data_1, data_0]
        for op_idx, op_func in enumerate(self.get_op_funcs()):
            if EarlyReturn(0, op_idx):
                return args
            args = op_func(*args)
        return args

    def get_op_funcs(self):
        return [
            self.op_conv2d_0,
            self.op_conv2d_1,
            self.op_conv2d_2,
            self.op_conv2d_3,
            self.op_nearest_interp_0,
            self.op_add_0,
            self.op_nearest_interp_1,
            self.op_add_1,
            self.op_nearest_interp_2,
            self.op_add_2,
            self.op_conv2d_4,
            self.op_conv2d_5,
            self.op_conv2d_6,
            self.op_conv2d_7,
            self.op_conv2d_8,
            self.op_add_3,
            self.op_conv2d_9,
            self.op_add_4,
            self.op_conv2d_10,
            self.op_add_5,
            self.op_conv2d_11,
            self.op_conv2d_12,
            self.op_conv2d_13,
            self.op_conv2d_14,
            self.op_nearest_interp_3,
            self.op_nearest_interp_4,
            self.op_nearest_interp_5,
            self.op_full_0,
            self.op_combine_0,
            self.op_concat_0,
        ]

    def op_conv2d_0(self, parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, parameter_0, data_3, data_2, data_1, data_0):
    
        # EarlyReturn(0, 0)

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x2048x-1x-1xf32, 256x2048x1x1xf32)
        conv2d_0 = paddle._C_ops.conv2d(data_0, parameter_0, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, data_3, data_2, data_1, conv2d_0]

    def op_conv2d_1(self, parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_1, parameter_9, data_3, data_2, data_1, conv2d_0):
    
        # EarlyReturn(0, 1)

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x1024x-1x-1xf32, 256x1024x1x1xf32)
        conv2d_1 = paddle._C_ops.conv2d(data_1, parameter_1, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, data_3, data_2, conv2d_0, conv2d_1]

    def op_conv2d_2(self, parameter_11, parameter_5, parameter_2, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, data_3, data_2, conv2d_0, conv2d_1):
    
        # EarlyReturn(0, 2)

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x512x-1x-1xf32, 256x512x1x1xf32)
        conv2d_2 = paddle._C_ops.conv2d(data_2, parameter_2, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, data_3, conv2d_0, conv2d_1, conv2d_2]

    def op_conv2d_3(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_3, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, data_3, conv2d_0, conv2d_1, conv2d_2):
    
        # EarlyReturn(0, 3)

        # pd_op.conv2d: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, 256x256x1x1xf32)
        conv2d_3 = paddle._C_ops.conv2d(data_3, parameter_3, [1, 1], [0, 0], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3]

    def op_nearest_interp_0(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3):
    
        # EarlyReturn(0, 4)

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_0 = paddle._C_ops.nearest_interp(conv2d_0, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0]

    def op_add_0(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0):
    
        # EarlyReturn(0, 5)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_0 = conv2d_1 + nearest_interp_0

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0]

    def op_nearest_interp_1(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0):
    
        # EarlyReturn(0, 6)

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_1 = paddle._C_ops.nearest_interp(add_0, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1]

    def op_add_1(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1):
    
        # EarlyReturn(0, 7)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_1 = conv2d_2 + nearest_interp_1

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1]

    def op_nearest_interp_2(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1):
    
        # EarlyReturn(0, 8)

        # pd_op.nearest_interp: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, None, None, None)
        nearest_interp_2 = paddle._C_ops.nearest_interp(add_1, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2]

    def op_add_2(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2):
    
        # EarlyReturn(0, 9)

        # pd_op.add: (-1x256x-1x-1xf32) <- (-1x256x-1x-1xf32, -1x256x-1x-1xf32)
        add_2 = conv2d_3 + nearest_interp_2

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2]

    def op_conv2d_4(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_4, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2):
    
        # EarlyReturn(0, 10)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_4 = paddle._C_ops.conv2d(conv2d_0, parameter_4, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4]

    def op_conv2d_5(self, parameter_11, parameter_5, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4):
    
        # EarlyReturn(0, 11)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_5 = paddle._C_ops.conv2d(add_0, parameter_5, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5]

    def op_conv2d_6(self, parameter_11, parameter_6, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5):
    
        # EarlyReturn(0, 12)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_6 = paddle._C_ops.conv2d(add_1, parameter_6, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6]

    def op_conv2d_7(self, parameter_11, parameter_7, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6):
    
        # EarlyReturn(0, 13)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x256x-1x-1xf32, 64x256x9x9xf32)
        conv2d_7 = paddle._C_ops.conv2d(add_2, parameter_7, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7]

    def op_conv2d_8(self, parameter_11, parameter_10, parameter_8, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7):
    
        # EarlyReturn(0, 14)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_8 = paddle._C_ops.conv2d(conv2d_7, parameter_8, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8]

    def op_add_3(self, parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8):
    
        # EarlyReturn(0, 15)

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_3 = conv2d_6 + conv2d_8

        return [parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3]

    def op_conv2d_9(self, parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, parameter_9, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3):
    
        # EarlyReturn(0, 16)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_9 = paddle._C_ops.conv2d(add_3, parameter_9, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9]

    def op_add_4(self, parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9):
    
        # EarlyReturn(0, 17)

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_4 = conv2d_5 + conv2d_9

        return [parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4]

    def op_conv2d_10(self, parameter_11, parameter_10, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4):
    
        # EarlyReturn(0, 18)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x3x3xf32)
        conv2d_10 = paddle._C_ops.conv2d(add_4, parameter_10, [2, 2], [1, 1], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_11, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10]

    def op_add_5(self, parameter_11, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10):
    
        # EarlyReturn(0, 19)

        # pd_op.add: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32)
        add_5 = conv2d_4 + conv2d_10

        return [parameter_11, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5]

    def op_conv2d_11(self, parameter_11, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5):
    
        # EarlyReturn(0, 20)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_11 = paddle._C_ops.conv2d(conv2d_7, parameter_11, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11]

    def op_conv2d_12(self, parameter_14, parameter_13, parameter_12, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11):
    
        # EarlyReturn(0, 21)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_12 = paddle._C_ops.conv2d(add_3, parameter_12, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_14, parameter_13, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12]

    def op_conv2d_13(self, parameter_14, parameter_13, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12):
    
        # EarlyReturn(0, 22)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_13 = paddle._C_ops.conv2d(add_4, parameter_13, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [parameter_14, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13]

    def op_conv2d_14(self, parameter_14, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13):
    
        # EarlyReturn(0, 23)

        # pd_op.conv2d: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, 64x64x9x9xf32)
        conv2d_14 = paddle._C_ops.conv2d(add_5, parameter_14, [1, 1], [4, 4], 'EXPLICIT', [1, 1], 1, 'NCHW')

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14]

    def op_nearest_interp_3(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14):
    
        # EarlyReturn(0, 24)

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_3 = paddle._C_ops.nearest_interp(conv2d_14, None, None, None, 'NCHW', -1, -1, -1, [8, 8], 'nearest', False, 1)

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3]

    def op_nearest_interp_4(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3):
    
        # EarlyReturn(0, 25)

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_4 = paddle._C_ops.nearest_interp(conv2d_13, None, None, None, 'NCHW', -1, -1, -1, [4, 4], 'nearest', False, 1)

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4]

    def op_nearest_interp_5(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4):
    
        # EarlyReturn(0, 26)

        # pd_op.nearest_interp: (-1x64x-1x-1xf32) <- (-1x64x-1x-1xf32, None, None, None)
        nearest_interp_5 = paddle._C_ops.nearest_interp(conv2d_12, None, None, None, 'NCHW', -1, -1, -1, [2, 2], 'nearest', False, 1)

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5]

    def op_full_0(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5):
    
        # EarlyReturn(0, 27)

        # pd_op.full: (1xi32) <- ()
        full_0 = paddle._C_ops.full([1], 1, paddle.int32, paddle.core.CPUPlace())

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0]

    def op_combine_0(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0):
    
        # EarlyReturn(0, 28)

        # builtin.combine: ([-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32]) <- (-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32)
        combine_0 = [nearest_interp_3, nearest_interp_4, nearest_interp_5, conv2d_11]

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0, combine_0]

    def op_concat_0(self, conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0, combine_0):
    
        # EarlyReturn(0, 29)

        # pd_op.concat: (-1x256x-1x-1xf32) <- ([-1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32, -1x64x-1x-1xf32], 1xi32)
        concat_0 = paddle._C_ops.concat(combine_0, full_0)

        return [conv2d_0, conv2d_1, conv2d_2, conv2d_3, nearest_interp_0, add_0, nearest_interp_1, add_1, nearest_interp_2, add_2, conv2d_4, conv2d_5, conv2d_6, conv2d_7, conv2d_8, add_3, conv2d_9, add_4, conv2d_10, add_5, conv2d_11, conv2d_12, conv2d_13, conv2d_14, nearest_interp_3, nearest_interp_4, nearest_interp_5, full_0, concat_0]

is_module_block_and_last_stage_passed = (
    True and not last_stage_failed
)
@unittest.skipIf(not is_module_block_and_last_stage_passed, "last stage failed")
class Test_builtin_module_0_0_0(CinnTestBase, unittest.TestCase):
    def prepare_data(self):
        self.inputs = [
            # parameter_11
            paddle.uniform([64, 64, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_5
            paddle.uniform([64, 256, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_2
            paddle.uniform([256, 512, 1, 1], dtype='float32', min=0, max=0.5),
            # parameter_6
            paddle.uniform([64, 256, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_7
            paddle.uniform([64, 256, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_3
            paddle.uniform([256, 256, 1, 1], dtype='float32', min=0, max=0.5),
            # parameter_10
            paddle.uniform([64, 64, 3, 3], dtype='float32', min=0, max=0.5),
            # parameter_8
            paddle.uniform([64, 64, 3, 3], dtype='float32', min=0, max=0.5),
            # parameter_14
            paddle.uniform([64, 64, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_13
            paddle.uniform([64, 64, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_12
            paddle.uniform([64, 64, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_4
            paddle.uniform([64, 256, 9, 9], dtype='float32', min=0, max=0.5),
            # parameter_1
            paddle.uniform([256, 1024, 1, 1], dtype='float32', min=0, max=0.5),
            # parameter_9
            paddle.uniform([64, 64, 3, 3], dtype='float32', min=0, max=0.5),
            # parameter_0
            paddle.uniform([256, 2048, 1, 1], dtype='float32', min=0, max=0.5),
            # data_3
            paddle.uniform([1, 256, 184, 328], dtype='float32', min=0, max=0.5),
            # data_2
            paddle.uniform([1, 512, 92, 164], dtype='float32', min=0, max=0.5),
            # data_1
            paddle.uniform([1, 1024, 46, 82], dtype='float32', min=0, max=0.5),
            # data_0
            paddle.uniform([1, 2048, 23, 41], dtype='float32', min=0, max=0.5),
        ]
        for input in self.inputs:
            input.stop_gradient = True

    def apply_to_static(self, net, use_cinn):
        build_strategy = paddle.static.BuildStrategy()
        input_spec = [
            # parameter_11
            paddle.static.InputSpec(shape=[64, 64, 9, 9], dtype='float32'),
            # parameter_5
            paddle.static.InputSpec(shape=[64, 256, 9, 9], dtype='float32'),
            # parameter_2
            paddle.static.InputSpec(shape=[256, 512, 1, 1], dtype='float32'),
            # parameter_6
            paddle.static.InputSpec(shape=[64, 256, 9, 9], dtype='float32'),
            # parameter_7
            paddle.static.InputSpec(shape=[64, 256, 9, 9], dtype='float32'),
            # parameter_3
            paddle.static.InputSpec(shape=[256, 256, 1, 1], dtype='float32'),
            # parameter_10
            paddle.static.InputSpec(shape=[64, 64, 3, 3], dtype='float32'),
            # parameter_8
            paddle.static.InputSpec(shape=[64, 64, 3, 3], dtype='float32'),
            # parameter_14
            paddle.static.InputSpec(shape=[64, 64, 9, 9], dtype='float32'),
            # parameter_13
            paddle.static.InputSpec(shape=[64, 64, 9, 9], dtype='float32'),
            # parameter_12
            paddle.static.InputSpec(shape=[64, 64, 9, 9], dtype='float32'),
            # parameter_4
            paddle.static.InputSpec(shape=[64, 256, 9, 9], dtype='float32'),
            # parameter_1
            paddle.static.InputSpec(shape=[256, 1024, 1, 1], dtype='float32'),
            # parameter_9
            paddle.static.InputSpec(shape=[64, 64, 3, 3], dtype='float32'),
            # parameter_0
            paddle.static.InputSpec(shape=[256, 2048, 1, 1], dtype='float32'),
            # data_3
            paddle.static.InputSpec(shape=[None, 256, None, None], dtype='float32'),
            # data_2
            paddle.static.InputSpec(shape=[None, 512, None, None], dtype='float32'),
            # data_1
            paddle.static.InputSpec(shape=[None, 1024, None, None], dtype='float32'),
            # data_0
            paddle.static.InputSpec(shape=[None, 2048, None, None], dtype='float32'),
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