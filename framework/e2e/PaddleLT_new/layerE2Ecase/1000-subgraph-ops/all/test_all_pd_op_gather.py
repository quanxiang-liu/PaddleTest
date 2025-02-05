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
class PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 7, 7], dtype='float32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f74dcb048224805e3276b3045b90673(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[300, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0f67bc2d3caf82abfd3b5ba78ab7af95(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]



class PrimitiveOp_820b8ef457efcb578663afa12ff60a27(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 256, 7, 7], dtype='float32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eadffc1c4df79f7bc107dfab6f78b194(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_820b8ef457efcb578663afa12ff60a27
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_16108bd9b72768c12ee7a11d72a1e83a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[100, 1], dtype='int32'),
        ]



class PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='int32'),
            paddle.static.InputSpec(shape=[None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d581a6e096ef059f5ad6a66cedabb1ab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([3], dtype='int32').reshape([1]),
            paddle.randint(low=0, high=3, shape=[2100], dtype='int64'),
        ]



class PrimitiveOp_093484c3ddc6ed56224288150ed1ae7c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 4], dtype='float32'),
            paddle.static.InputSpec(shape=[None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b165cc9dd77534941dce1d53edb66df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_093484c3ddc6ed56224288150ed1ae7c
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.1503038853406906, 0.04364101588726044, 0.4485945999622345, 0.3969551622867584]], dtype='float32').reshape([1, 4]),
            paddle.randint(low=0, high=3, shape=[2100], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_23908edb0499e56988365e05a5916d0c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]



class PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='float32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7eabf67e5b841ae51db6df087e62b7fe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([185691], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]



class PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='int32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_09c347db4434565de31dc17d21a2cc9b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185691], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]



