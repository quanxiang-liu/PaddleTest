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
    if enable_cinn is None:
        return True
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

def ApplyToStatic(net, use_cinn):
    build_strategy = paddle.static.BuildStrategy()
    build_strategy.build_cinn_pass = use_cinn
    return paddle.jit.to_static(
        net,
        input_spec=net.get_input_spec(),
        build_strategy=build_strategy,
        full_graph=True,
    )

class InstanceTrait:

    @classmethod
    def instance(cls):
        if cls.instance_ is None:
            cls.instance_ = cls()
        return cls.instance_

    @classmethod
    def static_instance_with_cinn(cls):
        if cls.static_instance_with_cinn_ is None:
            cls.static_instance_with_cinn_ = ApplyToStatic(
                cls.instance(),
                use_cinn=True
            )
        return cls.static_instance_with_cinn_

    @classmethod
    def static_instance_without_cinn(cls):
        if cls.static_instance_without_cinn_ is None:
            cls.static_instance_without_cinn_ = ApplyToStatic(
                cls.instance(),
                use_cinn=False
            )
        return cls.static_instance_without_cinn_


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

    def train(self, use_cinn):
        if GetEnvVarEnableJit():
            net = self.prepare_static_net(use_cinn)
        else:
            net = self.prepare_net()
        paddle.seed(2024)
        out = net(*self.inputs)
        return out
    
    def prepare_data(self):
        self.inputs = self.get_inputs()
        for input in self.inputs:
            input.stop_gradient = True

    def prepare_net(self):
        return self.get_test_class().instance()

    def prepare_static_net(self, use_cinn):
        if use_cinn:
            return self.get_test_class().static_instance_with_cinn()
        else:
            return self.get_test_class().static_instance_without_cinn()

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





last_stage_failed = (IsCinnStageEnableDiff() and LastCINNStageFailed())
class PrimitiveOp_83e962f96d985dcea27ed3dee49da724(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 20.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2100], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4ee5185a64a5ad3ea2aa9dd8d14f503e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_83e962f96d985dcea27ed3dee49da724
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]



class PrimitiveOp_0aad6c3bada90c78edca3fbf88b0d0bb(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2100], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58c5076b979b4331aa2323e2dd91266e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0aad6c3bada90c78edca3fbf88b0d0bb
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58c5076b979b4331aa2323e2dd91266e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0aad6c3bada90c78edca3fbf88b0d0bb
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]



class PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.bool, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='bool'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b2602a9727214ce531b830a00cb8ca83(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 2100], dtype='int32'), 'bool'),
        ]



class PrimitiveOp_7cca1944cc14c1ee26be00ff74757300(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.float32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[768], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2c593ef2dc63414ee2a917e6afcee68b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7cca1944cc14c1ee26be00ff74757300
    def get_inputs(self):
        return [
            paddle.uniform([768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 1.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bff6fa6c1528411965b29c304cb6a2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[2002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bff6fa6c1528411965b29c304cb6a2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[2002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc03a3e19cec254b482564131278b4c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1021], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc03a3e19cec254b482564131278b4c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1021], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1db6604384332c1e9865bde9ade6016(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1db6604384332c1e9865bde9ade6016(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1002], dtype='int32'),
        ]



class PrimitiveOp_f41b287300dc68c36c2e308eaa9ba794(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 80.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 3549], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eb18171f039dc9847ae04c5f60fb3752(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f41b287300dc68c36c2e308eaa9ba794
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]



class PrimitiveOp_bcfc52fcd477fcb6c114feac8e608653(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 3549], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7b4b3c1b3ab3b4af2767fa7c9ca912e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_bcfc52fcd477fcb6c114feac8e608653
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7b4b3c1b3ab3b4af2767fa7c9ca912e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_bcfc52fcd477fcb6c114feac8e608653
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e202d4cb5f6815d92aaaf5d7e83e3158(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 3549], dtype='int32'), 'bool'),
        ]



class PrimitiveOp_311d1476bcd32b3877f2fb1dff25d31a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 20.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4116], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_89a4d56337cdb26f3863d1928813c49c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_311d1476bcd32b3877f2fb1dff25d31a
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]



class PrimitiveOp_19949c9211074570548c5bc57db76883(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4116], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_33562cf2cf4c28fbd94381149981d556(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19949c9211074570548c5bc57db76883
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_33562cf2cf4c28fbd94381149981d556(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_19949c9211074570548c5bc57db76883
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc82e74f0bcebd2a88f14e7e1ffd36e7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 4116], dtype='int32'), 'bool'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57e19654653873baa81eabb39333255a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1027], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57e19654653873baa81eabb39333255a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1027], dtype='int32'),
        ]



class PrimitiveOp_b3795d71f36951a1cde60902212500d7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 20.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d58f320272437504317b5d434377792a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b3795d71f36951a1cde60902212500d7
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]



class PrimitiveOp_575ebcd135a309273b4dbf3366be63e3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ef76a63032aaac7d0238fde5559fbd1e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ef76a63032aaac7d0238fde5559fbd1e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 2100], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b2602a9727214ce531b830a00cb8ca83(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 2100], dtype='int32'), 'bool'),
        ]



class PrimitiveOp_dc2e0dfb5a02076b0b6aa61191815106(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 0.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.float32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5bce3cd1f7d51a232f64d74db3126130(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dc2e0dfb5a02076b0b6aa61191815106
    def get_inputs(self):
        return [
            paddle.uniform([768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bff6fa6c1528411965b29c304cb6a2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[2002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bff6fa6c1528411965b29c304cb6a2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[2002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc03a3e19cec254b482564131278b4c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1021], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc03a3e19cec254b482564131278b4c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1021], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1db6604384332c1e9865bde9ade6016(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1002], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1db6604384332c1e9865bde9ade6016(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1002], dtype='int32'),
        ]



class PrimitiveOp_a3bc871c8bad17ab433b5a1c8cd87517(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        input_1 = 80.0
        return paddle._C_ops.full_like(input_0, input_1, paddle.int32, paddle.framework._current_expected_place())

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c5b07661de3f66e82fad139e1ff5d443(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a3bc871c8bad17ab433b5a1c8cd87517
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e3e2156c5c1aefde91e93eb2a052bfc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e3e2156c5c1aefde91e93eb2a052bfc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 3549], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e202d4cb5f6815d92aaaf5d7e83e3158(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 3549], dtype='int32'), 'bool'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7fd704b2ba89da31851956e8ad532530(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b3795d71f36951a1cde60902212500d7
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e78afbfad6aede796454346eff45500(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e78afbfad6aede796454346eff45500(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_575ebcd135a309273b4dbf3366be63e3
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1, 4116], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc82e74f0bcebd2a88f14e7e1ffd36e7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c795a3031af9ac40974e6aa80e3679d
    def get_inputs(self):
        return [
            paddle.cast(paddle.randint(low=0, high=2, shape=[1, 4116], dtype='int32'), 'bool'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57e19654653873baa81eabb39333255a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1027], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57e19654653873baa81eabb39333255a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_996ad4757d90d629d9c2346dbd6c0e72
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[1027], dtype='int32'),
        ]




if __name__ == '__main__':
    unittest.main()