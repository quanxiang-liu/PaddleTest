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
class PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5fe27c9163701347ed1760d95d77ebec(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 91, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7ddee80ece8def108e62398726061b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_88cece23e69c774b1a59cbc5839bcac9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 784, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fd6e69fabd2b91ac22cb4e14c2a4e32(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_88cece23e69c774b1a59cbc5839bcac9
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2fd2a800eb5ab365ea67c4a3f86fc583(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 192, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_189146286565da352720831b0933f60b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2fd2a800eb5ab365ea67c4a3f86fc583
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f8d9f870806160ca2ceffa7cfd427c0e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 49, 2, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1110ccf5d1a130e882979aea1928def(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f8d9f870806160ca2ceffa7cfd427c0e
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_06d03b1a6e9227530a0fe81120add634(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 6, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6f6668cb900fea632b3eeba6efdc17d8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06d03b1a6e9227530a0fe81120add634
    def get_inputs(self):
        return [
            paddle.uniform([11, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 3, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_21a71f58f6e272cbdab2e50fa3b5a8aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 168, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0256548e22d5597f456cac5d22b4ac75(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 84, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c1765d1e3a188ad0c8bf3033290871a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 42, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c33a575e78450dcea4eb6884a9025362(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 21, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d34823c1868bf7b15f51a28a8c4a6a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eaa330b0e95baaaf1d3fa320cf0cafc6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 168, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa9dc6d49fa0e0bfa58e01087e63d9c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 84, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_be05cea208acb8953517976d2550fc4e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 42, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ff94e7a30a48f4189d2f9f4ed8d5755(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 21, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c7564bc27a906d9764c50da365e6fca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_48966755ca6ceb0f5d7a29d9c93d9260(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[300, 256, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9ba0fc47f3bbcb15fba54383e3c33d70(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_48966755ca6ceb0f5d7a29d9c93d9260
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d1973e038880d59e2acb4e9275dc7168(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 8, 7, 8, 7, 96], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7040d720cd816ce698dd54aed6d882e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d1973e038880d59e2acb4e9275dc7168
    def get_inputs(self):
        return [
            paddle.uniform([11, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e6c394a3793cbe0ff80ff96f1908ab0d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 64, 49, 3, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9eef3a73d411c6ac1d02a3432ef50ba0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e6c394a3793cbe0ff80ff96f1908ab0d
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3b5ec21679dd4b54bff2092462279966(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 64, 3, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8702e7bbae79c90859e8301881530f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3b5ec21679dd4b54bff2092462279966
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f52bdd0941f65a9f3a6a513d236c3be3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 3, 4, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b72f442162356427965a299ee1898f09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f52bdd0941f65a9f3a6a513d236c3be3
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ce2dfa4d284a34e360ba103641d3c4e8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 4, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d4e4d7fd7ec39ad8fff31a7ee416152(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce2dfa4d284a34e360ba103641d3c4e8
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1314fcd766e95cdefc46ed0c22415add(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 4, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_95d23c7d6c227b693a0530c48f9cbcf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1314fcd766e95cdefc46ed0c22415add
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_428967a8dfc5510002dfdc42449920e0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 198, 3, 3, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_534e21178c6eae113c37fd5abf28db27(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_428967a8dfc5510002dfdc42449920e0
    def get_inputs(self):
        return [
            paddle.uniform([54, 198, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a92c537e79650a1abcba543c33aaae76(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 3, 198, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa4faeed964d357cab24fd1758ad7ff4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a92c537e79650a1abcba543c33aaae76
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e2a6abbf25e84032c7e40186061d0b7f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 3, 198, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c58d9501b529ab713acae0325db762c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e2a6abbf25e84032c7e40186061d0b7f
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9e4d80cebaa6b15237c1dea248a2328c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1960, 16, 2, 4, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af3902f65ac44a28120da041f7ce86fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9e4d80cebaa6b15237c1dea248a2328c
    def get_inputs(self):
        return [
            paddle.uniform([1960, 16, 2, 4, 6], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1ab5e8203dcfce66e6cb1cb100ab5190(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1960, 16, 4, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3451e854cfad0429a74933bca25973e3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1ab5e8203dcfce66e6cb1cb100ab5190
    def get_inputs(self):
        return [
            paddle.uniform([1960, 16, 4, 6], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6b03ac42ae8983b762e2a93600e2ac22(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1960, 4, 16, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6fea8479ee2835903e5e3240794162e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b03ac42ae8983b762e2a93600e2ac22
    def get_inputs(self):
        return [
            paddle.uniform([1960, 4, 16, 6], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_823d3b3dd178dcdda7be23c113aded67(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 784, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1054e9154381729e7108a867ae45d93e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_823d3b3dd178dcdda7be23c113aded67
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b93154984e30987e3e9367bdc4e92bb7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 192, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69d61af3deac8e53ad951d8b500bda3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b93154984e30987e3e9367bdc4e92bb7
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3238a44c2ef9eeb2442c230be8d5637a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 49, 2, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e164021bec1f30166ac86f246a48f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3238a44c2ef9eeb2442c230be8d5637a
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a44e9cd3fd8434394cd08560134c37bc(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 6, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_504e39eae5fa8d0007755f3cb1c53df7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a44e9cd3fd8434394cd08560134c37bc
    def get_inputs(self):
        return [
            paddle.uniform([43, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_81ea641a39a5efcb55e69c733454984a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_29064f454d982d0f18a2167561111ffb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_81ea641a39a5efcb55e69c733454984a
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 128, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_488a38eb27414dc6811fdaa9ed029865(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 128, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9f81f5eea9d4426d195b8700468b0e7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_488a38eb27414dc6811fdaa9ed029865
    def get_inputs(self):
        return [
            paddle.uniform([16, 128, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6fa5ebbf2f1e56f51bb47b4860681c8b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 7056], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_df48dec90544647e126bac3330b5c86c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 68, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_67369ce5919f1a31ec2debc5a6f226d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 7056], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_72882147bf683d35fd717002ca7b71ff(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 8, 7, 8, 7, 96], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6754758248fc44b1dd20830f82c728b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_72882147bf683d35fd717002ca7b71ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1bc04dd3971ca724a309e8524d22f7d0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 64, 49, 3, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ff23fe83b2025d3fccb70156a0fa4fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1bc04dd3971ca724a309e8524d22f7d0
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6f487f709bd50533d0b4708d77eb4f65(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 64, 3, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b3d83d27508819afb295a745dc8b9af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6f487f709bd50533d0b4708d77eb4f65
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2c63ae1001e4eaa58792a6066aa28215(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 4, 19], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c3fe3491ac40c9a03a7ec46386acdba(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2c63ae1001e4eaa58792a6066aa28215
    def get_inputs(self):
        return [
            paddle.uniform([1, 3549, 4, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c775f8ac7f857dbf86bb46d49c52c8e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 160, 240], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6031cdcb96d9c59d1d13b43ba2ae4c40(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 80, 120], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1b90318aa09d39d2d84d37481308ae6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 40, 60], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_73dc812e7ea07a1312277756ec863b67(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 20, 30], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b2c9cd202757e7d69347079da819a8a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 10, 15], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f9625db6e94861cfe8a60af0201a829c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 160, 240], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6464e046d1d21a051a55cacaea5c3da3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 80, 120], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a0db9841ed990c5e31edabf3bdc57e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 40, 60], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a3e89703234aa7b1eb9bc6481c19f1b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 20, 30], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2479d1e4e03049e6302413fad943ef97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 10, 15], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eabd4549bb83249c4ae16e54a8ff00be(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4d2ff8608485ac9da4ec57d4b55af0a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3344b421600a528d493b412d8a0615d9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1efbe40c1befd47f088d7030aab589bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_036bd9b361aac141f60f74376a1e17e8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0fd009ab0af118c50fd6295e42dc017f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 225], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_855bd711ca6b83fedc14a54a2b9b374f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 225], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4a8a328565e8423f0b1494d7cf89505d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[100, 256, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c3a87a879d82f533fe603d3178b3543e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8a328565e8423f0b1494d7cf89505d
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_fc0b82452d00ffdceab5cfc5fb6544f6(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 20, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_049ddfd3d534a6088a98e0e50d3afdf2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fc0b82452d00ffdceab5cfc5fb6544f6
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ae917fa163e63d25c4a4329fc6ae3e04(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 40, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ccacd60bba6ab8c5b781f6da9980acf2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ae917fa163e63d25c4a4329fc6ae3e04
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58c1e291b103880b9c3c47f212bde2b5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 152, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0be26b5063da18154ab1165d4dc202d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14f7a46d8f86dafed9113ec1c1ab47d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 4096], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b86d5b4c8e86b0ed21c6b41fd777585d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 196, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f132f825a5516ae912e9126621131d40(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b86d5b4c8e86b0ed21c6b41fd777585d
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dee4e8a0c3b15d84531710e49072ee5e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 384, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e935ebe99a9b6abe46e4017303f6d1e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dee4e8a0c3b15d84531710e49072ee5e
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a84aab7a8d01ae4125b5d30916f8e429(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 49, 2, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ef0bbbcf21e3d330e9ae7a03b255e81(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a84aab7a8d01ae4125b5d30916f8e429
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c44f25e655b12e756035769e3aa144e5(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 12, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a0c0c04a14169ecb5c4fe2b22e9d0c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c44f25e655b12e756035769e3aa144e5
    def get_inputs(self):
        return [
            paddle.uniform([43, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_61b4ea275f1a6f79053e25fa6ff43637(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 128], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6a331d61ef0538a61948a07a93b67316(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_61b4ea275f1a6f79053e25fa6ff43637
    def get_inputs(self):
        return [
            paddle.uniform([128, 16, 8, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a4d1da93a08817f588c747cdc887b142(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 320, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_188c4d52f701d486c9edebe9373c2f34(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d1da93a08817f588c747cdc887b142
    def get_inputs(self):
        return [
            paddle.uniform([128, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e8b9329ec79f57ca15f040adaa03528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4608f3949b2486ec664d5e8438b797a1(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 76, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1014643a2e12208d20ade8c7aa10e52(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4608f3949b2486ec664d5e8438b797a1
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 676], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_324cc434c441f67ea0d151a5a666b542(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8395a8f1350fc050c0d6f8d9bf4f39e8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_324cc434c441f67ea0d151a5a666b542
    def get_inputs(self):
        return [
            paddle.uniform([1, 21, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9af7eabaf118fee7980218db16940c2b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 120, 216], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_38321f6b2316562899298fc7b55bc52c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 4, 5, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 8, 8, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1b7f2361c739c0738d38f92875ae38e4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_38321f6b2316562899298fc7b55bc52c
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 8, 128, 13, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e50aa019280ab376b09b07a481d3e93a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 900], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_263ff65dd247334410b80767c49f398c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 900], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_053762e4b6127e1c7c9c29d29cda206e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2704], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_23bd422f60a7fab608d129f886e3fc0f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 3136, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f20a4d4a6c63813d369557a2262c5fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_23bd422f60a7fab608d129f886e3fc0f
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8b156747f67416c54aed7a94e37cb92a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 96, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_28be6a642cbbeb5c91e3b26698cd84be(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8b156747f67416c54aed7a94e37cb92a
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9b1f1149a0f8fd116eb221bddc1e128c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 49, 2, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_27d28e5a49082449a69feb65c702172f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b1f1149a0f8fd116eb221bddc1e128c
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7fa021c983fac5629661f1821bac6ec2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 3, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa9d58449cc16eb55191289f48a04d14(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7fa021c983fac5629661f1821bac6ec2
    def get_inputs(self):
        return [
            paddle.uniform([43, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b1be3e8e85fd197ebc5d88956f68888b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f52bdd0941f65a9f3a6a513d236c3be3
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3df17ecc2b1e2a9841197f26a6ad1a21(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce2dfa4d284a34e360ba103641d3c4e8
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c25840f596ec09a5bd141360b66df05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1314fcd766e95cdefc46ed0c22415add
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_36eed832590267664b821ec237968ffb(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 15, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd7008fa48b0af7905d5ee870678a3dd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_36eed832590267664b821ec237968ffb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ac88110b853fdc5a5e147f68170a960f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4608f3949b2486ec664d5e8438b797a1
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 169], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_726fd52e455faf4c50bc388b248c5535(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 512, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ec8fae866f2adf60196aaadd7286f193(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 32768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1304eaf4dcde6a7d9ebe7560fe0e917a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 19, 512], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_436dcbc843ba3cad72891fa0cc7251c8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1304eaf4dcde6a7d9ebe7560fe0e917a
    def get_inputs(self):
        return [
            paddle.uniform([1, 19, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5aa5893cfd398d34fc947e7f475812bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b46b524178dba13b66315462034e3328(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a42476adff7592305a52125eec81f038(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1156], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f6a6e513cb7063b1365896af119a9389(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 4, 17], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e93f1ff8219d7f90f9b31598b61d7075(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 7581, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_74c99010dc852a6b76064274950ee7ff(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_62d76956567be7bb16ee0858569fcae7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([528, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_336e3303d0797164559ec8785c129935(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 1, 24, 48, 2, 96], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_917355b7681354ced07123cb58f97449(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_336e3303d0797164559ec8785c129935
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_84d1f83425e2cdb01d02dd8a70e83237(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 5776], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_44a9e94600e37fd043d586856e21c672(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 5776], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_fe3a32849f7d52f07cb5f6d492e7b879(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 4, 7, 4, 7, 192], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8374081e75e596134d04b0106b268249(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fe3a32849f7d52f07cb5f6d492e7b879
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_06bbed2e632e0bf15f3fbbfb387899b3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 16, 49, 3, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d93b3d9c7e24cfede9e46cc6b22b98c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06bbed2e632e0bf15f3fbbfb387899b3
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_be4edfeb0f1c5868b68f467c3ef6faaf(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 16, 6, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c00356bf1708442d2dde84ccae2e203e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_be4edfeb0f1c5868b68f467c3ef6faaf
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ef4dba020da2ad17165d922cb67a522(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 16384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_10a49f53a90976b2428b2b9bf30d596d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 21, 512], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a5e4ac59718f67c9ea9d86c5966a1f05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_10a49f53a90976b2428b2b9bf30d596d
    def get_inputs(self):
        return [
            paddle.uniform([1, 21, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0ff0bff5fc7a0adb04ee0ded0a28548(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cce8fc7611eaee3ea599c6d30c0fdcfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 576], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c8f24ed3f7867066a03e3e9f86bd7190(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 1, 12, 24, 192], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c4d29a6ed621be287b84871a320041a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c8f24ed3f7867066a03e3e9f86bd7190
    def get_inputs(self):
        return [
            paddle.uniform([6, 2, 1, 12, 24, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_211fbff682529d27ade693ad05b14b20(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_61b4ea275f1a6f79053e25fa6ff43637
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_349cd736c23c1965b5b84b9d1b6b6d69(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d1da93a08817f588c747cdc887b142
    def get_inputs(self):
        return [
            paddle.uniform([8, 320, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aacd62182cf3cf9201bf182baded9adf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 4725, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_97ab8d489c99e5c9c953637f4a6e9cbe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_81ea641a39a5efcb55e69c733454984a
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 64, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f38a7da709a268d1490cc29ae71518f5(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 160, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58ed8c1e6cccafdb7bf1fc9a9be966b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f38a7da709a268d1490cc29ae71518f5
    def get_inputs(self):
        return [
            paddle.uniform([8, 160, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae7ce85098821b5ad1bc1ac57791dd55(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 12, 12], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_266419ae99acd4915de197cd6dda793f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 3, 12, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9be8375a0a39107271d521d4e37aae80(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_266419ae99acd4915de197cd6dda793f
    def get_inputs(self):
        return [
            paddle.uniform([1, 577, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4b71d8035b9d029cb6f8f12878a767a2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 12, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e931a60fe3d494151f7afd0cdb95a9c8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4b71d8035b9d029cb6f8f12878a767a2
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 577, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f23cbbc71fe2c82b59339a7382d24537(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 12, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f0b77b8b1d91e488cc4ca0eab56f95d1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f23cbbc71fe2c82b59339a7382d24537
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 577, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_51a00d7e7a4bdb0fc5b743383c48447e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1296], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_752da25c52043e3b8f29cd7ff57dd6b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1296], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_664c072d4d6d7df3cc95b8564d1eb4b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1296], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2421358d5656138a3b0c9cfc93bb10f3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b2ebd6408e4db9ee7bb0b04471107f60(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2421358d5656138a3b0c9cfc93bb10f3
    def get_inputs(self):
        return [
            paddle.uniform([64, 64, 16, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c05365aaa76c24f20c7d31b264d9da75(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 64, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c58a9205082e73d7aa6b3eed44781aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c05365aaa76c24f20c7d31b264d9da75
    def get_inputs(self):
        return [
            paddle.uniform([64, 64, 256], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8dccbff135b7b5bffd5db324f35d409c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[10, 197, 2, 6, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d6b2d9b6a806fdad3b0fcdadd5c14a20(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8dccbff135b7b5bffd5db324f35d409c
    def get_inputs(self):
        return [
            paddle.uniform([10, 197, 2, 6, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9bda78905e1937e852565aaf0b28e306(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[10, 197, 6, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5df4ac11a415f79ddec22969bfb5ed23(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9bda78905e1937e852565aaf0b28e306
    def get_inputs(self):
        return [
            paddle.uniform([10, 197, 6, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_977320a67f81ea8a29f4284ebff28128(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[10, 6, 197, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3ecb4edb7398444b8613671a60b6dfd2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_977320a67f81ea8a29f4284ebff28128
    def get_inputs(self):
        return [
            paddle.uniform([10, 6, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ccc493cdfb81d202dec2e2258ee0447(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_36eed832590267664b821ec237968ffb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e75f49f8dc4006251992bdb1d90c4e09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([384, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4dd56b28cc18560559f6c9ad623773e4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 1, 96, 96, 1, 48], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d26d3c8cbca85fcba3291ea8cdde393f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4dd56b28cc18560559f6c9ad623773e4
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 96, 96, 1, 48], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_50e12b655507c0f99c0058f1442036a5(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 4, 7, 4, 7, 192], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ebd699f9db91d5c93baf78ec2b48a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_50e12b655507c0f99c0058f1442036a5
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7d69d49268612593b1a1ac63f706ea27(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 16, 49, 3, 6, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b7bb519c1497d3010ac7fa98ba2eb08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7d69d49268612593b1a1ac63f706ea27
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_adf20cb6f18b6c09609014bdbef92b2f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 16, 6, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0b6fa7a01106908b6a8fac4b5f217986(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_adf20cb6f18b6c09609014bdbef92b2f
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4450cddfe5db585438d8c882546cc486(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 16384, 2, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e2362f1877ee9a69939372a9836edb9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4450cddfe5db585438d8c882546cc486
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 2, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dd933078a9217d1a7515ded224cd58d7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 16384, 128], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8b4b3d724db276dbbdefbb7f976e0907(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dd933078a9217d1a7515ded224cd58d7
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_73fff7225b96c2f3d2686d736e0f4919(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 128, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6364a44c626d52882c9088aa4b7ee94c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_73fff7225b96c2f3d2686d736e0f4919
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_953f1ad4c5f2bcd95ab65bb2b8365215(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 2, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f23c556e61f905018766d561fb5cba12(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_953f1ad4c5f2bcd95ab65bb2b8365215
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 2, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b9cbecdc49a43231daae760b79e70db3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_32342ce9a43007a83e1b3629f057e564(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b9cbecdc49a43231daae760b79e70db3
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 1024, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e700062a2afc27d4ecd81240c991d97d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 16384, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7c42adea038093e1b5dd5e543c6a3f8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e700062a2afc27d4ecd81240c991d97d
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16384, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c84b7c7d2eb29d085839c6517a1bcce1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_36eed832590267664b821ec237968ffb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f20a4d4a6c63813d369557a2262c5fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_23bd422f60a7fab608d129f886e3fc0f
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_28be6a642cbbeb5c91e3b26698cd84be(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8b156747f67416c54aed7a94e37cb92a
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_27d28e5a49082449a69feb65c702172f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b1f1149a0f8fd116eb221bddc1e128c
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa9d58449cc16eb55191289f48a04d14(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7fa021c983fac5629661f1821bac6ec2
    def get_inputs(self):
        return [
            paddle.uniform([43, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5f99363e68646747c2ec73a4333ad8c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_81ea641a39a5efcb55e69c733454984a
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 64, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5cd4d81e97b0e399c7e32bfac2622b4b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_488a38eb27414dc6811fdaa9ed029865
    def get_inputs(self):
        return [
            paddle.uniform([16, 128, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_804c1cca46309f40eee236ef68049f77(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 169], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_78bcb1de2f885b624c4ae75683c98729(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 49, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e5537529fdb15566e2c316cfe33f2569(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_78bcb1de2f885b624c4ae75683c98729
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d33c07a830370360a6779b99b04b6402(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 49, 2, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_48e76d4ae2a7e7e7d104d052a07f1417(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d33c07a830370360a6779b99b04b6402
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b2747b6ac6d92b9ded1edcdae489d8c9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 24, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5fcf4e75e1a669fb5e7405d590b75dd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b2747b6ac6d92b9ded1edcdae489d8c9
    def get_inputs(self):
        return [
            paddle.uniform([43, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_066eb93615fbbcfcef1fa6496642e2f6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b7af8b82237f9b274ac078472d49eab7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 8400, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08c4b4f73c93d31588338e16673b0f65(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_307e0ff3bcdfd5640d6895a1686ba7c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_44088f250586a8ccb1ec9e363dce3a0a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_81ea641a39a5efcb55e69c733454984a
    def get_inputs(self):
        return [
            paddle.uniform([8, 32, 64, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ce7ae8f0ea2100b6b9c07cd7e843da1b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f38a7da709a268d1490cc29ae71518f5
    def get_inputs(self):
        return [
            paddle.uniform([8, 160, 512], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_fc30c73d627179a4f53151fcce1d9290(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 768], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1661cb7258547516b588eb25e5e55997(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fc30c73d627179a4f53151fcce1d9290
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_65efa7702f16107cac07eaeabb6cdb32(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 3549, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_0e6d43403343a16295559e126d10e29d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 768, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f745e73dc7f0cf795f822a5149e2d21(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0e6d43403343a16295559e126d10e29d
    def get_inputs(self):
        return [
            paddle.uniform([1, 768, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 96, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d3cf35252a128ab70b994d89870b44e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 60800], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e9346d67dae78aeacbd7d573d9396aea(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 96], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e0033c9938917f865647c78edbdf9c2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e9346d67dae78aeacbd7d573d9396aea
    def get_inputs(self):
        return [
            paddle.uniform([1, 60800, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_32b88ef3678f330d8ae0794a679960c4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 96, 60800], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aca831bfefd1020f0ea52aaad8cb86d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_32b88ef3678f330d8ae0794a679960c4
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 60800], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_257517a20f3b69a16af86e655a4f7df4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 3, 2, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dbac802d2270b623b843007e8b6dfe2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_257517a20f3b69a16af86e655a4f7df4
    def get_inputs(self):
        return [
            paddle.uniform([10, 640, 3, 2, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c128086d3feef53be6b4f7ecf28d94b9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_062738f2f3b3da4cd78548f2a4273a00(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c128086d3feef53be6b4f7ecf28d94b9
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 640, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f03a7321ee8397289d299e72ba68a9f2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a7fd2f20eabed7f2adec3a8351a2c4f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f03a7321ee8397289d299e72ba68a9f2
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 640, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 5, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9691664c39a43b6b06a80c6fc183dac2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e6fc9964b1e49c8b7001b55108e787e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_428967a8dfc5510002dfdc42449920e0
    def get_inputs(self):
        return [
            paddle.uniform([86, 198, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e7953131e2af4fa570c1dc9081995b58(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a92c537e79650a1abcba543c33aaae76
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69d15dad39d321db2c31c36701129288(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e2a6abbf25e84032c7e40186061d0b7f
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_787aab3956d00ca4fd43ab4a7daf37f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dba5f153171acb084a94d437fff97b2c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1600], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_17c111f36c96c5cbf06e406aa1c4d895(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 3136, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9829abd1c9b63a1ab4dcebc983308a45(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_17c111f36c96c5cbf06e406aa1c4d895
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9158dc0bcab49eab9cc067e315a41023(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 96, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_85a1c7485d69c1abe1f48752c04923b8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9158dc0bcab49eab9cc067e315a41023
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d693113c5ecc11e640fc40c188a0bba7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 49, 2, 3, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08b4e44db77041168c2f2ce33548c90f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d693113c5ecc11e640fc40c188a0bba7
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_721e67e98cb009a09a4bdef520c4233c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 3, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9c25b3633187c2f6bf663b96d9ac645b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_721e67e98cb009a09a4bdef520c4233c
    def get_inputs(self):
        return [
            paddle.uniform([11, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dc902e6420da9fc7157a872fc75969de(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 96, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_220cf6d70b0966667a9bc541a0972382(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dc902e6420da9fc7157a872fc75969de
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_44b2f3c154eb240ebea1ba087e5f448b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([20, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_901072681875b6da654268b4aab22733(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 1, 2, 24, 12, 192], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ef25fa42d9b84c96895830be27bdbb96(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_901072681875b6da654268b4aab22733
    def get_inputs(self):
        return [
            paddle.uniform([10, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad41dbbc60522340811e5c05b790ac89(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_76d30189a00da51acae6cfdcae77bdb8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_40318c7f08654689b5bfb3491983001d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 1, 7, 1, 7, 768], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_df562738f601a7681c49e3d4affac04a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_40318c7f08654689b5bfb3491983001d
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6c0fd1be147dc4b3a287c0d221b6f6d1(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 1, 49, 3, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4807ed19794202a938016f2c23fca9ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6c0fd1be147dc4b3a287c0d221b6f6d1
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5401c3ee15e0cc35b6132827a13b3641(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 1, 24, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_72d9cc3618c1ffe00e5e0a1655e2b809(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5401c3ee15e0cc35b6132827a13b3641
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_111e995f4b9aa6bae8365f96b19e4b80(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[4312, 16, 2, 4, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e0fbd124850f7b33250f375994795f7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_111e995f4b9aa6bae8365f96b19e4b80
    def get_inputs(self):
        return [
            paddle.uniform([4312, 16, 2, 4, 6], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5d16eeec0c782633fe57c2cbd68ac01c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[4312, 16, 4, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4fba8ee5bb09b8d582151661a02656b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5d16eeec0c782633fe57c2cbd68ac01c
    def get_inputs(self):
        return [
            paddle.uniform([4312, 16, 4, 6], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_31d3f538c132ee9381f4ce56f8b2b2fd(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[4312, 4, 16, 6], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6f37b7f89411b1dc17de38c710618005(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_31d3f538c132ee9381f4ce56f8b2b2fd
    def get_inputs(self):
        return [
            paddle.uniform([4312, 4, 16, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_036bd9b361aac141f60f74376a1e17e8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9755472a5b5e5f56d1394ed5485af3e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 441], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e870cc5dd5b2b4018bef3f2b5168136(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 441], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6754758248fc44b1dd20830f82c728b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_72882147bf683d35fd717002ca7b71ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ff23fe83b2025d3fccb70156a0fa4fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1bc04dd3971ca724a309e8524d22f7d0
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b3d83d27508819afb295a745dc8b9af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6f487f709bd50533d0b4708d77eb4f65
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b46b524178dba13b66315462034e3328(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_750a7397303685aab8eb1a45eebd05fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4626a7a1c31b607a81bcb49a779d43bb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1156], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a2dec3bbe14702332aa653680a3c0895(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4096, 1280], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1ad1f2b2152d9b457330d9e94d1b8bd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a2dec3bbe14702332aa653680a3c0895
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 1280], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e405ab1151749daf7df3392db174754e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1280, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1eae4322e3875a2a020d8d333ac55d17(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e405ab1151749daf7df3392db174754e
    def get_inputs(self):
        return [
            paddle.uniform([1, 1280, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_690e6c50ab7d510bbae209aad6687f5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6f3355a28a634ab1f1dd6832ca05f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_112d8037f5cc54896aca83ed029c201c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfcbd3069c07c78bf3fd8215965fad7e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d34823c1868bf7b15f51a28a8c4a6a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9850ec0f15bdd7c0958c5eb003ebe781(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_503afc8cd94a0246146ea0197ec9f78f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae4723b4fca9c8becea26ffeeb1cdaf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e110a6be5c50fcc502a375d86f66df88(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c7564bc27a906d9764c50da365e6fca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1208e2235e433643e4ee18def747d657(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 32, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa3ac71b9c1aa25fa6b8afd14aba9290(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1208e2235e433643e4ee18def747d657
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 65536], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_365556e52fc01ff899dc7905b52f4b7d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([576, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9bc42ca3d206af7e7285e597635260c8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 96, 1, 1, 96, 48], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99c471167a94ba25d9713e4372b95f2d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9bc42ca3d206af7e7285e597635260c8
    def get_inputs(self):
        return [
            paddle.uniform([6, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1cfe6c14e1c8dc9a012d6f104f53361c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b79fa1ad3893a5c6ef3bf350f60446e3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1cb9881a2c95dcf1b5b949cd1bb9f49e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0f688632ed7200621df7463f0fd5a7d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_324cc434c441f67ea0d151a5a666b542
    def get_inputs(self):
        return [
            paddle.uniform([1, 19, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1604523a4c102d23b9e1315d763f4540(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_695bf2e9a733ac7ee577cc96421660c6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa2fa83760c8ae241d9a81223bf08296(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b734ac24a577b1a9ddbfc04edbbc7225(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([6, 96, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fbd7e170e083c7d2f549eb5f30be19cd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7227ff3602c466482284a7152414484a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 1, 1, 12, 12, 768], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_50c3518caf0887039c16c80a49e91d21(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7227ff3602c466482284a7152414484a
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8109374442dd4c89a607307e9186f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([96, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b3936e0b9733966d9fba0d5ee8439133(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_336e3303d0797164559ec8785c129935
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6cdc3aceebbbfa2ea2dea2b6b4270c92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([12, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c4d29a6ed621be287b84871a320041a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c8f24ed3f7867066a03e3e9f86bd7190
    def get_inputs(self):
        return [
            paddle.uniform([6, 2, 1, 12, 24, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1aaef06c90cbcc5a9e427ea3693bc49e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 8, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8d57be438e7da80dad0cbf9d401f0940(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1aaef06c90cbcc5a9e427ea3693bc49e
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_08b2a4b199c3c68a57decd774c927153(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 2, 8, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bf1eefa47125993093a0d57f9998200(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_08b2a4b199c3c68a57decd774c927153
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 8, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_46ad176715e290dc5bebc4d6ce12eae7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 8, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b07d607de3ea8a99e3d47af6e0dad100(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_46ad176715e290dc5bebc4d6ce12eae7
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a4d22e85fc35fcfaa17772bf14c7824c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 8, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_96bae0aa4928b1d6ee5c8d7d4a7dd0ab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d22e85fc35fcfaa17772bf14c7824c
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f937869ac973f38967907fe5d117d1d2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_53594ce0004ecc52f7b5e63caa668b43(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6303398552bbe18875a2652eb3b8c88c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([6, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff465f4fe77f63f4cee082584aacf199(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7227ff3602c466482284a7152414484a
    def get_inputs(self):
        return [
            paddle.uniform([6, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e8b9329ec79f57ca15f040adaa03528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1ff8a2eb3b3ce1ffb7da9c95bfca8d3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_76d30189a00da51acae6cfdcae77bdb8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b1ae040e1999008dd4bdcadb474976dd(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 196, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_55073f96d31f12ffd26fb15b8614d9f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b1ae040e1999008dd4bdcadb474976dd
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_41626a0619b53cfa4728ab3780207f7b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 384, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_35f69d5078911e7c0b9fc96f8e90d657(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_41626a0619b53cfa4728ab3780207f7b
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ce6036c3c1c4e0c7f32434aa0183b01f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 49, 2, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_23de91d8989ad976032a455dd7fc4276(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce6036c3c1c4e0c7f32434aa0183b01f
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_84f56aec61b3d19a2926e13590981d93(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 12, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e0bdedf8d09cc9e148e49fc8efcb40e1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_84f56aec61b3d19a2926e13590981d93
    def get_inputs(self):
        return [
            paddle.uniform([11, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dd8939275f794301715db95603734ba0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([960, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2e31814610a1992a327a9b94c5b6f96(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9bc42ca3d206af7e7285e597635260c8
    def get_inputs(self):
        return [
            paddle.uniform([10, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b72f442162356427965a299ee1898f09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f52bdd0941f65a9f3a6a513d236c3be3
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d4e4d7fd7ec39ad8fff31a7ee416152(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce2dfa4d284a34e360ba103641d3c4e8
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_95d23c7d6c227b693a0530c48f9cbcf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1314fcd766e95cdefc46ed0c22415add
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ccacee9cbfe2a3ffbb2b223ccc1a3f6d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 3, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 16, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_661958d3791fc5d56382d94be7cb71a4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ccacee9cbfe2a3ffbb2b223ccc1a3f6d
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 38, 38], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a5c3bf71209f96e5bf1f63c8fdab47a4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 3, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 84, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_729c4a5aadea1ae2421d1e4acbfcb9ef(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a5c3bf71209f96e5bf1f63c8fdab47a4
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 38, 38], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b3d99b09d224c99006c843711ca126c8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 3, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 24, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e2863db5baa51d3e1f748a5cdc4dbec(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b3d99b09d224c99006c843711ca126c8
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 19, 19], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_685d2d62ae07c6502c52204b1c0d04fe(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 3, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 126, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a5e741f5149ffaaaa4a4a9839d80d511(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_685d2d62ae07c6502c52204b1c0d04fe
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 19, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ffc975f8de7b61c3ab12827755f9681a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b3d99b09d224c99006c843711ca126c8
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 10, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d69e0c062e0712a57b487e35e99a7b72(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_685d2d62ae07c6502c52204b1c0d04fe
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 10, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_154269bfbe3013eceeeeddbe49be34c2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b3d99b09d224c99006c843711ca126c8
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 5, 5], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_15a813d9bfec129c456fe638834ba7e2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_685d2d62ae07c6502c52204b1c0d04fe
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 5, 5], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fc14c2dae4e9a4bce70aed01a2efebb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ccacee9cbfe2a3ffbb2b223ccc1a3f6d
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 3, 3], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b0b968270b0a6ad337ef281ff6dd690(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a5c3bf71209f96e5bf1f63c8fdab47a4
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 3, 3], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d32e102cdbae9852d81d2ad21e1aa6a4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ccacee9cbfe2a3ffbb2b223ccc1a3f6d
    def get_inputs(self):
        return [
            paddle.to_tensor([[[[15.76220989227295]], [[15.502686500549316]], [[15.361867904663086]], [[14.869795799255371]], [[15.781167984008789]], [[15.610716819763184]], [[15.02834701538086]], [[16.097217559814453]], [[13.993327140808105]], [[16.281068801879883]], [[14.921567916870117]], [[15.6120023727417]], [[14.636691093444824]], [[14.480208396911621]], [[15.682112693786621]], [[14.734054565429688]]]], dtype='float32').reshape([1, 16, 1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1c4db2668123e64b5af102c74552d44(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a5c3bf71209f96e5bf1f63c8fdab47a4
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 1, 1], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_950f5af402a5681c12ca729bd171d2a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([2112, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2948236dd30a739d092525441158bfa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9bc42ca3d206af7e7285e597635260c8
    def get_inputs(self):
        return [
            paddle.uniform([22, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_96ff0cadea4f1816bcd86601f52e33ff(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 36, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_71553c2e7b16ea8e9dbeb02cf3d9293d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96ff0cadea4f1816bcd86601f52e33ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 36, 28, 50], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a7a2ff1a7132778352b1f6ddaaec8f11(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 4116, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1604523a4c102d23b9e1315d763f4540(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6333909df9bd5ad936039b7ad8e98760(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 289], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_cc95cfaf775b72f80ffbfd10b82b95d0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 49, 8, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd4484a0f0f7838f22ec29e3c9208de0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc95cfaf775b72f80ffbfd10b82b95d0
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd4484a0f0f7838f22ec29e3c9208de0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc95cfaf775b72f80ffbfd10b82b95d0
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7ae22e18a9a301c6cb1379ddb4c1c56e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 49, 8, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_62861a86a5839a337716bff58802d0e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7ae22e18a9a301c6cb1379ddb4c1c56e
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f73774ecdf335a247bb5fb3cce3fd86d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 8, 49, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af08244e754756f308d9b70b72e6a203(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f73774ecdf335a247bb5fb3cce3fd86d
    def get_inputs(self):
        return [
            paddle.uniform([22, 8, 49, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7f34bb30cf81eeec399368df8e5c1d71(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[8, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9e190c415a2748e87dd547bb4831b5d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7f34bb30cf81eeec399368df8e5c1d71
    def get_inputs(self):
        return [
            paddle.uniform([8, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4431284f5923f1fd8f8268e87306f8f8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[2401, 8], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3658a9f524eb776673e58464f1cb3873(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4431284f5923f1fd8f8268e87306f8f8
    def get_inputs(self):
        return [
            paddle.uniform([2401, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_094297dc80c61747b6a8e9ec837a0bc7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 192, 784], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_66e8707c0696c7f5367bbc5ac8fcab92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_094297dc80c61747b6a8e9ec837a0bc7
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_cf85c852e23cd12b270b727260a1f555(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 384, 196], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c2d12d1886a19b00b164871be3edbd3d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cf85c852e23cd12b270b727260a1f555
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_934b33e878f93249dc1c5457c5c4a7b0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 192, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5af24a7f9ecd2ff558cf8d0cf137aa8e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_934b33e878f93249dc1c5457c5c4a7b0
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e450c690ec3f3e30dd6727b87dcdea7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 6069, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_af5a8d1234de5a07337a7c58d568c84f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 5, 1, 2, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, None, 8, None, 8], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147901d42cdcd3857d70d4524009ac4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5a8d1234de5a07337a7c58d568c84f
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 4, 8, 16, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ebd699f9db91d5c93baf78ec2b48a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_50e12b655507c0f99c0058f1442036a5
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b7bb519c1497d3010ac7fa98ba2eb08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7d69d49268612593b1a1ac63f706ea27
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0b6fa7a01106908b6a8fac4b5f217986(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_adf20cb6f18b6c09609014bdbef92b2f
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6ac80c2b747b719195cf55d0dbfb6982(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5a8d1234de5a07337a7c58d568c84f
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 52, 8, 202, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_02880075520ff5c446472fa493faebfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 200, 304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de530fef89bfc4db9479c9a55df79136(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 100, 152], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0db94e5e135f8fbe39a24415e0b61ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 50, 76], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d0d686d558ccd02207c16281452eeafc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 25, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d322efe3d83b0c933fce87a8d4722ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 13, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_29276cad74c19c0e8443782104248c5e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 200, 304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_10388455c18f3271cf7b17093149f483(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 100, 152], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7fdc643a435465797c8fe3e3acd38f49(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 50, 76], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_61f4f36458c3370d2c27392b72d3674b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 25, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d6707d9bb1056d2fd84ecc542af59707(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 13, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c34b36f98eab494e458543c35917141e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 2116], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa275525de9792de5d52ee61750e268a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2116], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7ddee80ece8def108e62398726061b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b6a9abf8c13a72ec60662fd066595a16(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 3, 6, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83d02b697c8c8fa6aea272f86d6766de(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b6a9abf8c13a72ec60662fd066595a16
    def get_inputs(self):
        return [
            paddle.uniform([1, 1025, 3, 6, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3cb10a48066efe9c6cba235776656580(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 6, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa776bafbf6b4460ef261e45b819f9ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3cb10a48066efe9c6cba235776656580
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1025, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_07b9be7cdb7533f06c6f09ab037050cf(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 6, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bef98ab0ac73d475ae337b955797692(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_07b9be7cdb7533f06c6f09ab037050cf
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f6da7bf6e057e855b023adc1c348650d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c05365aaa76c24f20c7d31b264d9da75
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_765597cc8fdbd67a9d669cffabed0fe5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 4096], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_be39ec453a81deed8305c3d217d325a4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 196, 8, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bd3ee4d5ac08aeae36398170c863b9d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_be39ec453a81deed8305c3d217d325a4
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5207c09f0d5a2295236f7e84363d5b24(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_be39ec453a81deed8305c3d217d325a4
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 8, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7fee062f74ccd15cca8c6ca3aa92c439(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 49, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07b63794bc0381f48d4e84ddb53828de(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7fee062f74ccd15cca8c6ca3aa92c439
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f1f574d6d20df687890720bf37faa447(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 49, 2, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_869b336ca7800a730bb78af28736f7c6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f1f574d6d20df687890720bf37faa447
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e02782d2d7ceee8d5eef50838398eea2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 24, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_24e211f7a2883d1bdb5ba9b746cb521e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e02782d2d7ceee8d5eef50838398eea2
    def get_inputs(self):
        return [
            paddle.uniform([11, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9e363368e0ae364eebf951b0bc041607(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, None, 150], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc499dc12d6a919383948ce012261cfe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9e363368e0ae364eebf951b0bc041607
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 64, 150], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d16d111c70dbfc81b93bd686af23f409(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69d3982073f75b91251d56745a8d6786(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 136, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a38e338e7d64c4f737f26426ba008fc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 68, 80], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_016fc0cd3b0b1333a4eedd66cb223cf4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 34, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_808de5ecd5518df1af140ffa30d3e111(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 17, 20], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_87ab1fadc64bd8616cb7b001177e3c22(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 9, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_18881b5831c91ec01eec97cdb6adcf70(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 136, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9ca5d97da7d26a2b7897cbaf8c2f224d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 68, 80], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fcfc26e57cf3f24d56125e887a4233f3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 34, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e2d896bb780bc94b8785baf5d6157d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 17, 20], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_70fc792b31784fb3986b8d5eeceb701d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 9, 10], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5b05158962af3d46e3d50e41c1a447ac(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, 8, 8], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc0b432e8c856992363ba68d37843601(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5b05158962af3d46e3d50e41c1a447ac
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16, 512, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e5063f3743885cbde9596be8ae7773a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f863be0c2fdacff305c354a76cf29628(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 256, 160], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_934f39144372f5cba83a8e73a59a1cfc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f863be0c2fdacff305c354a76cf29628
    def get_inputs(self):
        return [
            paddle.uniform([10, 256, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7ddee80ece8def108e62398726061b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f37bdbb104c670af8d9e3360b9f0f49(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5b05158962af3d46e3d50e41c1a447ac
    def get_inputs(self):
        return [
            paddle.uniform([1, 13, 13, 512, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1f183ccac1102d24820bded4f088aced(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 96, 3136], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d08e0e330e79b1464c0fea0382abd305(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1f183ccac1102d24820bded4f088aced
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 3136], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_17f3e865131a021f5b4e524736b3775f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2048, 5, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_48080601ccbf1f1f28d52db0e2ac90e2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_17f3e865131a021f5b4e524736b3775f
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 5, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dd8cfc04414ea3958e439debabdb27d2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2048, 160], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07e43b4750b4bd9be14bb7aead802001(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dd8cfc04414ea3958e439debabdb27d2
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 160], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6e74936f1973777e1b48c5e1ac462825(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 160, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bbbe60fb1255d7120b0aede17dd8355a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6e74936f1973777e1b48c5e1ac462825
    def get_inputs(self):
        return [
            paddle.uniform([1, 160, 512], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dfe6182e61d494017a1566a583491925(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 5, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2ad638bb6be9fb0f085e067a9390017d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dfe6182e61d494017a1566a583491925
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 5, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_67d82c9b859b778e4bb5a6a1d1307a04(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a4e502d599ed5d81a7a9f531d79416d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_67d82c9b859b778e4bb5a6a1d1307a04
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 512, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_393390fa3317fe01965e406ab7f39ede(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, 2048, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ccfb2a09b11ae648a0423b03129a3b1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_393390fa3317fe01965e406ab7f39ede
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 2048, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad0a5ed1c0c35f6e5be72760d0711dae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1aaef06c90cbcc5a9e427ea3693bc49e
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8ed8a28bf5a9557c559f09413453793c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_08b2a4b199c3c68a57decd774c927153
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_be823c07e4ff1eea329bd60f03858ccf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_46ad176715e290dc5bebc4d6ce12eae7
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cbb97e1145ec54a7e3983f77ba2684db(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d22e85fc35fcfaa17772bf14c7824c
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_47ba02f72d9417d513b4d424003e76eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c5b813326c8d7615dcccffeb82a64d1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6bc8ff0609a37c2ebe902607ba7c8f97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 3600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3a613036c50f43fd10763724ef4066d9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b953484b4d3b8e3e454ed7698185c2a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2421358d5656138a3b0c9cfc93bb10f3
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 64, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_420a0fbf27377230bb38b253e8907623(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c05365aaa76c24f20c7d31b264d9da75
    def get_inputs(self):
        return [
            paddle.uniform([16, 64, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_818f318b957e77396810444653b8b005(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 200, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c3ef7cb386e3229a6b1de00ececcfe3a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 128, 100], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e15f80e5ff23d93cf9711a68b0585737(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c3ef7cb386e3229a6b1de00ececcfe3a
    def get_inputs(self):
        return [
            paddle.uniform([10, 128, 100], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fd6e69fabd2b91ac22cb4e14c2a4e32(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_88cece23e69c774b1a59cbc5839bcac9
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_189146286565da352720831b0933f60b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2fd2a800eb5ab365ea67c4a3f86fc583
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1110ccf5d1a130e882979aea1928def(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f8d9f870806160ca2ceffa7cfd427c0e
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6f6668cb900fea632b3eeba6efdc17d8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06d03b1a6e9227530a0fe81120add634
    def get_inputs(self):
        return [
            paddle.uniform([11, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b69d6b7fc05f754249c7d84ba454ed5e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_53594ce0004ecc52f7b5e63caa668b43(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_10b3bb8b33416045a037de13c4a201ed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6d9762ffa2c8e6af108e53cb3433709(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1a0b22e75714849594d931407010a9d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b3bc324269d58410de7346357376e62(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4608f3949b2486ec664d5e8438b797a1
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 2704], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_83e094d410b1e1724725e08a3ed830bc(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 232, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f1e28d6e5f3a9983ed1fc4453ca1110(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_83e094d410b1e1724725e08a3ed830bc
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 232, 16, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_df562738f601a7681c49e3d4affac04a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_40318c7f08654689b5bfb3491983001d
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4807ed19794202a938016f2c23fca9ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6c0fd1be147dc4b3a287c0d221b6f6d1
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_72d9cc3618c1ffe00e5e0a1655e2b809(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5401c3ee15e0cc35b6132827a13b3641
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_06ecd7ae23a54bcfb183c0cec7a15e05(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 197, 3, 3, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fca92c09d153bd82e95c6e04d53c1625(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06ecd7ae23a54bcfb183c0cec7a15e05
    def get_inputs(self):
        return [
            paddle.uniform([54, 197, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_77bfb361561ff676b55505f59df8c0e3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 3, 197, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_974747c064ba32d036c2fddd4c2ada9a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_77bfb361561ff676b55505f59df8c0e3
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_96e80e6e5d02dd64c9c8a8380ef677a8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 3, 197, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b09e1d4ac867e300852ea58806296c96(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96e80e6e5d02dd64c9c8a8380ef677a8
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7b3be978485eafcd96c44a699867cdef(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 16, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69da44419c2b281114a654baad8c74f1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7b3be978485eafcd96c44a699867cdef
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9bf5224dc7c667d013e308fad8ee5987(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1208e2235e433643e4ee18def747d657
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 32768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6b50c96d03539b8ff5bfffbf76164111(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 65536, 1, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c32183c5daef331b1151e587840c8a86(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6b50c96d03539b8ff5bfffbf76164111
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 1, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_765f2d4791e1805cd69053f42f4ca09d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 65536, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7909d3b71da12be0cd6cca3e8c9cb0b5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_765f2d4791e1805cd69053f42f4ca09d
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_de1972fec47383d747a019d298c33e88(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 32, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c44a666e3950235993f673a11f01f34(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_de1972fec47383d747a019d298c33e88
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_23e023d725dc9733d992004aa4c17078(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 1, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e76e683c07116c7b4e730575f665a97b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_23e023d725dc9733d992004aa4c17078
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 1, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a13a216b0659e0e24e2cc9b88f6a327c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f6d7501dae2e52e5ca41cd55e7faeb27(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a13a216b0659e0e24e2cc9b88f6a327c
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_709c2e5c28e38923c83afd5b074c5f44(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, 65536, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e170713bc4a398d50e9e253d3ef8562(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_709c2e5c28e38923c83afd5b074c5f44
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 65536, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9ba0fc47f3bbcb15fba54383e3c33d70(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_48966755ca6ceb0f5d7a29d9c93d9260
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_706fb2fa636c211c456609ff7fc40039(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 640, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_cc12ea5e4cac3505ab61495602b8c3fe(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 128, 320], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_17e27ad4cd41f25e5560c8025270cc2b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc12ea5e4cac3505ab61495602b8c3fe
    def get_inputs(self):
        return [
            paddle.uniform([10, 128, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4b11eb46edcbde223da7944942d5955(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_36eed832590267664b821ec237968ffb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_47ba02f72d9417d513b4d424003e76eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e13f77905e0af807837b61ac41dcb69c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4c1bba9a443f75a5c46ce7d256bb68c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_804c1cca46309f40eee236ef68049f77(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f131ccec24ee4e9576e44b1764156228(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0e6d43403343a16295559e126d10e29d
    def get_inputs(self):
        return [
            paddle.uniform([11, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cd5fa1daf6f5ae1510a8056c4e54f77a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2264ed632825bbc12108f4752c6f5c13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 529], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c68cce38dbfa3245cc0270cb4d883c64(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 529], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8374081e75e596134d04b0106b268249(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fe3a32849f7d52f07cb5f6d492e7b879
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d93b3d9c7e24cfede9e46cc6b22b98c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06bbed2e632e0bf15f3fbbfb387899b3
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c00356bf1708442d2dde84ccae2e203e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_be4edfeb0f1c5868b68f467c3ef6faaf
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e8b9329ec79f57ca15f040adaa03528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8edc26a7650051b32ad323e100bcdf07(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 160], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_434f820db800af8b248ade0a63230c9b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8edc26a7650051b32ad323e100bcdf07
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 32, 160], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4c8d9a66d1e97987f32826b0c707e072(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 256, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_afe9d006009954c4d8acb6ae4cbed026(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4c8d9a66d1e97987f32826b0c707e072
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0ebb3f78c5b55371eaa40f1c4ddc70f0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([8, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7dd9fe9dbe883b7fded7ba90bc3e1ef(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_901072681875b6da654268b4aab22733
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5aa5893cfd398d34fc947e7f475812bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5aa5893cfd398d34fc947e7f475812bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_787aab3956d00ca4fd43ab4a7daf37f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0c6fa3f4304ad032c073a6f3f25264ff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e9c7521e0e2fab0588b8a04b60040db(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1600], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_fc859f94499e5b98317344015690bffa(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 72, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5a1e0075a4f63a64caf964983239557e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fc859f94499e5b98317344015690bffa
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 72, 14, 25], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9829abd1c9b63a1ab4dcebc983308a45(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_17c111f36c96c5cbf06e406aa1c4d895
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_85a1c7485d69c1abe1f48752c04923b8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9158dc0bcab49eab9cc067e315a41023
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08b4e44db77041168c2f2ce33548c90f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d693113c5ecc11e640fc40c188a0bba7
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9c25b3633187c2f6bf663b96d9ac645b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_721e67e98cb009a09a4bdef520c4233c
    def get_inputs(self):
        return [
            paddle.uniform([11, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1a79d9dabe3e3747915e24733b6d00bc(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 384, 196], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a879e6163adbe8ea5f9b661f32362ef(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1a79d9dabe3e3747915e24733b6d00bc
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad943ea04877db050898978da95b3639(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_38321f6b2316562899298fc7b55bc52c
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 8, 128, 4, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_625d12fa66edb2affce7c2ed354662e2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf8dfcc9b1bdcefbfd6d64600997831d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 96, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b1be3e8e85fd197ebc5d88956f68888b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f52bdd0941f65a9f3a6a513d236c3be3
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3df17ecc2b1e2a9841197f26a6ad1a21(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce2dfa4d284a34e360ba103641d3c4e8
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c25840f596ec09a5bd141360b66df05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1314fcd766e95cdefc46ed0c22415add
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6bb7a7923b000f8c70804bcf56ca10d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 361], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_51e25c528e53bc2bfb8adaaf3c6980a5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 361], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7ddee80ece8def108e62398726061b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_45c69ed0ed3e4cd646081f22404a66ad(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 32768, 1, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e04aac556264c3e846af4e1cfa62758d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_45c69ed0ed3e4cd646081f22404a66ad
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 1, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_70eb838b6126c289d07db3ed28465025(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 32768, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f8907d5d337e8c9cfad3226856a6bda9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_70eb838b6126c289d07db3ed28465025
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_05aef4de2780226f44a51d6c4c26253b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 64, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7c34f7531be7cf1c4b2ff6e6782b9c0f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_05aef4de2780226f44a51d6c4c26253b
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 512], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f9c06380b63410f49ee44d8d8984255e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 1, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c68844b76c138abe175179612a5ec6a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f9c06380b63410f49ee44d8d8984255e
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 1, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6f87a8b50c0814038d2ca231913b326b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad2c20d5ad8eb60ed5f444bc1c6843c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6f87a8b50c0814038d2ca231913b326b
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 512, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_098b4c8f5e1fdcd07bf431fc3d1d7d6a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, 32768, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bd88b92d677059d5d261a5f107946c4f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_098b4c8f5e1fdcd07bf431fc3d1d7d6a
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 32768, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07b63794bc0381f48d4e84ddb53828de(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7fee062f74ccd15cca8c6ca3aa92c439
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_869b336ca7800a730bb78af28736f7c6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f1f574d6d20df687890720bf37faa447
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_24e211f7a2883d1bdb5ba9b746cb521e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e02782d2d7ceee8d5eef50838398eea2
    def get_inputs(self):
        return [
            paddle.uniform([11, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc499dc12d6a919383948ce012261cfe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9e363368e0ae364eebf951b0bc041607
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 64, 150], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b340498713a234d122a45814bd46dab2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_00c7425bf966be9f0dd10b04700af1bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e12d5f5c5dc39e171b3adcc2f1115561(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_257517a20f3b69a16af86e655a4f7df4
    def get_inputs(self):
        return [
            paddle.uniform([10, 200, 3, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bd293a431fd451ad4fbb8748c6401fff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c128086d3feef53be6b4f7ecf28d94b9
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 200, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_97ceafdbe9590f8fed2c699fe00721ed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f03a7321ee8397289d299e72ba68a9f2
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 200, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_abfd47d5333f7e3c1aa8ee7613dcd0f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 9261, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c9b112b74b13508fadfa2dd8e70471ff(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 16, 16, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eb324df2c87c62d47c06a3d2e486aafb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9b112b74b13508fadfa2dd8e70471ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 16, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_79e31cb51626bd7c1cec4cac7d255551(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[16, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1fe70a9ecfd3d16178cb8c51eaad0610(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_79e31cb51626bd7c1cec4cac7d255551
    def get_inputs(self):
        return [
            paddle.uniform([16, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e5aa38e5628897ac493547f3a5c0db86(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_10d3a6de56068e7b4ef37521d0d7fd71(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e5aa38e5628897ac493547f3a5c0db86
    def get_inputs(self):
        return [
            paddle.uniform([784, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ac3dce6b0facfa2fd094d52993200d12(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 49, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_06ebac3828052c699b15dd6e01dcd735(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fc30c73d627179a4f53151fcce1d9290
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_6051ef2e4bf9da51acbb93d7c03750f9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 197, 2, 6, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5f9f4a0aab2e9604cc6ab9bbb9109839(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6051ef2e4bf9da51acbb93d7c03750f9
    def get_inputs(self):
        return [
            paddle.uniform([22, 197, 2, 6, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_252fac5f1e85c21d9df4cf18cb384174(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 197, 6, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14fc49fadb38e36a40b3120f12175a4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_252fac5f1e85c21d9df4cf18cb384174
    def get_inputs(self):
        return [
            paddle.uniform([22, 197, 6, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b0b944e472832d4bdd2124f65fea9e74(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 6, 197, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bf50e62480492468205eb7a5adc69f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b0b944e472832d4bdd2124f65fea9e74
    def get_inputs(self):
        return [
            paddle.uniform([22, 6, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bd36d775c87740aa089dbd5a390aeb61(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_09644369ddab57c3458bd8f04ae9ddc4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 256, 50], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_78902c059ea3addbb2bfde833f7b60c4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_09644369ddab57c3458bd8f04ae9ddc4
    def get_inputs(self):
        return [
            paddle.uniform([10, 256, 50], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_630505d0f10ef58fbd219e836931db71(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 21760], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_41b949caefeb3d2ed80fe28b46daec9e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e9346d67dae78aeacbd7d573d9396aea
    def get_inputs(self):
        return [
            paddle.uniform([1, 21760, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5c06ff5979cff2837e52b6d04aa704c7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 96, 21760], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4dcdc367ecd5491b7f8cc3e241c9c38f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5c06ff5979cff2837e52b6d04aa704c7
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 21760], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0776438211dba298985d7c0be9994f85(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([240, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b81d7268321b56467f522cecbdf355f3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_336e3303d0797164559ec8785c129935
    def get_inputs(self):
        return [
            paddle.uniform([10, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c9adb44198add626d809097f415ab29(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([4, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5494e4c3d64732b5e6408b834bd041a2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7227ff3602c466482284a7152414484a
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5254c11e4fd89b67f9b86fc98eea67bf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 136, 208], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e872107e80a992a0f38f6745064eca9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 68, 104], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_391d19412ec5743feee7c309801ddbf9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 34, 52], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9d93422258f9bd4c48b4b11f0389f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 17, 26], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c921d2496aea4b2da87a626a2d258514(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 9, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d46f2c6370746657ffe05a8dcbf3146(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 136, 208], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4118154386827b5ffb24af85cc418f3a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 68, 104], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff0c62ac37be427f3d613e62bebaf75d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 34, 52], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b91aa25909b730e8fcb9713b4e58785(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 17, 26], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c0bd8de44868d07b09f8d21cfeaf336a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 9, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cd5fa1daf6f5ae1510a8056c4e54f77a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 676], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_642fa4db0e830f017130b2443c07c0fe(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 2, 7, 2, 7, 384], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e6dcd3ae66e023671128f4ddb90f27d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_642fa4db0e830f017130b2443c07c0fe
    def get_inputs(self):
        return [
            paddle.uniform([43, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_0c7a9e6d72818db95987ca6659ec2475(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 4, 49, 3, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa99c063606e9f48c373c64338e91022(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0c7a9e6d72818db95987ca6659ec2475
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4c8844caa25e0a1fe0523cf976f3d2b0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 4, 12, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1ed344fb678840af2dfc39f01f41073(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4c8844caa25e0a1fe0523cf976f3d2b0
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b50e0717c863ba8b64df0665d7fbbab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cffb2e69fc5074ce0a7bacb65351b2ba(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9ef0a7edebbfc755b9d1b047c79598c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 4624], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b68e7c0b805bdc821927ee21a9b5d6ca(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 8192, 2, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1fb65aa4d9fca581c7a40caa4728215(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b68e7c0b805bdc821927ee21a9b5d6ca
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 2, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f37b247f4061cf8fa0b4c93b1cea6ee4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 8192, 128], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07158de904a3473223509a7e1b1ed3f7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f37b247f4061cf8fa0b4c93b1cea6ee4
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7b138001e0c5b0b46267d93bd7b66591(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_73fff7225b96c2f3d2686d736e0f4919
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2dfea3ce8860b245cb8e252ab22bc9eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_953f1ad4c5f2bcd95ab65bb2b8365215
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 2, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_deb40a5d662f5a567e0d350f16dfbc18(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b9cbecdc49a43231daae760b79e70db3
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 512, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_eb5a3de9ef9c0b3ef35e98988bfaabe0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 8192, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7e50bb94ab1f9e940722832d68a6b236(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eb5a3de9ef9c0b3ef35e98988bfaabe0
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 8192, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b9758dc61d6f31649cc2a955d10e0e6b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2048, 5, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ea9d031af1771257990a14a6d7e2dc0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b9758dc61d6f31649cc2a955d10e0e6b
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 5, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_557b6e95194fac4d99b1cfad9b0a3e39(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2048, 320], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_243e2f9bdc4a273dad44b9e86cf14a56(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_557b6e95194fac4d99b1cfad9b0a3e39
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 320], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d39ea56a2a54632c4bc8be936f359be1(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 320, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b783c2b50076dc2a0a22abbfe7c8b3db(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d39ea56a2a54632c4bc8be936f359be1
    def get_inputs(self):
        return [
            paddle.uniform([1, 320, 512], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_18a2940c3370928e07e1e06492080c1a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 5, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_874277d8dbcb2fe31d9a7af313094e1c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_18a2940c3370928e07e1e06492080c1a
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 5, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_542d1d2e1c057d3676dafb24c94f4a81(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_90dd841a6816a753abb60d7328fa92f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_542d1d2e1c057d3676dafb24c94f4a81
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 512, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_a6817e1b1717b7e33b26fc63216aacca(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, 2048, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1802f4a33a403a1884d665720dfe4129(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a6817e1b1717b7e33b26fc63216aacca
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 2048, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a642635f768b449eb440cb9ffa2f001b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dba5f153171acb084a94d437fff97b2c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7e98d52e59bda2b4ebfdac86d80826f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0f9401ddfd09693160cd8c69f6e181ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f16074b258dd78805070baa16a1e9082(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1957e747fcf0cdeafd0c7a484521483c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 2100, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6a60594b06f41a46326a4ce88e554ec4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c05365aaa76c24f20c7d31b264d9da75
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 8192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_631d012a9b8032c129b546769fc0a702(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 8192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f8849ff8fb429b294799e2e09203cba(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_784e52ecfd5f6701414bc33812f701c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 12, 12], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07d06f24b797be36eea0a6cd3cdc2002(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 100], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9e8b10fc4cd27f5a7921157ae8b2f0d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 100], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_eed51e1ab485260116b2fdd2e5c20d3c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 1, 7, 1, 7, 768], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4fc5e0c13de899b5a162f5078472f9fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eed51e1ab485260116b2fdd2e5c20d3c
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_273c174ec7af008390f9678ff3bb40b0(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 1, 49, 3, 24, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_304990d590e98eb0cc0553f213f34394(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_273c174ec7af008390f9678ff3bb40b0
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b12a016b9dcd04c864be8c8fc716fbab(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 1, 24, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7fca72875c05b39353dd43547122273(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b12a016b9dcd04c864be8c8fc716fbab
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bfb4d11326c0cd3b1fd4a9876d8b722(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2930772907aaedff92da232a0c19813f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 768, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f23198b83e9b006cb830822685d553f4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2930772907aaedff92da232a0c19813f
    def get_inputs(self):
        return [
            paddle.uniform([11, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f48386c77aa9301e76a5c5048b7c397e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([4, 96, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99e5382675822682b95624be29685367(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_307e0ff3bcdfd5640d6895a1686ba7c3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 400], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5f02f725a56a680583e731f5a46967f1(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 2, 7, 2, 7, 384], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_88f82a0b20ccd30f1bbd22d76bb0f257(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5f02f725a56a680583e731f5a46967f1
    def get_inputs(self):
        return [
            paddle.uniform([11, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d6352cd472c7320675e3554d47e88f80(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 4, 49, 3, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e2e7c441f11bb9f7b4f87dc230bf747(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d6352cd472c7320675e3554d47e88f80
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2bde58917356cddae4411a39c96e70aa(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 4, 12, 49, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2b1364a2419d2a12970a83bca041f5a1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2bde58917356cddae4411a39c96e70aa
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4fc5e0c13de899b5a162f5078472f9fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_eed51e1ab485260116b2fdd2e5c20d3c
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_304990d590e98eb0cc0553f213f34394(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_273c174ec7af008390f9678ff3bb40b0
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7fca72875c05b39353dd43547122273(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b12a016b9dcd04c864be8c8fc716fbab
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7b6c4f389a4983ca04df76061409b2c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_266419ae99acd4915de197cd6dda793f
    def get_inputs(self):
        return [
            paddle.uniform([1, 1025, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0ac628298d54ad9e776bfdc258891952(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4b71d8035b9d029cb6f8f12878a767a2
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae8eda228ae0729deb3bfe5c764edb3c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f23cbbc71fe2c82b59339a7382d24537
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e48e4c9d3c86c6c6d9e183839a60c41(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0e6d43403343a16295559e126d10e29d
    def get_inputs(self):
        return [
            paddle.uniform([43, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58207c09adc795f9a9760434b50adae9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([44, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd287608f51f8189084263ee4eb5efb9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_901072681875b6da654268b4aab22733
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_88f82a0b20ccd30f1bbd22d76bb0f257(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5f02f725a56a680583e731f5a46967f1
    def get_inputs(self):
        return [
            paddle.uniform([11, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0e2e7c441f11bb9f7b4f87dc230bf747(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d6352cd472c7320675e3554d47e88f80
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2b1364a2419d2a12970a83bca041f5a1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2bde58917356cddae4411a39c96e70aa
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1efbe40c1befd47f088d7030aab589bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e9e6f63331647208f5819559adf1966(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 256], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ea61355c7659359f1ac35d577e426c05(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 20, 128, 256], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_83531858a86dd398f5acd56c07361296(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ea61355c7659359f1ac35d577e426c05
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_7c20144886b3c2627adeba99809465d9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 40, 64, 128], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b565e558a4ff9d94032ceef6475186de(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_7c20144886b3c2627adeba99809465d9
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d886b2e0a8c78eee23535a64840e3a29(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 80, 32, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_500de4b7a73c451ab6c7dc87e9b6e6ff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d886b2e0a8c78eee23535a64840e3a29
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 80, 32, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_277c4be82ca2329d1c0159c384fea8ac(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 160, 16, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f067ffff6909e0df384a172e8486ebc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_277c4be82ca2329d1c0159c384fea8ac
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 160, 16, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_690e6c50ab7d510bbae209aad6687f5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6f3355a28a634ab1f1dd6832ca05f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_112d8037f5cc54896aca83ed029c201c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfcbd3069c07c78bf3fd8215965fad7e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b979dc76395563cee64433b78216b8a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9850ec0f15bdd7c0958c5eb003ebe781(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_503afc8cd94a0246146ea0197ec9f78f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae4723b4fca9c8becea26ffeeb1cdaf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e110a6be5c50fcc502a375d86f66df88(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7b2bc73c438889a959f641fa9037d31b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c3a87a879d82f533fe603d3178b3543e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4a8a328565e8423f0b1494d7cf89505d
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3ae98eab44c8224a7efd49c41e8d20b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_595ee9a66526db6f080803bacaf2af70(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 384, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fc386973f8e329757dba503c637279ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_595ee9a66526db6f080803bacaf2af70
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3c02c2aa534de28bc894e213229abee4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 8, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dec5fd162b529113a138f77a708db1f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c02c2aa534de28bc894e213229abee4
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 8, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b83ff22bbcd762a56c47d3df1fd8c2ff(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 2, 8, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d62e0a2af62626eb69013711b04355b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b83ff22bbcd762a56c47d3df1fd8c2ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 8, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1cdbd36ff3e66af4e50c907fe9f4f1a3(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 8, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_31e37f36ca786802586075c9590de707(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1cdbd36ff3e66af4e50c907fe9f4f1a3
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ea227fa7bd87a7ad593b9051b401b915(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 8, None, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_233a288cb774ffe37b2d6b43047de15b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ea227fa7bd87a7ad593b9051b401b915
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6dd1cb4ea034823dfa0923333c72496b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 11109, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7040d720cd816ce698dd54aed6d882e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d1973e038880d59e2acb4e9275dc7168
    def get_inputs(self):
        return [
            paddle.uniform([11, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9eef3a73d411c6ac1d02a3432ef50ba0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e6c394a3793cbe0ff80ff96f1908ab0d
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8702e7bbae79c90859e8301881530f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3b5ec21679dd4b54bff2092462279966
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_25206b716fdd4ef3b4cb521040f3e789(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2048, 1280], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f5581fad9eb81e855ed8633ba419b20e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_25206b716fdd4ef3b4cb521040f3e789
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 1280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_76d30f6416db2be5f6f12b0d9183657a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e405ab1151749daf7df3392db174754e
    def get_inputs(self):
        return [
            paddle.uniform([1, 1280, 2048], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e0c375657a7bb82f88c57a15820d9bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 768], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5627f68d0f9df1b981760a7f3f63bc8d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 768, 49], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a4904b9983e5905be80084f12492e532(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5627f68d0f9df1b981760a7f3f63bc8d
    def get_inputs(self):
        return [
            paddle.uniform([43, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e6dcd3ae66e023671128f4ddb90f27d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_642fa4db0e830f017130b2443c07c0fe
    def get_inputs(self):
        return [
            paddle.uniform([43, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa99c063606e9f48c373c64338e91022(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0c7a9e6d72818db95987ca6659ec2475
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1ed344fb678840af2dfc39f01f41073(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4c8844caa25e0a1fe0523cf976f3d2b0
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_053762e4b6127e1c7c9c29d29cda206e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c7860daad97f89752a032a694fd78789(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_36eed832590267664b821ec237968ffb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3f68cad29993c68ce2107a74346f0ce9(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 7, 7, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_24ce001c6b717fab5b4e28a12a4ca838(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3f68cad29993c68ce2107a74346f0ce9
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 11, 7, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e5537529fdb15566e2c316cfe33f2569(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_78bcb1de2f885b624c4ae75683c98729
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_48e76d4ae2a7e7e7d104d052a07f1417(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d33c07a830370360a6779b99b04b6402
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5fcf4e75e1a669fb5e7405d590b75dd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b2747b6ac6d92b9ded1edcdae489d8c9
    def get_inputs(self):
        return [
            paddle.uniform([43, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ce6a19c3ab146ed6baccb93edb67f0c2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 192, 25], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08c4b4f73c93d31588338e16673b0f65(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1bf3b4d147b905e69ee458ad013cd5ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_384148a9d2a926f1c0edf6cc736b8a77(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fdc2b05450cb9c5b8ffeb3f3c208ab3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 8464], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_48e54aea40da3cf1256f7793a0d29460(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 8464], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_50dfd2df778706fc91c61e93558397ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([144, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d032d08ebbb810e8490629086a933aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_336e3303d0797164559ec8785c129935
    def get_inputs(self):
        return [
            paddle.uniform([6, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ad74d2d21d9fc18817186af45159a222(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4096, 5, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af83b88ff75e65dbe9b021d0d7c2cb81(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ad74d2d21d9fc18817186af45159a222
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 5, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_38baba934b30936b5ccf8474ac222cda(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4096, 320], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_43b92489ae695d83909f6bba3a56d6a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_38baba934b30936b5ccf8474ac222cda
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_92da8679bdef2812c6d7eab413e45f56(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d39ea56a2a54632c4bc8be936f359be1
    def get_inputs(self):
        return [
            paddle.uniform([1, 320, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bb062b767dbf3ce5de2efcb410aaa1e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_18a2940c3370928e07e1e06492080c1a
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f7ab637e4297d14b14d29e73c861698(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_542d1d2e1c057d3676dafb24c94f4a81
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_87459e2230d31cb0a2d57e4fa2f52722(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, 4096, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_779c6d17429438f0588719737515d614(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_87459e2230d31cb0a2d57e4fa2f52722
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64d8cbc41470318e159d35587c404d02(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 200, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2d39824d87bccab89160ae753830f5ff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 100, 136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a367b594c15596718f46a45e3ffc3990(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 50, 68], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3dc4209970408bd310f5b7f3430536fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 25, 34], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64963df5e0509b93030222c2ec56d7e6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 13, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f2f5f80aa7a341d16d3cc55920de7f2f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 200, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0928dd19ba1ed550e919c524e7f1a871(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 100, 136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_788d8c1a2d17c947c568ef525ca282f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 50, 68], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d71016c31d565507880547ea42113b13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 25, 34], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5900804fce5225c2cdad9d6f1cdf7b42(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 13, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9c18dc05f4d07f9419f9df2efabed57d(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4096, 5, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a3c1ce149d1e8a5dc56c2b47b813303(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9c18dc05f4d07f9419f9df2efabed57d
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 5, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2b75ce29fc3c5426aed9f39b0c168476(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 4096, 160], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5192afe309a8238cb4439091968a5c70(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2b75ce29fc3c5426aed9f39b0c168476
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a4bfd82adaef9aac360c30e26e1b79c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6e74936f1973777e1b48c5e1ac462825
    def get_inputs(self):
        return [
            paddle.uniform([1, 160, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f82f137a4098d040065fdd4e2709802(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dfe6182e61d494017a1566a583491925
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 5, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_460230cc60452db4f251852021a89dd9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_67d82c9b859b778e4bb5a6a1d1307a04
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_516e8a940f44dbfca08811112d049e65(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 5, 4096, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_90489276e1dbb5a1f3374ce8517dd5b8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_516e8a940f44dbfca08811112d049e65
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5aa5893cfd398d34fc947e7f475812bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_049ddfd3d534a6088a98e0e50d3afdf2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fc0b82452d00ffdceab5cfc5fb6544f6
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ccacd60bba6ab8c5b781f6da9980acf2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ae917fa163e63d25c4a4329fc6ae3e04
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f53e6e807dd6538ec552e58beeed4dd2(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 80, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4e95fc6993623e7c4af2269494b9c2e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f53e6e807dd6538ec552e58beeed4dd2
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 80, 32, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f132f825a5516ae912e9126621131d40(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b86d5b4c8e86b0ed21c6b41fd777585d
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e935ebe99a9b6abe46e4017303f6d1e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dee4e8a0c3b15d84531710e49072ee5e
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ef0bbbcf21e3d330e9ae7a03b255e81(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a84aab7a8d01ae4125b5d30916f8e429
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a0c0c04a14169ecb5c4fe2b22e9d0c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c44f25e655b12e756035769e3aa144e5
    def get_inputs(self):
        return [
            paddle.uniform([43, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0d25b433277fb4fe86d94054c7b87fdb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3c02c2aa534de28bc894e213229abee4
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_679ad2762a07659fdad5005e3d1249d0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b83ff22bbcd762a56c47d3df1fd8c2ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2b91ac6ac32f8bcdc824e7545203c916(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1cdbd36ff3e66af4e50c907fe9f4f1a3
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b9ef61f8ec928028ce5cdd978f1c2cd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ea227fa7bd87a7ad593b9051b401b915
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_00053e25bac17b1da7049f52e2c5d5c5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 176], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_490f884289833e2d60b572017da20db4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 88], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0696de01cdab1acd51e0c19a1d3fc5b6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 44], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_90df1315eb2b9a3348f9991aa54ad528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 22], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99e99710171e5d431e3335b686c2accd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 11], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ab1831d6f3dd67a3f09fcdce90dd1992(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 176], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_68fc9a33d4008ad96e608e2f2bea6b74(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 88], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9dc5e989fc7d0af57fcc6ed2ed84479b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 44], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cd674ad60a55a26ea055cfd452eef54a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 22], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a5c957d1dcc3408bd4c5d21dd3d9bd2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 11], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e8b9329ec79f57ca15f040adaa03528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5fe27c9163701347ed1760d95d77ebec
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1054e9154381729e7108a867ae45d93e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_823d3b3dd178dcdda7be23c113aded67
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69d61af3deac8e53ad951d8b500bda3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b93154984e30987e3e9367bdc4e92bb7
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e164021bec1f30166ac86f246a48f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3238a44c2ef9eeb2442c230be8d5637a
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_504e39eae5fa8d0007755f3cb1c53df7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a44e9cd3fd8434394cd08560134c37bc
    def get_inputs(self):
        return [
            paddle.uniform([43, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_876ecedb2af250a98b3f963cc85e29c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b646590518565690407c8d44b193ebf9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c695f5cd1cac8d0679add5e66c93919e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b646590518565690407c8d44b193ebf9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c2fa842e21bcaf49985b99d689c31004(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_595ee9a66526db6f080803bacaf2af70
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dfcab448911a63f3bbbf26f60c613315(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1444], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad3b57f04004b09c755182e45bf69ec8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1444], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c67d616e673bcaf021d3821df2105a7c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 116, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3968616ba85ad02dde70bc0bb67e2f79(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c67d616e673bcaf021d3821df2105a7c
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 116, 32, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_55073f96d31f12ffd26fb15b8614d9f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b1ae040e1999008dd4bdcadb474976dd
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_35f69d5078911e7c0b9fc96f8e90d657(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_41626a0619b53cfa4728ab3780207f7b
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_23de91d8989ad976032a455dd7fc4276(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ce6036c3c1c4e0c7f32434aa0183b01f
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e0bdedf8d09cc9e148e49fc8efcb40e1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_84f56aec61b3d19a2926e13590981d93
    def get_inputs(self):
        return [
            paddle.uniform([11, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f13fe3b3915adef4c47122b4ac10294(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_934b33e878f93249dc1c5457c5c4a7b0
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1886171726bf646f37c3344a4421d38f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1764], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b5937999c8b1dac970097c67ee42e6c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1764], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_54db0b64d153e50130196a3e4b7d662f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[11, 192, 784], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b6a7219f6045dc7533e222c6e384b977(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_54db0b64d153e50130196a3e4b7d662f
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_914c53ff07e472aee3975a04dbc0e004(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14880c768b9e3fe6e1e5a717ec67c28a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 144], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8fab7a645795661fb39989bde9657e4b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 16384, 2, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_366e8e459892532218cd949b32ad5f55(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8fab7a645795661fb39989bde9657e4b
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 2, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_e69634108fd1b2e6457385b1b0fd57d4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 16384, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fbd69eb0341e2a7184dd37d9de9a2d91(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_e69634108fd1b2e6457385b1b0fd57d4
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_970cd9035568c7188a0192de562552d6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_05aef4de2780226f44a51d6c4c26253b
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 1024], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8a2b6333316b7f6958ef45a05265f33c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, None, 2, 2, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_12f3042507d01c438fb5c2440bfca15d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8a2b6333316b7f6958ef45a05265f33c
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 2, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2f0bb06c3fb4127348b781fbb00cf17f(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, None, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a55d2a6b411db64d0cd8213cd151021(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2f0bb06c3fb4127348b781fbb00cf17f
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 1024, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d01c68410d309006619a5d8329efce95(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 16384, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8f4a6ccf1d127c31b6318ac3bd424a69(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d01c68410d309006619a5d8329efce95
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16384, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_0b4b5735eef25006824f1bc74c7a56b1(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 8192, 2, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_25ee300a63848dba654c94c5ed8a2be1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_0b4b5735eef25006824f1bc74c7a56b1
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 2, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f51255d13acf25f18ed605a1cf9c2b96(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 8192, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_622f5632b4b981ad70078ae605641c27(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f51255d13acf25f18ed605a1cf9c2b96
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7c34f7531be7cf1c4b2ff6e6782b9c0f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_05aef4de2780226f44a51d6c4c26253b
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bdeac065afd5689152d933913c180fa1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8a2b6333316b7f6958ef45a05265f33c
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f0bed47737490cdb2922ce1b53b98c45(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2f0bb06c3fb4127348b781fbb00cf17f
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 512, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_490643863c6c8b2348878f2f7711b452(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 2, 8192, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_84dcec8e7626600e754ed4cf3d5543fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_490643863c6c8b2348878f2f7711b452
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 8192, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_442a1e5ed10e206719c8656cb5d96883(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 184, 280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7a80e33967d7fc59583c458d85dba18(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 92, 140], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f8147b0fe91d5a60c082212eecf38664(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 46, 70], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6a08ec0d8642a3e07008d85ddbe53c1b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 23, 35], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bacaea89bd9bbb88e55163c263a2d99(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d9ce7cf3d5140c5bf46eaa7a5ccc98d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 184, 280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_424c69e35e54e90dee8ac43492ad148a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 92, 140], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff2e6dd9c75cab3a4cbc7baa9b31a24b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 46, 70], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1a7a6c52c45350469a98c9ee35ae19e6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 23, 35], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd0188595e24677f2cea874688855467(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 12, 18], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_339e7845a42b44af29a124b43c493b56(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, 320], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98a17921ce08ea6824a1c3bfabc7ae89(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_339e7845a42b44af29a124b43c493b56
    def get_inputs(self):
        return [
            paddle.uniform([4, 16, 64, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9dfdc77118b17c3acfa536ac3a4828ed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([4, 512, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_834f35394c9c68c9b135858d5ad419e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 80, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b1187e7b11048169e51e15dc578c1b5f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_06ecd7ae23a54bcfb183c0cec7a15e05
    def get_inputs(self):
        return [
            paddle.uniform([86, 197, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7745c2fdf4fd3b55529371ab4765e8b7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_77bfb361561ff676b55505f59df8c0e3
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d5080dba7d26ea8a0d62967a1759eeb9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_96e80e6e5d02dd64c9c8a8380ef677a8
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_5d74862a1126900d8a9eff85a04f1978(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 32768, 1, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f3df7d603602f11af6d3b74c907a7a14(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_5d74862a1126900d8a9eff85a04f1978
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 1, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_12fe3f1bb66a6d472fcf8ddc30d07c8e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 32768, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8fce0ff5a681ddbff2acd55dd86c6f23(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_12fe3f1bb66a6d472fcf8ddc30d07c8e
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bdc8d19a4cdb6f02b95a355e3ab838ca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_de1972fec47383d747a019d298c33e88
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6cf790444f2706622bf16770f7008ff3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_23e023d725dc9733d992004aa4c17078
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 1, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6ce45686ca76dbb865c96cf3472dc1a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a13a216b0659e0e24e2cc9b88f6a327c
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 512, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9d48530a5aa399a1a123de606339c543(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, 32768, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a7240ca7a70d9984b8e8d132d130c115(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9d48530a5aa399a1a123de606339c543
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 32768, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e9e5332577035712d75330429811be75(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_63bc694c3d066b8413776bb3e856c18c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_339e7845a42b44af29a124b43c493b56
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 64, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2693f453e34e2ba823bc6048b6463521(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_726fd52e455faf4c50bc388b248c5535
    def get_inputs(self):
        return [
            paddle.uniform([4, 512, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7740067824b5d9208ec1698c09f5ba0f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_af5734e7ec8e39201494c0f8513b0b78
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ecb5b0bccff20cd8c003b3c973820409(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f6a6e513cb7063b1365896af119a9389
    def get_inputs(self):
        return [
            paddle.uniform([1, 3024, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8e0f7b7049b407d17cb8e8ecb2e5560b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 196, 4, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0fd9b4c2100075146c985630d7d2ed3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8e0f7b7049b407d17cb8e8ecb2e5560b
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0fd9b4c2100075146c985630d7d2ed3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8e0f7b7049b407d17cb8e8ecb2e5560b
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_03ce6c302dd06560bb60b770f41aa9d5(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 196, 4, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6f2f6b5f7024a13a4f3ea8dacd9f89b7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_03ce6c302dd06560bb60b770f41aa9d5
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_3e5b4a97e3a298a5776da5021385a28e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 4, 196, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_29d156670c45ad0478158daad235dd4b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3e5b4a97e3a298a5776da5021385a28e
    def get_inputs(self):
        return [
            paddle.uniform([22, 4, 196, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_24f4b4e6a7eddbf7d86269498caca840(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[4, 196], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d9d7fa5d9cd1ac7e3bfa5581101ade9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_24f4b4e6a7eddbf7d86269498caca840
    def get_inputs(self):
        return [
            paddle.uniform([4, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d76b545f3694b60eb3f29dc221352676(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[38416, 4], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_68020fc105488967616dd22e7655d917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d76b545f3694b60eb3f29dc221352676
    def get_inputs(self):
        return [
            paddle.uniform([38416, 4], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8d460508dc0065ff73beb3a7af1279f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 192, 288], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8a7107924a5cd94da7ab33e7e3986c30(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 96, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9d05cba745768e3235faea0aaa2b8506(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 48, 72], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f53ad526c0d670c3eaeb742a218d884b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 24, 36], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bacaea89bd9bbb88e55163c263a2d99(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8beec93246bf7787c856c9cca72a76fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 192, 288], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0ebb8ac68c94cce94692d2480ac1c426(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 96, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1721395bd78e09c2f0bf7365c190c181(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 48, 72], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1ee5e97a93eb2fdc362525a9625921ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 24, 36], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd0188595e24677f2cea874688855467(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 12, 18], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_bec67a8e1ff482a10bb3a976965da2a6(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, 3, 8, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_051da5aca326807841a5008445de8c6d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_bec67a8e1ff482a10bb3a976965da2a6
    def get_inputs(self):
        return [
            paddle.uniform([10, 160, 3, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4da25493fc7dad35bd856ce24097fe6d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_46ad176715e290dc5bebc4d6ce12eae7
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 160, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b599ed8d51de6b9c9a1554b5c6e92098(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d22e85fc35fcfaa17772bf14c7824c
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 160, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd4484a0f0f7838f22ec29e3c9208de0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc95cfaf775b72f80ffbfd10b82b95d0
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8d52869f4b033ce9ce3c4ab177e77225(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[8, 196], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cd33369bba04d28a66a2f7d1a10597af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8d52869f4b033ce9ce3c4ab177e77225
    def get_inputs(self):
        return [
            paddle.uniform([8, 196], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f646bc0a6ecdc3f520f7c18b3949a30c(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[9604, 8], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_42462a55c2e2d4ca7dc0bf68b0500cc8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f646bc0a6ecdc3f520f7c18b3949a30c
    def get_inputs(self):
        return [
            paddle.uniform([9604, 8], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_1b73bfaecb8248b860d8a5888d74c0f7(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 8, 196, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b875f67af78529f12853ad42813bd29d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_1b73bfaecb8248b860d8a5888d74c0f7
    def get_inputs(self):
        return [
            paddle.uniform([22, 8, 196, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_421a0d8abbdd7d9df5a5024c856d1aad(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 16, 12, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_609a7d413a849cf827d04ca0e750276d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_421a0d8abbdd7d9df5a5024c856d1aad
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_609a7d413a849cf827d04ca0e750276d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_421a0d8abbdd7d9df5a5024c856d1aad
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_2e053d0088ff37535a2da5248a489e01(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 16, 12, 32], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a53d7718cea16a5442dfdd51a1ff090a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_2e053d0088ff37535a2da5248a489e01
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_4158f6bb10b2e1cf499cc8a26cf5cf5e(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 12, 16, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7d90c603189f0e377c44c5234e324830(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4158f6bb10b2e1cf499cc8a26cf5cf5e
    def get_inputs(self):
        return [
            paddle.uniform([22, 12, 16, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_8b932de4a499ba755bc240caad9a9da8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[12, 16], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9c03735a8130c55675b94b8118695fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8b932de4a499ba755bc240caad9a9da8
    def get_inputs(self):
        return [
            paddle.uniform([12, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_dea3932acaac1291e7aeaf094f5805c8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 12], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f142e8de1c536c5702d2be7f0d494a0c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_dea3932acaac1291e7aeaf094f5805c8
    def get_inputs(self):
        return [
            paddle.uniform([256, 12], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_88cb818f9d537c5a56b008004700607c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b6a9abf8c13a72ec60662fd066595a16
    def get_inputs(self):
        return [
            paddle.uniform([1, 1174, 3, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5a306bb3b00a08ddc2d96f9b370f5098(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_3cb10a48066efe9c6cba235776656580
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a3fd5651734a36d4b185ca1d325a9291(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_07b9be7cdb7533f06c6f09ab037050cf
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ccb14d1f8e07e9ec44522bf50f34605(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_324cc434c441f67ea0d151a5a666b542
    def get_inputs(self):
        return [
            paddle.uniform([1, 150, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bcc7aef922b8c4e1688241df8290dafe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_8edc26a7650051b32ad323e100bcdf07
    def get_inputs(self):
        return [
            paddle.uniform([4, 16, 32, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fb381c08e76331e58f66b96886eacc24(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4c8d9a66d1e97987f32826b0c707e072
    def get_inputs(self):
        return [
            paddle.uniform([4, 256, 128], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_359381b4e9d234dff22af00cc5b62b62(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, 2, 58, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5355e1d54c02c8e95523b611c9d450a9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_359381b4e9d234dff22af00cc5b62b62
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 58, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b50e0717c863ba8b64df0665d7fbbab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_34b848173fe53222220fe44f65d593dc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_df48dec90544647e126bac3330b5c86c
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d9d9c17a0c43c66e94f6d9058bd2e13e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ee4dd586a7b4b0a4665887f6a28095b0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd68648c5f5b65fa274b79e3f89ef746(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_266419ae99acd4915de197cd6dda793f
    def get_inputs(self):
        return [
            paddle.uniform([1, 1174, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8fcfa11ccfd4776235b41dc128240d05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_4b71d8035b9d029cb6f8f12878a767a2
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f01132e635b27d4aac3b2a2d839ac802(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f23cbbc71fe2c82b59339a7382d24537
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1174, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b8961b82be6b93f1f6cccdcb425b721a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 65536, 1, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bc4a8c445f1c3e92436e350d94e23a0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b8961b82be6b93f1f6cccdcb425b721a
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 1, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f50fb564d2cbfdeb5e3ba8896b651e79(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 65536, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1db6f8fc28766a00f7dc41fd7123de3c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f50fb564d2cbfdeb5e3ba8896b651e79
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_970cd9035568c7188a0192de562552d6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_05aef4de2780226f44a51d6c4c26253b
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_886405b61c432dd6f5f6d30451675fd2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f9c06380b63410f49ee44d8d8984255e
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 1, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0248cd00c3502f8f57a4e559370c8afc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_6f87a8b50c0814038d2ca231913b326b
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024, 64], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_cc46ae5e570930af12552c15c6c00ed8(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[1, 1, 65536, 64], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa4a217abd97ec9cc9c955a96d7f83e2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc46ae5e570930af12552c15c6c00ed8
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 65536, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c750be6a7aaf03c9d3869a0ad4a1ece(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_aa36f9bd8ef7daac2a1b4ce19e0a1255
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_81347f4b532af6ede8dd0e0bb5e56968(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_bec67a8e1ff482a10bb3a976965da2a6
    def get_inputs(self):
        return [
            paddle.uniform([10, 50, 3, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8adc88e48c842a1b6e812388b5dd502(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_46ad176715e290dc5bebc4d6ce12eae7
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 50, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c1c151fb6de34af58f910ad8436360f6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_a4d22e85fc35fcfaa17772bf14c7824c
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 50, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_066b08abfcdcfae9ad33eb3668184176(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[43, 96, 3136], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e054d6ac53219408c4ba12e532e2c63c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_066b08abfcdcfae9ad33eb3668184176
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 3136], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_fd73595919777900f45e1c88193ebf09(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[22, 49, 16, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_001fe52a4383d5db50ddc6a78244b633(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fd73595919777900f45e1c88193ebf09
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 16, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ed75c0e5dbc1bdaa54fcd0d4c8fe730b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_fd73595919777900f45e1c88193ebf09
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 16, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0366d5cf5a8579d105d658a5080856df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a079aa72da31571c4849461dc0ce8e7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ffec176772a36c9210a8cbf250ae03a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 3, 1, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_afe93f8f4d987e280cea9b97d741b1a5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd6c9b163856cfb765b331a1ea47af3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_21a71f58f6e272cbdab2e50fa3b5a8aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 168, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0256548e22d5597f456cac5d22b4ac75(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 84, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c1765d1e3a188ad0c8bf3033290871a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 42, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c33a575e78450dcea4eb6884a9025362(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 21, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d34823c1868bf7b15f51a28a8c4a6a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eaa330b0e95baaaf1d3fa320cf0cafc6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 168, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa9dc6d49fa0e0bfa58e01087e63d9c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 84, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_be05cea208acb8953517976d2550fc4e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 42, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ff94e7a30a48f4189d2f9f4ed8d5755(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 21, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c7564bc27a906d9764c50da365e6fca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_9b446a3d32d2a78c5b8519adc18c5fdd(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[2, 0, 1])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a901d638f5871e6d61109ea6e842b97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b446a3d32d2a78c5b8519adc18c5fdd
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_731fdecb84853c16794f01d115308c9b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 3, 2, 4, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_19a60dc44833867587c8ccd434a696ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[3, 0, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e0fa96ff44b1e5e0efdbec62638cf002(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_c9226b59af181610e9b1836006d34b19(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 1, 2, 4, 3])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ee37a4689bcc0afbabc56a0d82327645(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_846893b369c6b060f2f7dc74d1f7316c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d8d8fdd10781cca5412a4a79958a184f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0b6032462a660d3c505f4a52f233398d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_26ffe0f980149fcfbdff5621f1bb9c50(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([54, 198, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8ea7cfe9a4666def96977f05f60a5adc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_22026f38de0131660fad6c720f6d0c3e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c44547911661d7a56c5c69a160a56b34(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1960, 16, 2, 4, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f401b370338c7b5f55e71bfc3f99326d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1960, 16, 4, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1efb53e30111c09164c2e1e6151625f7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1960, 4, 16, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e3340395d889245435a4214c2b44c930(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2facb38dd0d03cbdc15458925e0695fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6896a4e965454e1e0b95e5f7dd52e3aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a9548a6680373e6665f07efb2f86d48(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f9beb2738caf9a09b0ce6adb97800b7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 128, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a65d0e6df170541af16d3af8eef42d31(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([16, 128, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6fa5ebbf2f1e56f51bb47b4860681c8b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 7056], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4e642486369c571c61fee7545fdd1b3a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 7056], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1ccf38d4870d89b2165f6294d06ee66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2adc7d5b8c1a0f656514c0d23bcb4008(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ebe48a8d51d3ce99181d82ff88d9d3a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1158d3c525eb44d9db15ef83ac825e50(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 3549, 4, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c775f8ac7f857dbf86bb46d49c52c8e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 160, 240], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6031cdcb96d9c59d1d13b43ba2ae4c40(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 80, 120], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1b90318aa09d39d2d84d37481308ae6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 40, 60], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_73dc812e7ea07a1312277756ec863b67(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 20, 30], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b2c9cd202757e7d69347079da819a8a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 10, 15], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f9625db6e94861cfe8a60af0201a829c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 160, 240], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6464e046d1d21a051a55cacaea5c3da3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 80, 120], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a0db9841ed990c5e31edabf3bdc57e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 40, 60], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a3e89703234aa7b1eb9bc6481c19f1b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 20, 30], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2479d1e4e03049e6302413fad943ef97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 10, 15], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eabd4549bb83249c4ae16e54a8ff00be(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4d2ff8608485ac9da4ec57d4b55af0a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3344b421600a528d493b412d8a0615d9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc060bd731a5ebad74d707bb276a514b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ea26d945452a45c1fc3d8c3181e8d057(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0fd009ab0af118c50fd6295e42dc017f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 225], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3415a06bb2974afb762d19b93d55395b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 225], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eee5c50d385dc0d5af42849b3ab98c5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b446a3d32d2a78c5b8519adc18c5fdd
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 49], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 2, 1, 3, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_da701d652bf14d1add1cdbef6499fdbc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8b6d63c5fcb3e42f3b50c57000a51d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58c1e291b103880b9c3c47f212bde2b5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 152, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0be26b5063da18154ab1165d4dc202d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14f7a46d8f86dafed9113ec1c1ab47d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_080d79497ac11e26f3e52b3c85193456(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c5352138780e018f886f8a1a6e722161(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7bfabfb70dc5dd97ccc7837ec7b4b099(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3746c4e3a32026b57dae15546d7eeb7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ed9347a8acdf709ef1a500e157c5bc3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([128, 16, 8, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b309825d0f7d28ae7735589dbd0da975(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([128, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9028952aee01274083a1b0b5fb14d9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eec2a283ee68a502dbcffae6fd9435d7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e74c2d29e02c521623bf696817ee8668(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 21, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9af7eabaf118fee7980218db16940c2b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 120, 216], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_d4a5e243e4027139bce2de01cd27b65b(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 4, 5, 3, 1, 2])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2de745a42c5d2cf7c19e923fa9adb328(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d4a5e243e4027139bce2de01cd27b65b
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 8, 128, 13, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e50aa019280ab376b09b07a481d3e93a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 900], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fac790fa9d305d053b6e5abe4213b62(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 900], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_256d32c94d0f2dfa4996131ca36e82d6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9f31b585566719089cc8fcb7dc8b0b66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_60b11d4d55e273a48d96127e410e71ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de458b006519587b6a688b4668103eee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c872fd870825de1d095569e20a12c308(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d003cb81275111b641c03845b166183(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1db3216c6d5e1c8a1c7c59f9e8ccabed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ebe3ad0f96a7db05932673f8107f44(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5bfc2bd1e491185be471960773b9c411(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f3e137e17c77dc28de4a2434e45c499d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ba3115c9a8905227f8838b1c038d294d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 32768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a821ffb076623e1eff6fad474d5059f1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 19, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1687bd6e8d3c62c0f04710d58fa12f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b46b524178dba13b66315462034e3328(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a9b275894d28ccbf8d3c35662f9f4e4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_278e422d45bd22c2ab804fc95f649818(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 7581, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_62d76956567be7bb16ee0858569fcae7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([528, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_030afefce0f6b2aab689da4bcdf4ae24(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_84d1f83425e2cdb01d02dd8a70e83237(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 5776], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_63d8cafeee0a932664c34b03767dca59(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 5776], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9bc2b219c9e59d88c79d09aa6ef72704(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14b17bb19aa44ed39d05d619deb4a527(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a3f03a7b6c571c87387f478fb31a04fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4e3dc05d2ed9b754a32f7d397687a39d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fca98efa50488688c9d91d2001956fb7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 21, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0ff0bff5fc7a0adb04ee0ded0a28548(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cce8fc7611eaee3ea599c6d30c0fdcfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af2a2bddb2619709b514a2bcf2b1fc67(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([6, 2, 1, 12, 24, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6b31a9af70af9fac540612a933818984(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d2b7d63cda7a341afdf67dee9455452(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([8, 320, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_025d2835e3af970211aeaa0569c2faaf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 4725, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a630d59033d1a7d92ad984eaba029856(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 64, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f16b9c9751f1e3bdd780606174a27d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([8, 160, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae7ce85098821b5ad1bc1ac57791dd55(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 12, 12], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f7284f0d6fe505390ba9fd3694642a9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 577, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7231a4127ec604474bee8a3a356f8f9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 577, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dd7de72d75627bf7584413deea53274e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 577, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_51a00d7e7a4bdb0fc5b743383c48447e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1296], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_752da25c52043e3b8f29cd7ff57dd6b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1296], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_664c072d4d6d7df3cc95b8564d1eb4b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1296], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1f0012256bd8f4eeab4e99633af3669(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([64, 64, 16, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2ce3b6a8675b4ba2fcee8124349f69ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([64, 64, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dbf6057cea88444fd5975d69e8449207(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 197, 2, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_00df62ecb037bf27f6947818e32f1b78(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 197, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b1924fc9ef27acfb418cfa7019951772(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 6, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8803b35b8f849bf042b88c1585785d8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e75f49f8dc4006251992bdb1d90c4e09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([384, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6d6ad1788aa2459ee2ac7dc832eea0d6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 96, 96, 1, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_31263d2807c606c2317e9c16674fa605(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_800ea6fea11ffcfa9ec4c95d1312711f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ab5edbb96248d2f2af999919c81b3152(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fc9b7062f3006c45dbcbba2c1702435(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 2, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ca10b315feb085b597e8f58f41f44ebe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_483aa9f0f71e24d3fdddd3b35918e1f3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cae3ee7034cf7985d56728838e990388(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 2, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_973eb75cc8957d9355315bf36c17ad4e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5ca1e3c8d65e6229b5a27c12e5592342(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16384, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9f31b585566719089cc8fcb7dc8b0b66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_60b11d4d55e273a48d96127e410e71ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de458b006519587b6a688b4668103eee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c872fd870825de1d095569e20a12c308(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_91ddb8b6401809cc365773da738effbd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 64, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f1495376a313fbaf462893f536604b10(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([16, 128, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0d94d716be23e3cf8d63afc367844dd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_528ca8021d1452a9f2b68f21b15a7c08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_49e0bacdfc1a2073305a58f97b9df8c5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2cd4d8aee31294dc0c9b55727a378a51(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_066eb93615fbbcfcef1fa6496642e2f6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_707a22122d5f4f78d8e1f2d116b41c8f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 8400, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08c4b4f73c93d31588338e16673b0f65(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_60bc43fca205100352c40eb4b2275166(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_750087f3ce9640b62dd30dba676b18dc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([8, 32, 64, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_727f14961887bae8d692bcb004697bc2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([8, 160, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e0c375657a7bb82f88c57a15820d9bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1c11e2158fffb8b31316f9f631e30681(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 3549, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_682b9cca9ce2ef0dddb70475cd390705(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 768, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e8c726be48c119e42beb6d69be49ef9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 60800], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9c5591691f599706cadb95ecbc72268(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 60800, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e8c726be48c119e42beb6d69be49ef9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 60800], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0b1b8705e4004ed4576e13d3d82b46ce(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 640, 3, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_74d797fd84b488aca967d1bb60fca8eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 640, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d032dbe195ec42143e2097e7d0047bad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 640, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_138c2e067c5cb334c4282b9e221d7821(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_95a7bcbd9fad200095db249f31161eb0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([86, 198, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c70f0b028f1f9ff895503f31e5f2ba4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d94b2a6afbeaa6c04c4113832a9f72d7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 198, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_787aab3956d00ca4fd43ab4a7daf37f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d6b4c42f28df1866dba7f46b9a07f66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1f6cc568fef2a651f31c27a2c4930bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99264210f8c7110a3c948174bda9f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_65cda3d05e2eb317add68fc8c267a2cf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6308e41260bf1afd7bc7637f0aefd9dd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e2ad7606d1482fe3465463fe17530b20(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_44b2f3c154eb240ebea1ba087e5f448b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([20, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e038245e26338d2991b193477b851768(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([10, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ad41dbbc60522340811e5c05b790ac89(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_801696087e946b4ef6746f2fbe604ed0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc114a2f0e10ebab5b4c78481ffea821(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b3e9b272debfcad5e2afa807e952e9e3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_89f53da819e864af27df9f6346205eb0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c72c70fa0ea3a59047e03ff254bb75e4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([4312, 16, 2, 4, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ba4c14e2845eb1a5c618e36465ce9ae9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([4312, 16, 4, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fbb47b5beb8b4b621fdb052c3687d43(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([4312, 4, 16, 6], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ea26d945452a45c1fc3d8c3181e8d057(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9755472a5b5e5f56d1394ed5485af3e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 441], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b56a4f14086fcde4e379d3c9e8abd10a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 441], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1ccf38d4870d89b2165f6294d06ee66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2adc7d5b8c1a0f656514c0d23bcb4008(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ebe48a8d51d3ce99181d82ff88d9d3a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b46b524178dba13b66315462034e3328(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_750a7397303685aab8eb1a45eebd05fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4626a7a1c31b607a81bcb49a779d43bb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1156], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af3595a782cb6f33592eb4318c037aa6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 1280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c92b9cc84d8325c88e305e93b0406784(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1280, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_690e6c50ab7d510bbae209aad6687f5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6f3355a28a634ab1f1dd6832ca05f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_112d8037f5cc54896aca83ed029c201c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfcbd3069c07c78bf3fd8215965fad7e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d34823c1868bf7b15f51a28a8c4a6a63(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9850ec0f15bdd7c0958c5eb003ebe781(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_503afc8cd94a0246146ea0197ec9f78f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae4723b4fca9c8becea26ffeeb1cdaf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e110a6be5c50fcc502a375d86f66df88(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c7564bc27a906d9764c50da365e6fca(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8013bc35dc6814ddb046d017d334de89(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 65536], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_365556e52fc01ff899dc7905b52f4b7d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([576, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8065808aa6dca86fbab60f436adda58c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([6, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1cfe6c14e1c8dc9a012d6f104f53361c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b79fa1ad3893a5c6ef3bf350f60446e3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1cb9881a2c95dcf1b5b949cd1bb9f49e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 324], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1c283a2a9d7a0ee2bfb9eccbba5bec92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 19, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1604523a4c102d23b9e1315d763f4540(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_695bf2e9a733ac7ee577cc96421660c6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa2fa83760c8ae241d9a81223bf08296(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3ee90180322654d3e3289796752e6bed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([6, 96, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fbd7e170e083c7d2f549eb5f30be19cd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff2a5f53bcd5fd31e632efa1ada6fd59(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8109374442dd4c89a607307e9186f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([96, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_96c28b9dccfb20d78185b3bec4073d22(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6cdc3aceebbbfa2ea2dea2b6b4270c92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([12, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af2a2bddb2619709b514a2bcf2b1fc67(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([6, 2, 1, 12, 24, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8710259d96317f0ae6ff73615e810f6f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d406b4a1b6cfc11d94bd632c7567eeb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_36059c92072a61f8353346c765cc44f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d600eaab98addbe7dfb913fe08289cc1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f937869ac973f38967907fe5d117d1d2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_293b23ee51ea6f2988d61c7c976aeef8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6303398552bbe18875a2652eb3b8c88c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([6, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0fe19bd802505e7309807dab01aa66b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([6, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9028952aee01274083a1b0b5fb14d9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1ff8a2eb3b3ce1ffb7da9c95bfca8d3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_801696087e946b4ef6746f2fbe604ed0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1671bcb82b0dc09f45b3b963dc63f446(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5bfa725338c5a7df12049cd9d9d682(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_757492ab8af5e1d028cf42efba19f3b1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_caf9802c0dac815d5119e78c5392aa92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dd8939275f794301715db95603734ba0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([960, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7ce73f5f393bcb8bfdf89ad00b41941b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([10, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_846893b369c6b060f2f7dc74d1f7316c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d8d8fdd10781cca5412a4a79958a184f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0b6032462a660d3c505f4a52f233398d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 100, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_273f7178444dc7e50ed60ca7a49c1bfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 38, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cff756e16f6f6e2332be7a838a9361b3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 38, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7370329d4b58190f70b6b077212f3085(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 19, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a7b92be9eed63bb70e8f1708e327e141(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 19, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8884171028a10bcb0748f3f0ba55e9fe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 10, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_42896d8d4e190c4fb45786eb9a248bff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 10, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_03ffe5edf8aaf73103afa856c333d06f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 24, 5, 5], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2f376c7800f2882fefcaa1fdddb32739(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 126, 5, 5], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fa93f488ffecc65e0269e08e1f187926(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 3, 3], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3183af3935dd0041957c5c244cc2535e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 3, 3], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b9226c2615e0fca9065aaf489f7397a9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.to_tensor([[[[15.76220989227295]], [[15.502686500549316]], [[15.361867904663086]], [[14.869795799255371]], [[15.781167984008789]], [[15.610716819763184]], [[15.02834701538086]], [[16.097217559814453]], [[13.993327140808105]], [[16.281068801879883]], [[14.921567916870117]], [[15.6120023727417]], [[14.636691093444824]], [[14.480208396911621]], [[15.682112693786621]], [[14.734054565429688]]]], dtype='float32').reshape([1, 16, 1, 1]),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14de3af477a52399c60bde29e8936f52(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 84, 1, 1], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_950f5af402a5681c12ca729bd171d2a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([2112, 2, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a10e6efe16a2bf74cb2c6935ca4498e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([22, 96, 1, 1, 96, 48], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e0f8ac5cefa307764fffdf85f81e820(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 36, 28, 50], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8d187174ecadba344923598fb52a4aa1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 4116, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1604523a4c102d23b9e1315d763f4540(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6b6677f6379326bbdc280c5764ab2c72(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 289], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c7e6302f1f12791c2bad0fce36c3877(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c7e6302f1f12791c2bad0fce36c3877(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_34ba42ae1c061bd1b7610ecb8f32d080(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_62c40c88be9a41ef4957d28cd677c5a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 8, 49, 16], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[1, 0])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f8d24d95a7881c04b8d60d8c67567632(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([8, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_37db857f3a4314afe6f53e0dbaabab64(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([2401, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_297d36080670ba73bc50183c480b1619(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1b5af932a58d61a6ad793cff26ca9a95(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_491ff8dc8d37cde9e7714d2840ebdfa4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae7579917425b417ba02c6679c823814(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 6069, 4, 17], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_b1ed8385bbc2163f7bdd6c14b49a2160(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 5, 1, 2, 4])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2a7fde174b41bee1f3ce4832e93f53ab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b1ed8385bbc2163f7bdd6c14b49a2160
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 4, 8, 16, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_31263d2807c606c2317e9c16674fa605(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_800ea6fea11ffcfa9ec4c95d1312711f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ab5edbb96248d2f2af999919c81b3152(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bd674a8ef6a4bfcc3468bca5090ce40a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b1ed8385bbc2163f7bdd6c14b49a2160
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 52, 8, 202, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_02880075520ff5c446472fa493faebfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 200, 304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de530fef89bfc4db9479c9a55df79136(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 100, 152], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0db94e5e135f8fbe39a24415e0b61ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 50, 76], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d0d686d558ccd02207c16281452eeafc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 25, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d322efe3d83b0c933fce87a8d4722ea(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 13, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_29276cad74c19c0e8443782104248c5e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 200, 304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_10388455c18f3271cf7b17093149f483(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 100, 152], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7fdc643a435465797c8fe3e3acd38f49(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 50, 76], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_61f4f36458c3370d2c27392b72d3674b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 25, 38], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d6707d9bb1056d2fd84ecc542af59707(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 13, 19], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c34b36f98eab494e458543c35917141e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 2116], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_269b46089b521eeaac03f5e7a4a9e360(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2116], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0366d5cf5a8579d105d658a5080856df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7306ed8071e4e5873f98e2f2c3f8d3ba(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1025, 3, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_efe68967c62b6fe2c7237cb710aaa27e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f2a4efc310110a45c5af587cda47d986(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d377a1f15dbbf534789c1e0a627242b0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_765597cc8fdbd67a9d669cffabed0fe5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd98eaf45e6a867ad40acbf7252fdc94(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de7ade5c0f046479f20e37ee3054c3a2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_52b6b342b9e1ca3a4eea42b47d8967fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bac9b0a384a4539b802d822ae17ec8d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3b570bbac506c5b27c12528ec8868e75(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f64e4694bbbbdd2c9facb30f6a25c1b8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 64, 150], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b4141d70d7cdba7c411d24d8c0aa2352(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_69d3982073f75b91251d56745a8d6786(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 136, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a38e338e7d64c4f737f26426ba008fc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 68, 80], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_016fc0cd3b0b1333a4eedd66cb223cf4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 34, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_808de5ecd5518df1af140ffa30d3e111(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 17, 20], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_87ab1fadc64bd8616cb7b001177e3c22(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 9, 10], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_18881b5831c91ec01eec97cdb6adcf70(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 136, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9ca5d97da7d26a2b7897cbaf8c2f224d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 68, 80], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fcfc26e57cf3f24d56125e887a4233f3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 34, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e2d896bb780bc94b8785baf5d6157d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 17, 20], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_70fc792b31784fb3986b8d5eeceb701d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 9, 10], dtype='float32', min=0, max=0.5),
        ]



class PrimitiveOp_f8a7f00dbc88aa77b50c1809d039798a(InstanceTrait, paddle.nn.Layer):
    
    def __init__(self):
        super().__init__()

    def forward(self, arg_0):
        input_0 = arg_0
        return paddle.transpose(input_0, perm=[0, 3, 1, 4, 2, 5])

    def get_input_spec(self):
        return [
            paddle.static.InputSpec(shape=[None, None, None, None, None, None], dtype='float32'),
        ]
        
    instance_ = None
    static_instance_with_cinn_ = None
    static_instance_without_cinn_ = None


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07ffc65b0cc065c9e03d4aa2dd79c07a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f8a7f00dbc88aa77b50c1809d039798a
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16, 512, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e5063f3743885cbde9596be8ae7773a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4f631ab42397b41df8ff1e6dcbf3c518(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 256, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0366d5cf5a8579d105d658a5080856df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b769144f207275cbf7c236383477b023(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_f8a7f00dbc88aa77b50c1809d039798a
    def get_inputs(self):
        return [
            paddle.uniform([1, 13, 13, 512, 8, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bdcf7bc3f51beaba7d9ce8b62e2e9d1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_72fc5c0fc5b0df91bcf1a1c5c4d0a91d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 5, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_26a04376597cb33aacb75d237a333c05(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e7c536a77c6f3ec1bb9cfa9f2265937(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 160, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_05ef0a56e28efb89768e6e9756a041d9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 5, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_922ce11fab8f5673c63328a0808f270b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5bd2a3fffaac7cdedebc6cdfaf63e081(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 2048, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dfb732599f340bf7c3c0f4f19b924162(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d6db151b2628f69a5fbf31a0525c0286(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_50c2338251ecd99f977de565eee50296(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f67a1ecf5ad129e85b0a3e9aa212869(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_47ba02f72d9417d513b4d424003e76eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1fa2f6a881ec79daba536438ea6522f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6bc8ff0609a37c2ebe902607ba7c8f97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 3600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_660f61ed4de0b67001740adde8f3b2cc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_47beaec7bdf51be22519136edec0f368(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([16, 32, 64, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_09253ffed5a114a1bb7d3185fb582ca6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([16, 64, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_818f318b957e77396810444653b8b005(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 200, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0835941dc79fcf7928933a821ed41dfd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 128, 100], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a079aa72da31571c4849461dc0ce8e7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ffec176772a36c9210a8cbf250ae03a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_afe93f8f4d987e280cea9b97d741b1a5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd6c9b163856cfb765b331a1ea47af3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b69d6b7fc05f754249c7d84ba454ed5e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_293b23ee51ea6f2988d61c7c976aeef8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_10b3bb8b33416045a037de13c4a201ed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6d9762ffa2c8e6af108e53cb3433709(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1a0b22e75714849594d931407010a9d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc615154398d6b8db428f84964972187(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 76, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a6be2eee7d2bf5a9c2b85bd9a664cbde(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 232, 16, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc114a2f0e10ebab5b4c78481ffea821(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b3e9b272debfcad5e2afa807e952e9e3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_89f53da819e864af27df9f6346205eb0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_74aead03635ff239d24c1c01e31385be(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([54, 197, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e923c679130ebfd9028bde93a0090b48(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a4ed2eaf0b797a801cf5a10fa1243c54(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([54, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_977b9e7f388b14a25a204685ec92094b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d51485eefb259096387536404de9416b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 32768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ece661dda2d423f143a136d921b106ce(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 1, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0068c9b590387385d5e832d3e963cb13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_05ea13ff2d7b1d90d3687f8846bbed08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1694645a4199276099d963178fa28119(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 1, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c0448f42c6c1b66f587763ee604c7ee0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_32dfbbfb9604251c54e5e7cda6741b12(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 65536, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a901d638f5871e6d61109ea6e842b97(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b446a3d32d2a78c5b8519adc18c5fdd
    def get_inputs(self):
        return [
            paddle.uniform([300, 256, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_706fb2fa636c211c456609ff7fc40039(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 640, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_756935fe2663014e8fe69ce37c7e045e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 128, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_47ba02f72d9417d513b4d424003e76eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e13f77905e0af807837b61ac41dcb69c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4c1bba9a443f75a5c46ce7d256bb68c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 6400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5805c260567b80b1f469ac577159e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0d94d716be23e3cf8d63afc367844dd1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 169], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98aeb06c3a727e64725d6237e1cba864(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bbee4eea118e541c2510f05ec92bb863(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2264ed632825bbc12108f4752c6f5c13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 529], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3fd8dd0b81b888e192babadcea87ea20(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 529], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9bc2b219c9e59d88c79d09aa6ef72704(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 7, 4, 7, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_14b17bb19aa44ed39d05d619deb4a527(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 49, 3, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a3f03a7b6c571c87387f478fb31a04fb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 16, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9028952aee01274083a1b0b5fb14d9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aeb445a9954f15e75cc3a00d9130d3cf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([8, 16, 32, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b3d6f541dc9f8a0108a27e48e570690(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([8, 256, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0ebb3f78c5b55371eaa40f1c4ddc70f0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([8, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_117ebeaac653006298d6a750f04fe0d3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1687bd6e8d3c62c0f04710d58fa12f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1687bd6e8d3c62c0f04710d58fa12f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_787aab3956d00ca4fd43ab4a7daf37f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0c6fa3f4304ad032c073a6f3f25264ff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2e9c7521e0e2fab0588b8a04b60040db(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c846123ce04f3160f271906335e74d96(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 72, 14, 25], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1f6cc568fef2a651f31c27a2c4930bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_697541a5b2e8ae3868c2b1135a4f78ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99264210f8c7110a3c948174bda9f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_65cda3d05e2eb317add68fc8c267a2cf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6308e41260bf1afd7bc7637f0aefd9dd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eb0a7b9455bfb674a91917e66d968b24(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1565009029963a575d2c9011e4dc3268(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d4a5e243e4027139bce2de01cd27b65b
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 8, 128, 4, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_12cd910781dfb633434929cc6ab51b22(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cf8dfcc9b1bdcefbfd6d64600997831d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 96, 40], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d003cb81275111b641c03845b166183(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 320, 3, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1db3216c6d5e1c8a1c7c59f9e8ccabed(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ebe3ad0f96a7db05932673f8107f44(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 4, 320, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6bb7a7923b000f8c70804bcf56ca10d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 361], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_163a1e3b18599c44235d09fc257f0531(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 361], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e4169d14daa56aada94e4aafd8884d7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0366d5cf5a8579d105d658a5080856df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_396c6824bdbc60590d355ee2aac5a1dd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 1, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b82cee7b9cd54de3244e81cf32f1d915(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d6df6c81a1146148a30d19b23680ba4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_676297617f149baa72bf92beea1f763e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 1, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e57b8d3bb2fe2357377ff64ad3bdca3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_77d3a63c026ccd9a33b1ce4484ebdb0a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 32768, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_52b6b342b9e1ca3a4eea42b47d8967fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bac9b0a384a4539b802d822ae17ec8d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3b570bbac506c5b27c12528ec8868e75(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f64e4694bbbbdd2c9facb30f6a25c1b8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 16, 64, 150], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b340498713a234d122a45814bd46dab2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7f831642782c5eadd9f6961fa442279c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_00c7425bf966be9f0dd10b04700af1bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1ba1e6b6f2e0160e409594b2cbbe1be0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 200, 3, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e4053b4d7f09533cab055cb119dcef1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 200, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d3d49352341f3939195c10b456c87740(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 2, 200, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3e76b9229318356a6ffa5002cbdf8c4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 9261, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f71edd35de213ce3bdee0e3cb26782b4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 16, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a305e7d6fe485854cdcabe5be7d1c8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([16, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08f33db5df4ccf9a54ccf61b150244f8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([784, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ac3dce6b0facfa2fd094d52993200d12(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 49, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bfb4d11326c0cd3b1fd4a9876d8b722(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_549e892a8d6d03d548a0d7eb98ecc14c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([22, 197, 2, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3ea899e92e694066db71cee80cea9896(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 197, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a1cb9c1e5686c05d9d040d7d0f41612e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 6, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bd36d775c87740aa089dbd5a390aeb61(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 100, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_949ce3d9a89ce91d0e68ce8d9c1ec30f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 256, 50], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_87cedc242897514ca2acdff8380ab465(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 21760], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6d0ef060bab9b373f39627ab2fe053ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 21760, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_87cedc242897514ca2acdff8380ab465(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 96, 21760], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0776438211dba298985d7c0be9994f85(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([240, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aa3841b7b4eb8302c77cdcc55a2ff913(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([10, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6c9adb44198add626d809097f415ab29(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([4, 32, 144, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0320b54c3e2241c60e00f78849cffc1c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([4, 1, 1, 12, 12, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5254c11e4fd89b67f9b86fc98eea67bf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 136, 208], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e872107e80a992a0f38f6745064eca9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 68, 104], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_391d19412ec5743feee7c309801ddbf9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 34, 52], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9d93422258f9bd4c48b4b11f0389f353(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 17, 26], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c921d2496aea4b2da87a626a2d258514(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 9, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d46f2c6370746657ffe05a8dcbf3146(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 136, 208], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4118154386827b5ffb24af85cc418f3a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 68, 104], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff0c62ac37be427f3d613e62bebaf75d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 34, 52], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b91aa25909b730e8fcb9713b4e58785(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 17, 26], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c0bd8de44868d07b09f8d21cfeaf336a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 9, 13], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d130a8427e0f2e481ec0095c47af3b9c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bbee4eea118e541c2510f05ec92bb863(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 676], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8b8b297b04afc1c33a1e1cb57c8b7940(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aea85f583a9d10edbd7a5a4feaf8fbb2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e7add5ef06babae4cf40df9641aab25(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b50e0717c863ba8b64df0665d7fbbab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cffb2e69fc5074ce0a7bacb65351b2ba(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9ef0a7edebbfc755b9d1b047c79598c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_580fda8e141c6180066264cecbe8957c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 2, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b09e77bbb8a840fa8d9e7d8feaba1379(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_27723770060940ad8932759058be88f1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7d511b876ec63a7a70271d2c2e1089e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 2, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bbf4703d015d6f56487795edcd59b9b2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7c69193d65820262858cfd049a4d672(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 8192, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_221ae0612fdfca651d1dc12c351daec8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1406baa55d2967e0451f351461d4a0a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9862d29afaaca3fb715454df95d643f4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 320, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_526db5d65d6b94a805a1036a8cf9a2fc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9bde20a1725f7312d66495888aa3b1e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f038d25e4435c160ae0752249c9a5785(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 2048, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a642635f768b449eb440cb9ffa2f001b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5d6b4c42f28df1866dba7f46b9a07f66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1600], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7e98d52e59bda2b4ebfdac86d80826f9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0f9401ddfd09693160cd8c69f6e181ac(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f16074b258dd78805070baa16a1e9082(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 5184], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_30d38fdd888cca3e94e205e410eac837(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 2100, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_97c0d046ce39e8a62639efd12a2f66a3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 8192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_631d012a9b8032c129b546769fc0a702(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 8192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c2b1bea7cd88e5ba26b8e8386fcb8a4e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_784e52ecfd5f6701414bc33812f701c7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 12, 12], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_07d06f24b797be36eea0a6cd3cdc2002(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 100], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6e5840f85161c124828e337fd638c3e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 100], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d671f7aa08bb825693186ac32436b7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4fe49310037db3dc2405cbb59ccc70b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_957088e6660cd4170c6a752c7e282d5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bfb4d11326c0cd3b1fd4a9876d8b722(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_98aeb06c3a727e64725d6237e1cba864(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8e080074720385d6462f8a25c66f121f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([4, 96, 9216], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99e5382675822682b95624be29685367(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_60bc43fca205100352c40eb4b2275166(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_889fb08e5d4012aa7235234f11566b66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bbe12bffffe5548f8155b28300eec6a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a48beee8b52330801a332afa0add8bdf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1d671f7aa08bb825693186ac32436b7f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 7, 1, 7, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4fe49310037db3dc2405cbb59ccc70b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 49, 3, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_957088e6660cd4170c6a752c7e282d5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 1, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_af5663cc61646a61d8a6ee7724950ee7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1025, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_54553a7c9fa9b438f56b6ea295a6fe4b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfe0d35a891b0bb385b66cb79d1b5d39(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1025, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_501f0ddce66aae5705f63989268c5f76(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_58207c09adc795f9a9760434b50adae9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([44, 8, 288, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b600ac68d2e63ec7bf58fbf79dbbee5a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([22, 1, 2, 24, 12, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_889fb08e5d4012aa7235234f11566b66(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2bbe12bffffe5548f8155b28300eec6a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a48beee8b52330801a332afa0add8bdf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1f8b6342d6a4c27eda80963f00b3e92f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dc060bd731a5ebad74d707bb276a514b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 576], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9136d65bb67acb86db72bf5d3ecd9c7e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_da701d652bf14d1add1cdbef6499fdbc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8b6d63c5fcb3e42f3b50c57000a51d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0313917cd04ca6ae54b49b60b1953406(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 80, 32, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5f5219dc57c7bada0701a431326ab0ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 160, 16, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_690e6c50ab7d510bbae209aad6687f5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c6f3355a28a634ab1f1dd6832ca05f4a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_112d8037f5cc54896aca83ed029c201c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfcbd3069c07c78bf3fd8215965fad7e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b979dc76395563cee64433b78216b8a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9850ec0f15bdd7c0958c5eb003ebe781(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 264], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_503afc8cd94a0246146ea0197ec9f78f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 132], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ae4723b4fca9c8becea26ffeeb1cdaf0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 66], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e110a6be5c50fcc502a375d86f66df88(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 33], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7b2bc73c438889a959f641fa9037d31b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eee5c50d385dc0d5af42849b3ab98c5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_9b446a3d32d2a78c5b8519adc18c5fdd
    def get_inputs(self):
        return [
            paddle.uniform([100, 256, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd4edefac67fdead3b830b20fee90e7d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1b5af932a58d61a6ad793cff26ca9a95(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cab1c8604fa1bafcd1d36226b3af3369(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_929de013b46cfd40334324824492f749(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ec45061537311de25298f4ed77cf45ec(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9d1075092e661fb1edc3fa24934c0319(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1caeb641f93e6a7952367260ed079acd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 11109, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_19a60dc44833867587c8ccd434a696ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([11, 8, 7, 8, 7, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e0fa96ff44b1e5e0efdbec62638cf002(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 49, 3, 3, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ee37a4689bcc0afbabc56a0d82327645(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([11, 64, 3, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bdd369432ef7f93bb7d63f980f47a836(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 2048, 1280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_560e1b88e64b3af65bac761ce44aaccf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1280, 2048], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e0c375657a7bb82f88c57a15820d9bc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 768], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_501f0ddce66aae5705f63989268c5f76(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 768, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8b8b297b04afc1c33a1e1cb57c8b7940(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([43, 2, 7, 2, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_aea85f583a9d10edbd7a5a4feaf8fbb2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d5f45e5fd172b4f62e0668fbc64b20f4
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 49, 3, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1e7add5ef06babae4cf40df9641aab25(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_c9226b59af181610e9b1836006d34b19
    def get_inputs(self):
        return [
            paddle.uniform([43, 4, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0147cc3d81d40153fa1cd769b648dbd3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_256d32c94d0f2dfa4996131ca36e82d6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 2704], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6a9d8a2c489824c7ce76a520288fa83b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 11, 7, 7, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_528ca8021d1452a9f2b68f21b15a7c08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_49e0bacdfc1a2073305a58f97b9df8c5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 24, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2cd4d8aee31294dc0c9b55727a378a51(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 24, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ce6a19c3ab146ed6baccb93edb67f0c2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([10, 192, 25], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08c4b4f73c93d31588338e16673b0f65(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1bf3b4d147b905e69ee458ad013cd5ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_384148a9d2a926f1c0edf6cc736b8a77(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 400], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fdc2b05450cb9c5b8ffeb3f3c208ab3b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 8464], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5659e87f55a612d52dfbc5b053d02361(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 8464], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_50dfd2df778706fc91c61e93558397ad(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([144, 4, 96, 24], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4049ab3c9334b8be11e9641ad1bb6a56(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_731fdecb84853c16794f01d115308c9b
    def get_inputs(self):
        return [
            paddle.uniform([6, 1, 24, 48, 2, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_339263095a9fdae3bf16b8dd8453e2d7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5608cc80269be9caa9722904b386619b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d8b242b96e030a80102d14c5e579eb09(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 320, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_459c5c4db0a169becd27f2b51d6b1d74(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 5, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_360cfe6a0974edc7bbccad6de920b214(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3d6fa4b8c9cded98d52a165259d8ed08(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64d8cbc41470318e159d35587c404d02(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 200, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2d39824d87bccab89160ae753830f5ff(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 100, 136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a367b594c15596718f46a45e3ffc3990(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 50, 68], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3dc4209970408bd310f5b7f3430536fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 25, 34], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_64963df5e0509b93030222c2ec56d7e6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 13, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f2f5f80aa7a341d16d3cc55920de7f2f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 200, 272], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0928dd19ba1ed550e919c524e7f1a871(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 100, 136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_788d8c1a2d17c947c568ef525ca282f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 50, 68], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d71016c31d565507880547ea42113b13(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 25, 34], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5900804fce5225c2cdad9d6f1cdf7b42(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 13, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4943a4751a6ee67da3c1785db1e745a8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 5, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de8b69e6cbadfb5b8c41c889114d520d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4096, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7e6fa9001c965cd39efe8f47605aa4eb(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 160, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5b869b1f6c570174cac24fcd050bed26(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 5, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_215fd199ac1147cc605658d41e1ab654(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d13fb41c51d9498a984e827f4d5944e5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 4096, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_de9932f848156458b40a0838a707587f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9fd76f0f4ac1aa3df83faf3a102864e0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d1687bd6e8d3c62c0f04710d58fa12f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 16384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_da701d652bf14d1add1cdbef6499fdbc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 20, 128, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8b6d63c5fcb3e42f3b50c57000a51d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 40, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0313917cd04ca6ae54b49b60b1953406(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 80, 32, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_080d79497ac11e26f3e52b3c85193456(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_602e30801c3c6151366d27b2d6f289af(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c5352138780e018f886f8a1a6e722161(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7bfabfb70dc5dd97ccc7837ec7b4b099(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3746c4e3a32026b57dae15546d7eeb7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5414e17c0806e7c52602b97d06ed6214(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b9e57952b9c4d8e4c4fc3293160e876(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 8, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_feeae0812466cf8d4cbf4f81849d1f98(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7db1fae5d98f3635dcf7ee5a35f2bb1e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8, 512, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_00053e25bac17b1da7049f52e2c5d5c5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 176, 176], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_490f884289833e2d60b572017da20db4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 88, 88], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0696de01cdab1acd51e0c19a1d3fc5b6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 44, 44], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_90df1315eb2b9a3348f9991aa54ad528(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 22, 22], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_99e99710171e5d431e3335b686c2accd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 11, 11], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ab1831d6f3dd67a3f09fcdce90dd1992(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 176, 176], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_68fc9a33d4008ad96e608e2f2bea6b74(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 88, 88], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9dc5e989fc7d0af57fcc6ed2ed84479b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 44, 44], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cd674ad60a55a26ea055cfd452eef54a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 22, 22], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7a5c957d1dcc3408bd4c5d21dd3d9bd2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 11, 11], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eeb7c8f4fa1f88bdd63f0d502593d27f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 15, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_cfa56674d60fbcb21076344fe2e99917(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a9028952aee01274083a1b0b5fb14d9f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 91, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e3340395d889245435a4214c2b44c930(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_39ab98dab3f3f731affa036b5c0dc66f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2facb38dd0d03cbdc15458925e0695fd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6896a4e965454e1e0b95e5f7dd52e3aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([43, 49, 2, 6, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4a9548a6680373e6665f07efb2f86d48(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([43, 6, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_876ecedb2af250a98b3f963cc85e29c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 20, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_41c5cb3da30d807ef4c5f55cbcda0549(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c695f5cd1cac8d0679add5e66c93919e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_41c5cb3da30d807ef4c5f55cbcda0549(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_eb0a7b9455bfb674a91917e66d968b24(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_dfcab448911a63f3bbbf26f60c613315(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1444], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9a13dd390a3d55d9e6829cb74e51ef96(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1444], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_edf547ef2994c5132a80001458b3e1c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 116, 32, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1671bcb82b0dc09f45b3b963dc63f446(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a20236bcd0cc8df922ad9e3b9707be1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 196, 384], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5c5bfa725338c5a7df12049cd9d9d682(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 384, 49], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_757492ab8af5e1d028cf42efba19f3b1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([11, 49, 2, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_caf9802c0dac815d5119e78c5392aa92(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([11, 12, 49, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_297d36080670ba73bc50183c480b1619(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1886171726bf646f37c3344a4421d38f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 1764], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_25259726c5633ee212b85c3db321d1b9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 1764], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2fcddb7fcf017557676838e88122ca7a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 784, 192], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_491ff8dc8d37cde9e7714d2840ebdfa4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 192, 784], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_914c53ff07e472aee3975a04dbc0e004(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7c56dc2d8d8c5b84a943d631ecd51f8c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c9eb33fb5b80c62c2fae73cc678c7b6b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8d1265b2ec8380284dde5b871025513a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 16384, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a975c273ac0ed3a7e11bf37e5588a9e8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2d7c25b0e5e8be2f676732c183eb749d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_635e34b364c8b62c1d928ba3ad2d6821(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 1024, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a2e3cc6b115f300b346a617a6c6db458(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 16384, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_53872466ab75233281027e20424ab324(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6ebfaf64222054101a2f7b41f50698d3(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 8192, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4d6df6c81a1146148a30d19b23680ba4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7bede706d6561fd0639a68f3ede7dc6a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 2, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0522959950d59f56bd7d24ae782db4d4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6f521ac7d2e6d444e0039c2b9d41dfe8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 8192, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_442a1e5ed10e206719c8656cb5d96883(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 184, 280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f7a80e33967d7fc59583c458d85dba18(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 92, 140], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f8147b0fe91d5a60c082212eecf38664(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 46, 70], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6a08ec0d8642a3e07008d85ddbe53c1b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 23, 35], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bacaea89bd9bbb88e55163c263a2d99(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d9ce7cf3d5140c5bf46eaa7a5ccc98d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 184, 280], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_424c69e35e54e90dee8ac43492ad148a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 92, 140], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ff2e6dd9c75cab3a4cbc7baa9b31a24b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 46, 70], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1a7a6c52c45350469a98c9ee35ae19e6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 23, 35], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd0188595e24677f2cea874688855467(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f24a97dab2fcf3a113dc63354904c9ce(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([4, 16, 64, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a0fca28ded3302d7504149fcafceff7d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([4, 512, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_834f35394c9c68c9b135858d5ad419e9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 128, 80, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4020d525ea35a9bdc49c8387b9951148(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([86, 197, 3, 3, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4c4a865d085ab0398fcda0d1e03651d9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e2d64fd766182b1ffc9bd8dd2d6cc48f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([86, 3, 197, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6ecf6a2a5407c94ca17e23d85741b7c1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 1, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b5a05a99fe4bbbf59da6cebe64504711(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32768, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_db83d552e0d3e75b1d3088173168b800(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 32, 512], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d2cb609c863a1ff83ee4f966cfd840fe(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 2, 1, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1c67f9dde45c65df8480bb99ead8e748(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 512, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9f70f48562a3d8bc1a6ad40d85b59d5c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 32768, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_40fdeeb6164e3603dd6a1fdbdded099c(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 512, 4096], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2eb4e39c7491d469e5d4900bdbbaab1f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([4, 8, 64, 320], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f638f07f018164cc45797ff89f0f3588(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([4, 512, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9f51a2cb3d6b4a996baec047fdcdf767(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 5, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_97ca71a8da9bfef32cbc2243a696edfc(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([1, 3024, 4, 17], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2253bfa33ae127449f88f9c46ea30dd4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2253bfa33ae127449f88f9c46ea30dd4(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f9fb27cff9a3eccdbdfb4b97a6eb31db(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 196, 4, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d15446285673193a4651010e34822faf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 4, 196, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6181870dccf4ac615b9556eb0e6295cf(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([4, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_31ea645a6ae6560dfafd201221eaea55(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([38416, 4], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e8d460508dc0065ff73beb3a7af1279f(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 192, 288], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8a7107924a5cd94da7ab33e7e3986c30(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 96, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9d05cba745768e3235faea0aaa2b8506(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 48, 72], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f53ad526c0d670c3eaeb742a218d884b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 24, 36], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8bacaea89bd9bbb88e55163c263a2d99(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 3, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8beec93246bf7787c856c9cca72a76fa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 192, 288], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0ebb8ac68c94cce94692d2480ac1c426(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 96, 144], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1721395bd78e09c2f0bf7365c190c181(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 48, 72], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1ee5e97a93eb2fdc362525a9625921ee(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 24, 36], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_fd0188595e24677f2cea874688855467(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_21944dcf7777da5a9e4b697539aa6b89
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 12, 18], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_0de49986f679f8a824f97bdb15ad17dd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 160, 3, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c88472eaf4b55f143dd7fa431d170afa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 160, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6487d8fd4ef8a7ee1b2f2544acdfea8a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 160, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3c7e6302f1f12791c2bad0fce36c3877(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 8, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4809bd423bd5bbf7616f2b57e30438bd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([8, 196], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c860c45750fcb1c013a6e819569a2bc7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([9604, 8], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_1843897d9ec3b4969400a38499e756aa(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 8, 196, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f235ba5b61ec1caaa3cab8c423a3c0c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f235ba5b61ec1caaa3cab8c423a3c0c9(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9ad8df714a2d161b3bc05b35d926c62e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 16, 12, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3f3fccf769e31554004f53aebb7015f7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([22, 12, 16, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e1f3abde13cfa9b6c07a81210a1f5a1d(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([12, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_187c942e0630057ed6562d5a15d8e460(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_b899a981127d9169ef28c6abeaaa5b15
    def get_inputs(self):
        return [
            paddle.uniform([256, 12], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_2feb39010053311c141aed65d24ca945(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1174, 3, 6, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_c099e101245dc6ba7b35a4afefd1a454(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_94d421db744aa411f8b2a617160a0c3e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 6, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_04b21f99835ed64d8ad54dc945837ed7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 150, 256], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_885684fdaaecfb04ff690dc0fa7b0b4b(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_d91a3baf3f1a954b65b3e865bc511d30
    def get_inputs(self):
        return [
            paddle.uniform([4, 16, 32, 160], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_4b9f46fff63b8b54eba018b34ba70dbd(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([4, 256, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6012e70ac189e734db6470157ed68f6e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_cc85fe0cde1697ba1c3ec1266746bb27
    def get_inputs(self):
        return [
            paddle.uniform([1, 2, 58, 64, 128], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_9b50e0717c863ba8b64df0665d7fbbab(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d4cb2b09bfb2fdedb4c5d0ff6ab07af5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 68, 4624], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_179359dce29343467c55a61c4926a4ae(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 80, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d9d9c17a0c43c66e94f6d9058bd2e13e(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 4, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_ee4dd586a7b4b0a4665887f6a28095b0(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 2304], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_d36882000d6f6893a4bd2a95cb316f5a(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1174, 3, 12, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_08580470bd643a3b52b79f4c1f739657(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_f4edd02cf8add6d176e3e968984b66df(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 12, 1174, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_87ebacb6e31ce7a78f5ce217db59e734(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 1, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_6b864416757171eb785c26e2b5793665(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 65536, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_a975c273ac0ed3a7e11bf37e5588a9e8(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([1, 64, 1024], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_bac69b34cdcf93a2fc3db4c5f78730f2(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([1, 1024, 2, 1, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_8be908955640808030387a9b44e0e6d5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 1024, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_04a2e57f6836faff06c21143805c0999(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([1, 1, 65536, 64], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_3bdcf7bc3f51beaba7d9ce8b62e2e9d1(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([11, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_5013e67429d8ceb216d79a807e4c09f5(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_ca5e1216bb4c2fe00fba042f698efabf
    def get_inputs(self):
        return [
            paddle.uniform([10, 50, 3, 8, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_608f76c9ac8114f0d8aeac750d7a9af7(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_42cf4ea50ad8f44f40d879d166f43783
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 50, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_19721ad1fae49791359f565adb5dc556(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([10, 8, 50, 32], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_7767c47e9530e2684fbefd3071245745(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 3136, 96], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_b4141d70d7cdba7c411d24d8c0aa2352(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_713858deb1aeda9a58531a7bf0bf8cbb
    def get_inputs(self):
        return [
            paddle.uniform([43, 96, 3136], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_e76bcd20a550abd5e8ddb9e1a474e0a6(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 16, 16], dtype='float32', min=0, max=0.5),
        ]


@unittest.skipIf(last_stage_failed, "last stage failed")
class TestPrimitiveOp_55e071f04e117a3ca298b9bae121bb36(CinnTestBase, unittest.TestCase):
    
    def get_test_class(self):
        return PrimitiveOp_74c99010dc852a6b76064274950ee7ff
    def get_inputs(self):
        return [
            paddle.uniform([22, 49, 16, 64], dtype='float32', min=0, max=0.5),
        ]




if __name__ == '__main__':
    unittest.main()