class PrimitiveOp_7603578c520240d9f25b89c17ee08157(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f34f718fb4caef638a1b79aa40ac139(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4], [2]], dtype='int64').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f34f718fb4caef638a1b79aa40ac139(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4], [2]], dtype='int64').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eadffc1c4df79f7bc107dfab6f78b194(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_820b8ef457efcb578663afa12ff60a27
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0f67bc2d3caf82abfd3b5ba78ab7af95(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4ec98544f8c56187e4aee884be2299b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([9, 5], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[2002], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1db1cd6bdaa2a087c6b660b1b154b39c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([6, 0, 2, 8, 9, 6, 2, 5, 4, 0, 2, 4, 2, 2, 3, 5, 2, 4, 4, 1, 0], dtype='int32').reshape([21]),
            paddle.randint(low=0, high=3, shape=[1021], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e04cbad298d59fe2326fe2e6da5c2ff4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([242991], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_189d14f3bcbdacbe75be0fe100e458b5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[242991], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57fd3a120edc6f5269ece0028b2d249e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([242991, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [0], [6], [1], [5]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_57fd3a120edc6f5269ece0028b2d249e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([242991, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [0], [6], [1], [5]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f6d96bfe319f6d651c328fa2430344d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5f81b4f7cabb0e807490073c54fa0fe0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([8, 5], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[1002], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b3502c70d4bf4c789c5f7fb99f85e76(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([171888], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4442a39d8fd43f061bbd8b1c05cd2be3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[171888], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5362e1c2af48cfddca33c82edc939f00(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5362e1c2af48cfddca33c82edc939f00(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1]], dtype='int64').reshape([5, 1]),
        ]



class PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 14, 14], dtype='float32'),
            paddle.static.InputSpec(shape=[None, 1], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64b0619b38efd470ca09ffcefec4a863(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([6, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5]], dtype='int32').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b3502c70d4bf4c789c5f7fb99f85e76(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([171888], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4442a39d8fd43f061bbd8b1c05cd2be3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[171888], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d42f4993a87643dcffb164044fc369d2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1], [3], [3]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d42f4993a87643dcffb164044fc369d2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1], [3], [3]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4e62c2cf97b39743509d3ed02359b9a4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([3, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2]], dtype='int32').reshape([3, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_28aeb8120ed03bac0da3ffac813ac79b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([217413], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f4470ae37413465107e19d966d24c52(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[217413], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2ab670fd2c73aec4072c876b95e8ccd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([217413, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[103, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2ab670fd2c73aec4072c876b95e8ccd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([217413, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[103, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eadffc1c4df79f7bc107dfab6f78b194(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_820b8ef457efcb578663afa12ff60a27
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_564446043313208a186106fb1c6b60ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]



class PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[49, 8], dtype='float32'),
            paddle.static.InputSpec(shape=[49], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d2c7faf9c08246e553c6837e31cae5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5bf1d56f0dcb9642bef0a1f6f5622056
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8666fb912472923e495ee2a586a5640a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([6, 6], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[3549], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e41673d46c4b377399fb4d1e9e8df4f6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_093484c3ddc6ed56224288150ed1ae7c
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.33601894974708557, 0.49781355261802673, 0.28972992300987244, 0.49367406964302063], [0.23135510087013245, 0.3880614638328552, 0.16228419542312622, 0.05693240836262703]], dtype='float32').reshape([2, 4]),
            paddle.randint(low=0, high=3, shape=[3549], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98f5ea242286c7e4dd702bbe185f67ab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([7, 64, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_564446043313208a186106fb1c6b60ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f89150f66edf78bb5ad6ef6f36f611bb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([86970], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e63d016a85dbbb1f305df1373adef9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[86970], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c24282bf52b1b1909e1ce1e2fcea2b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([86970, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [5], [1], [0], [0], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c24282bf52b1b1909e1ce1e2fcea2b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([86970, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [5], [1], [0], [0], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a3e60fe4c3642cb706b00fdb700b82b2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([205923], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aaeb6793c96f0d3a1f0d57ff0d917661(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[205923], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c273076240c177f72302f2605c8859a5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([205923, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [0], [8], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c273076240c177f72302f2605c8859a5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([205923, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [0], [8], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_42138215c69cdf775a5c118c6cca00ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([153450], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_711bfe0aa037bf625fe21d93d6d965c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[153450], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9bda06a1c373f0e38e7ea92e47a1cbbc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1], [7], [4], [8], [3]], dtype='int64').reshape([10, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9bda06a1c373f0e38e7ea92e47a1cbbc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1], [7], [4], [8], [3]], dtype='int64').reshape([10, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5dd8e4d00ab821746f11d246d7811e1c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([5, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4]], dtype='int32').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a6d70ab033baac2576d5492150001f33(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([3], dtype='int32').reshape([1]),
            paddle.randint(low=0, high=3, shape=[4116], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_37cd510fe35867b972202a168c09151d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_093484c3ddc6ed56224288150ed1ae7c
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.06195584312081337, 0.3410966396331787, 0.32643094658851624, 0.28816238045692444]], dtype='float32').reshape([1, 4]),
            paddle.randint(low=0, high=3, shape=[4116], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f6d96bfe319f6d651c328fa2430344d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4fade1b3ce7da604ee6be12fbbfd93e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([113061], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e977800c4f3ae073a1579e8ddf402507(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[113061], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6127e1e37f2f8e778126fe953ecd79e1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([113061, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[2], [6], [7], [8]], dtype='int64').reshape([4, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6127e1e37f2f8e778126fe953ecd79e1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([113061, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[2], [6], [7], [8]], dtype='int64').reshape([4, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f6d96bfe319f6d651c328fa2430344d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_564446043313208a186106fb1c6b60ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_61cc19782613eb076a591381673562f6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([123783], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9da7773268af15e11c1a2ac56ac33741(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[123783], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bd51c1f390fe56d7ed4116b75b5a899(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([123783, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[84, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bd51c1f390fe56d7ed4116b75b5a899(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([123783, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[84, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f74dcb048224805e3276b3045b90673(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[300, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7eabf67e5b841ae51db6df087e62b7fe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([185691], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_09c347db4434565de31dc17d21a2cc9b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185691], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7de3e2e9865064c5ac945654d9f00d3d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7de3e2e9865064c5ac945654d9f00d3d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5dd8e4d00ab821746f11d246d7811e1c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([5, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4]], dtype='int32').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_42138215c69cdf775a5c118c6cca00ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([153450], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_711bfe0aa037bf625fe21d93d6d965c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[153450], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa00d4d12bc115861016849ea0542be6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa00d4d12bc115861016849ea0542be6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1]], dtype='int64').reshape([6, 1]),
        ]



class PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[49, 16], dtype='float32'),
            paddle.static.InputSpec(shape=[None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71e7ca7a5b5577a55ea7da34fb685907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d31ca2776c0fa8f7f5023e406e12e2e4
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]



class PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 1
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
            paddle.static.InputSpec(shape=[None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83a075bdbad5edd31fa1481b512ea8d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([100, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([5, 3], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83a075bdbad5edd31fa1481b512ea8d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([100, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([5, 3], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_900b5b890502c8c89f3a62d01cc1c67b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([300, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 9], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_900b5b890502c8c89f3a62d01cc1c67b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([300, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 9], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c400fdb5365f154625d336b5347f1b92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_564446043313208a186106fb1c6b60ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c68e087e710223107fb3bed3a53cb4b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([2, 2, 3, 5, 2, 4, 4, 1, 0, 6, 8, 6, 0, 6, 9, 3, 4, 9, 4, 0, 0, 7, 8, 6, 1, 9, 3], dtype='int32').reshape([27]),
            paddle.randint(low=0, high=3, shape=[1027], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa564165eae7d3594c527394bb3dd90c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_16108bd9b72768c12ee7a11d72a1e83a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[100, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_564446043313208a186106fb1c6b60ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]



class PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[196, 4], dtype='float32'),
            paddle.static.InputSpec(shape=[196], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf4034cf69cd50ad1a097e4e7b3419f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b3465e3b203b5be5fcfcc771c20ac50
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3e7832895110b8c222e30fcfb0ae0bec(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([220968], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_36fbee912cb9066d5f4ad7c97e28c6e2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[220968], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5a913af728f97224cb75694e050de435(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([220968, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [5], [2], [2], [8]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5a913af728f97224cb75694e050de435(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([220968, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [5], [2], [2], [8]], dtype='int64').reshape([5, 1]),
        ]



class PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[196, 8], dtype='float32'),
            paddle.static.InputSpec(shape=[196], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_736336bfdaa1db0d5091542876022950(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b66194313bbec1479a5e196a1aec9b4f
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]



class PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[16, 12], dtype='float32'),
            paddle.static.InputSpec(shape=[None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ea31c93408cadaddcb2424744a3ed21c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 0, 1, 0, 0, 0, 2, 0, 0, 1, 0, 2, 2, 2, 0, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_677aa4125b8a8ec141082aa02f0d102a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 0, 2, 0, 1, 2, 0, 1, 2, 2, 2, 1, 2, 2, 2, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_29c5af48db42ac0a53d8c34abfa6b2a4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 2, 0, 2, 0, 2, 0, 1, 2, 2, 1, 1, 1, 2, 1, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_91d3418b6f9e544baa4e53d957a97411(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 2, 1, 0, 1, 2, 2, 1, 1, 2, 0, 0, 0, 1, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_82ebd29865442a778acde7f3547adab5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 2, 1, 2, 2, 2, 2, 2, 1, 2, 2, 0, 0, 1, 2, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_952c43273d57031a2053dde42feb66f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 2, 2, 0, 0, 2, 0, 2, 2, 1, 2, 2, 1, 1, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c80d657d7ea9c0d32f8451beec70afa7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2, 1, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_30e78e160800c7d1b8619cbb6780b93c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 0, 2, 1, 1, 1, 2, 1, 1, 0, 0, 1, 1, 0, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_955b7fab39d736286b16d488d5ac26c4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 2, 0, 1, 2, 1, 2, 0, 0, 0, 2, 0, 1, 2, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ea797ac06ebe4c3831e6bc87a75a3a09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 1, 2, 0, 1, 2, 1, 2, 2, 0, 2, 1, 2, 0, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_25a1b79a8a78d763035906012e745cdc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 1, 0, 1, 1, 2, 2, 0, 1, 1, 1, 1, 2, 0, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_430609e5e39be9e28b11ad6b8d9d23e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 0, 1, 2, 1, 2, 2, 1, 2, 1, 0, 0, 1, 2, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8dd582e9d22e9b22ba94ac006d0fc5b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 0, 1, 2, 2, 2, 2, 1, 2, 2, 0, 1, 1, 2, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_53104937beb969cf1bfab69ff3ca4137(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 2, 2, 2, 0, 2, 1, 2, 0, 2, 2, 0, 1, 1, 1, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b6a48d9d7c8db797fcee83f13423f85(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 2, 0, 2, 1, 2, 2, 1, 0, 1, 1, 2, 1, 2, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8b4a9780a053a04fb32070482e8fcc87(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_651ebf37af0b14a4eccdc0f4ae38b3be
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 0, 2, 0, 2, 0, 0, 2, 0, 1, 2, 0, 1, 2, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b7664340fe2a4589ac4cacc5506c79c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6766c3938d537c118f25fa145c8a8ac0
    def get_inputs(self):
        return [
            paddle.uniform([185658], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_35135aaadef2b81d14c1a4a69bc674af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb375b0f6e96a0641ec5818872f5f171
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185658], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8a1dd3560cd91715e6d2a1e06153211f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185658, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [1], [6], [9], [2], [8], [2]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8a1dd3560cd91715e6d2a1e06153211f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7603578c520240d9f25b89c17ee08157
    def get_inputs(self):
        return [
            paddle.uniform([185658, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [1], [6], [9], [2], [8], [2]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f6d96bfe319f6d651c328fa2430344d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e76d368aa7b1a7be866cf25805e35d6
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64b0619b38efd470ca09ffcefec4a863(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96c9abf9600a00da8aba2e072cb7d448
    def get_inputs(self):
        return [
            paddle.uniform([6, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5]], dtype='int32').reshape([6, 1]),
        ]



class PrimitiveOp_aadacf8cdf25463843f4879e3059aa71(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None], dtype='float32'),
            paddle.static.InputSpec(shape=[None, None], dtype='int32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a800b348e3acd90a761e9f8c6965fb5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[300, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_77980fe073dab324b0f6aba7a4e3f7e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b7944fbcda3906db091c7f9a9fa0721(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_295f49942c57286ec5051c376c6d3639(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[100, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d581a6e096ef059f5ad6a66cedabb1ab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([3], dtype='int32').reshape([1]),
            paddle.randint(low=0, high=3, shape=[2100], dtype='int64'),
        ]



class PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
            paddle.static.InputSpec(shape=[None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d13ab465e8fd3dcbb0b49cdc1092a4e6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.1503038853406906, 0.04364101588726044, 0.4485945999622345, 0.3969551622867584]], dtype='float32').reshape([1, 4]),
            paddle.randint(low=0, high=3, shape=[2100], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b7944fbcda3906db091c7f9a9fa0721(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]



class PrimitiveOp_858e98aee01312c918722a118c698ad0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='float32'),
            paddle.static.InputSpec(shape=[None, None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b54bc4d2fbb015f848c99b7d3996e36c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([185691], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]



class PrimitiveOp_0d9404637301b92050f2e4ae232fdd33(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None], dtype='int32'),
            paddle.static.InputSpec(shape=[None, None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c62536bf708de22e49a5a4894530a6b0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185691], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]



class PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0, arg_1):
        input_0 = arg_0
        input_1 = arg_1
        input_2 = 0
        return paddle._C_ops.gather(input_0, input_1, input_2)

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
            paddle.static.InputSpec(shape=[None, None], dtype='int64'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a7a6ea8b5f67300488da715420c0c27(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4], [2]], dtype='int64').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a7a6ea8b5f67300488da715420c0c27(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4], [2]], dtype='int64').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b7944fbcda3906db091c7f9a9fa0721(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_77980fe073dab324b0f6aba7a4e3f7e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4ec98544f8c56187e4aee884be2299b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([9, 5], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[2002], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1db1cd6bdaa2a087c6b660b1b154b39c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([6, 0, 2, 8, 9, 6, 2, 5, 4, 0, 2, 4, 2, 2, 3, 5, 2, 4, 4, 1, 0], dtype='int32').reshape([21]),
            paddle.randint(low=0, high=3, shape=[1021], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4cd14bb1201f61f618edfb9b6e43d92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([242991], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d757c4a9bb4c3d527c64a3ec3b17012b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[242991], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_127e5bdbdd4cd64b98b3bd37fe014b2a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([242991, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [0], [6], [1], [5]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_127e5bdbdd4cd64b98b3bd37fe014b2a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([242991, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [0], [6], [1], [5]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98d46ed24f3a2ff4359d84ba41dce754(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5f81b4f7cabb0e807490073c54fa0fe0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([8, 5], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[1002], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_82d4b468af12b85620504a22e3e74d79(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([171888], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a3f6661cb5e0d9eb3b10199a0162cee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[171888], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_27ee42d2d6a729282672d80c9fbba56c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_27ee42d2d6a729282672d80c9fbba56c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8562ac092366d2e8cfafc8d5f244d149(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([6, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5]], dtype='int32').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_82d4b468af12b85620504a22e3e74d79(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([171888], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a3f6661cb5e0d9eb3b10199a0162cee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[171888], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f98d550541b7306cafc1682a8dab0f29(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1], [3], [3]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f98d550541b7306cafc1682a8dab0f29(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([171888, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [4], [1], [4], [1], [3], [3]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a794478972cf6113cd21a3371fe32743(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([3, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2]], dtype='int32').reshape([3, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bfdb4f334d53f51bf9a85a508960ea13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([217413], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08b77cd2229cdad305876a9316529687(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[217413], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b33a291f7fa55b24946a51330062ff2a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([217413, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[103, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b33a291f7fa55b24946a51330062ff2a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([217413, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[103, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b7944fbcda3906db091c7f9a9fa0721(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([2, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1]], dtype='int32').reshape([2, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b154f7862b115453e2a1681188992e8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e70f14a80b4163d5b62e0617dd9c20da(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8666fb912472923e495ee2a586a5640a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([6, 6], dtype='int32').reshape([2]),
            paddle.randint(low=0, high=3, shape=[3549], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6967df53b18ef7816e8712c243b5405d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.33601894974708557, 0.49781355261802673, 0.28972992300987244, 0.49367406964302063], [0.23135510087013245, 0.3880614638328552, 0.16228419542312622, 0.05693240836262703]], dtype='float32').reshape([2, 4]),
            paddle.randint(low=0, high=3, shape=[3549], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a34c1fdc6bc2fdaec5cf44cf85124cd8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([7, 64, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b154f7862b115453e2a1681188992e8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0d95252ef09396543f0778aee1cc53df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([86970], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad4bb77fda970ff646f76a483181c7ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[86970], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a77b3beeb224828db2bd013f676b37f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([86970, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [5], [1], [0], [0], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a77b3beeb224828db2bd013f676b37f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([86970, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [5], [1], [0], [0], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_398252f6e646c2d0310a4ccc8b041b5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([205923], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3ace2f4c3a562ff51178be8519ce86c6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[205923], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_73fb491f172b7d498d0f228f88629b4c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([205923, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [0], [8], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_73fb491f172b7d498d0f228f88629b4c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([205923, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [0], [8], [4], [1]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a29ca6d3c7dd47f5e7e27c91ca938c09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([153450], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cb4cad712ff6c8e9aed72b74c7ee6a05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[153450], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_13da72b0bd2cf283002f796f9f1ee51c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1], [7], [4], [8], [3]], dtype='int64').reshape([10, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_13da72b0bd2cf283002f796f9f1ee51c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1], [7], [4], [8], [3]], dtype='int64').reshape([10, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fdd7f9f1b3d2e79dc5ab6e1f9bf796f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([5, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4]], dtype='int32').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a6d70ab033baac2576d5492150001f33(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([3], dtype='int32').reshape([1]),
            paddle.randint(low=0, high=3, shape=[4116], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6d93b6f40bda6fd3a308fc3adbab8d03(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.to_tensor([[0.06195584312081337, 0.3410966396331787, 0.32643094658851624, 0.28816238045692444]], dtype='float32').reshape([1, 4]),
            paddle.randint(low=0, high=3, shape=[4116], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98d46ed24f3a2ff4359d84ba41dce754(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_acdfa5882c90012a0b5986b3593b9463(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([113061], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_32278feb01f7eb8df18dd6d515c7422d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[113061], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a71874a03379489635363cc748b46257(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([113061, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[2], [6], [7], [8]], dtype='int64').reshape([4, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a71874a03379489635363cc748b46257(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([113061, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[2], [6], [7], [8]], dtype='int64').reshape([4, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98d46ed24f3a2ff4359d84ba41dce754(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b154f7862b115453e2a1681188992e8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c0fa6dbd47e662e35b19ed513395d4d2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([123783], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aec03a20a53442cb39e6a72b02396773(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[123783], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_40ce87697705fc4f1a2350f056e3d585(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([123783, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[84, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_40ce87697705fc4f1a2350f056e3d585(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([123783, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[84, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a800b348e3acd90a761e9f8c6965fb5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[300, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b54bc4d2fbb015f848c99b7d3996e36c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([185691], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c62536bf708de22e49a5a4894530a6b0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185691], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2adfba021254fcef48644adca4c7197(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2adfba021254fcef48644adca4c7197(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185691, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[1], [1], [5], [0], [9], [2], [4]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fdd7f9f1b3d2e79dc5ab6e1f9bf796f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([5, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4]], dtype='int32').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a29ca6d3c7dd47f5e7e27c91ca938c09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([153450], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cb4cad712ff6c8e9aed72b74c7ee6a05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[153450], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7b77bb993e0789d26fe490d63c1eab6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7b77bb993e0789d26fe490d63c1eab6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([153450, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[8], [4], [4], [2], [3], [1]], dtype='int64').reshape([6, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5314d4f8b00cdf2a15500c0274e57c7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([49, 16], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[49], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83a075bdbad5edd31fa1481b512ea8d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([100, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([5, 3], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83a075bdbad5edd31fa1481b512ea8d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([100, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([5, 3], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_900b5b890502c8c89f3a62d01cc1c67b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([300, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 9], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_900b5b890502c8c89f3a62d01cc1c67b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cb84fd32792a17e2c02e2307555aeaab
    def get_inputs(self):
        return [
            paddle.uniform([300, 80], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 9], dtype='int32').reshape([2]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_22a12c33718da6b1c6862285ad7cf599(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b154f7862b115453e2a1681188992e8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c68e087e710223107fb3bed3a53cb4b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f57b45b510ee748e3ff312bed12f9c77
    def get_inputs(self):
        return [
            paddle.to_tensor([2, 2, 3, 5, 2, 4, 4, 1, 0, 6, 8, 6, 0, 6, 9, 3, 4, 9, 4, 0, 0, 7, 8, 6, 1, 9, 3], dtype='int32').reshape([27]),
            paddle.randint(low=0, high=3, shape=[1027], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1cb324209a8f5851636c346332d24f4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6], [7]], dtype='int32').reshape([8, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_295f49942c57286ec5051c376c6d3639(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[100, 1], dtype='int32'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b154f7862b115453e2a1681188992e8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([1, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0]], dtype='int32').reshape([1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9535c2f0fadc96103d3bd8a094514fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 4], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a66b7f7541dcbb569cc6b70e445cffa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([220968], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2065675f8b5cdd7125301e904e4afa16(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[220968], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_82b9218f118c208830f7aa97b3aceb10(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([220968, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [5], [2], [2], [8]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_82b9218f118c208830f7aa97b3aceb10(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([220968, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[6], [5], [2], [2], [8]], dtype='int64').reshape([5, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e8cf81a01d5a5be2f962c45971318c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([196, 8], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[196], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_33a421d6797c89a6201aefc3a714b7ca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 0, 1, 0, 0, 0, 2, 0, 0, 1, 0, 2, 2, 2, 0, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d3c3976e87a18fd980f41fd7bc46b22(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 0, 2, 0, 1, 2, 0, 1, 2, 2, 2, 1, 2, 2, 2, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bc816be5f8025c3b066c412069d7e08d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 2, 0, 2, 0, 2, 0, 1, 2, 2, 1, 1, 1, 2, 1, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a11d231f582938f00294c18a90fd4609(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 2, 1, 0, 1, 2, 2, 1, 1, 2, 0, 0, 0, 1, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_303b9042286b8b9749b831d8f5a1925f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 2, 1, 2, 2, 2, 2, 2, 1, 2, 2, 0, 0, 1, 2, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_72a7d3958ae08d092ae41fac1921714d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 2, 2, 0, 0, 2, 0, 2, 2, 1, 2, 2, 1, 1, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4507dc4b866d872eb101afd37139576(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 0, 1, 1, 2, 0, 1, 1, 2, 0, 1, 1, 2, 1, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e05dda21f361c88c56f3330a2b4c172e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 0, 2, 1, 1, 1, 2, 1, 1, 0, 0, 1, 1, 0, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b428fc0552459e5e5d5df4952f530b28(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 2, 0, 1, 2, 1, 2, 0, 0, 0, 2, 0, 1, 2, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2422e69251e0e265bb9915caf0ee657(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 1, 2, 0, 1, 2, 1, 2, 2, 0, 2, 1, 2, 0, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9f6cee727a2557721396f6a3db10d659(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 1, 0, 1, 1, 2, 2, 0, 1, 1, 1, 1, 2, 0, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_30e579c9f1930a562147ad59ceb1bb45(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 0, 1, 2, 1, 2, 2, 1, 2, 1, 0, 0, 1, 2, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ed1315e9fb62252fceefc5f81f5e9fd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 0, 0, 1, 2, 2, 2, 2, 1, 2, 2, 0, 1, 1, 2, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_13ce8dfa61967602ef8187289083bc4d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([1, 2, 2, 2, 0, 2, 1, 2, 0, 2, 2, 0, 1, 1, 1, 2], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_24b28bcf716463baf5813039aeab65a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([2, 1, 2, 0, 2, 1, 2, 2, 1, 0, 1, 1, 2, 1, 2, 0], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa869fa6068d6c1c3fbab93811eeee45(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8836dc3e04c113e83b2b0f59219fae
    def get_inputs(self):
        return [
            paddle.uniform([16, 12], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([0, 0, 2, 0, 2, 0, 0, 2, 0, 1, 2, 0, 1, 2, 1, 1], dtype='int64').reshape([16]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64d1fc2ab014a1b52bce19799e793c89(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_858e98aee01312c918722a118c698ad0
    def get_inputs(self):
        return [
            paddle.uniform([185658], dtype='float32', min=0, max=0.5),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d72b066cd3143ad9ee2866f263b07711(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0d9404637301b92050f2e4ae232fdd33
    def get_inputs(self):
        return [
            paddle.randint(low=0, high=3, shape=[185658], dtype='int32'),
            paddle.randint(low=0, high=3, shape=[256, 1], dtype='int64'),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bdbdf619f7da35f68a05cd2281e35af3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185658, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [1], [6], [9], [2], [8], [2]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bdbdf619f7da35f68a05cd2281e35af3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9a7a3b05b98bb931d5a3b8ea3ccfd031
    def get_inputs(self):
        return [
            paddle.uniform([185658, 4], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[9], [1], [6], [9], [2], [8], [2]], dtype='int64').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98d46ed24f3a2ff4359d84ba41dce754(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([7, 256, 7, 7], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5], [6]], dtype='int32').reshape([7, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8562ac092366d2e8cfafc8d5f244d149(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aadacf8cdf25463843f4879e3059aa71
    def get_inputs(self):
        return [
            paddle.uniform([6, 256, 14, 14], dtype='float32', min=0, max=0.5),
            paddle.to_tensor([[0], [1], [2], [3], [4], [5]], dtype='int32').reshape([6, 1]),
        ]




if __name__ == '__main__':
    unittest.main()