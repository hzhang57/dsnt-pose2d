'''
The code in this file originates from another source.

Source: https://github.com/pytorch/pytorch/blob/master/test/common.py
License: 3-Clause BSD
Changes: Yes
'''

import unittest
import contextlib
from itertools import product
from copy import deepcopy

import torch
import torch.cuda
from torch.autograd import Variable

torch.set_default_tensor_type('torch.DoubleTensor')

SEED = 0

def get_cpu_type(t):
    assert t.__module__ == 'torch.cuda'
    return getattr(torch, t.__class__.__name__)

def get_gpu_type(t):
    assert t.__module__ == 'torch'
    return getattr(torch.cuda, t.__name__)

def to_gpu(obj, type_map={}):
    if torch.is_tensor(obj):
        t = type_map.get(type(obj), get_gpu_type(type(obj)))
        return obj.clone().type(t)
    elif torch.is_storage(obj):
        return obj.new().resize_(obj.size()).copy_(obj)
    elif isinstance(obj, Variable):
        assert obj.is_leaf
        t = type_map.get(type(obj.data), get_gpu_type(type(obj.data)))
        return Variable(obj.data.clone().type(t), requires_grad=obj.requires_grad)
    elif isinstance(obj, list):
        return [to_gpu(o, type_map) for o in obj]
    elif isinstance(obj, tuple):
        return tuple(to_gpu(o, type_map) for o in obj)
    else:
        return deepcopy(obj)

@contextlib.contextmanager
def freeze_rng_state():
    rng_state = torch.get_rng_state()
    if torch.cuda.is_available():
        cuda_rng_state = torch.cuda.get_rng_state()
    yield
    if torch.cuda.is_available():
        torch.cuda.set_rng_state(cuda_rng_state)
    torch.set_rng_state(rng_state)

def iter_indices(tensor):
    if tensor.dim() == 0:
        return range(0)
    if tensor.dim() == 1:
        return range(tensor.size(0))
    return product(*(range(s) for s in tensor.size()))

def is_iterable(obj):
    try:
        iter(obj)
        return True
    except:
        return False

class TestCase(unittest.TestCase):
    precision = 1e-5

    def setUp(self):
        torch.manual_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)

    def assertTensorsSlowEqual(self, x, y, prec=None, message=''):
        max_err = 0
        self.assertEqual(x.size(), y.size())
        for index in iter_indices(x):
            max_err = max(max_err, abs(x[index] - y[index]))
        self.assertLessEqual(max_err, prec, message)

    def safeCoalesce(self, t):
        tc = t.coalesce()

        value_map = {}
        for idx, val in zip(t._indices().t(), t._values()):
            idx_tup = tuple(idx)
            if idx_tup in value_map:
                value_map[idx_tup] += val
            else:
                value_map[idx_tup] = val.clone() if torch.is_tensor(val) else val

        new_indices = sorted(list(value_map.keys()))
        new_values = [value_map[idx] for idx in new_indices]
        if t._values().ndimension() < 2:
            new_values = t._values().new(new_values)
        else:
            new_values = torch.stack(new_values)

        new_indices = t._indices().new(new_indices).t()
        tg = t.new(new_indices, new_values, t.size())

        self.assertEqual(tc._indices(), tg._indices())
        self.assertEqual(tc._values(), tg._values())

        return tg

    def unwrapVariables(self, x, y):
        if isinstance(x, Variable) and isinstance(y, Variable):
            return x.data, y.data
        elif isinstance(x, Variable) or isinstance(y, Variable):
            raise AssertionError("cannot compare {} and {}".format(type(x), type(y)))
        return x, y

    def assertEqual(self, x, y, prec=None, message=''):
        if prec is None:
            prec = self.precision

        x, y = self.unwrapVariables(x, y)

        if torch.is_tensor(x) and torch.is_tensor(y):
            def assertTensorsEqual(a, b):
                super(TestCase, self).assertEqual(a.size(), b.size())
                if a.numel() > 0:
                    b = b.type_as(a)
                    b = b.cuda(device=a.get_device()) if a.is_cuda else b.cpu()
                    # check that NaNs are in the same locations
                    nan_mask = a != a
                    self.assertTrue(torch.equal(nan_mask, b != b))
                    diff = a - b
                    diff[nan_mask] = 0
                    if diff.is_signed():
                        diff = diff.abs()
                    max_err = diff.max()
                    self.assertLessEqual(max_err, prec, message)
            self.assertEqual(x.is_sparse, y.is_sparse, message)
            if x.is_sparse:
                x = self.safeCoalesce(x)
                y = self.safeCoalesce(y)
                assertTensorsEqual(x._indices(), y._indices())
                assertTensorsEqual(x._values(), y._values())
            else:
                assertTensorsEqual(x, y)
        elif type(x) == str and type(y) == str:
            super(TestCase, self).assertEqual(x, y)
        elif type(x) == set and type(y) == set:
            super(TestCase, self).assertEqual(x, y)
        elif is_iterable(x) and is_iterable(y):
            for x_, y_ in zip(x, y):
                self.assertEqual(x_, y_, prec, message)
        else:
            try:
                self.assertLessEqual(abs(x - y), prec, message)
                return
            except:
                pass
            super(TestCase, self).assertEqual(x, y, message)

    def assertNotEqual(self, x, y, prec=None, message=''):
        if prec is None:
            prec = self.precision

        x, y = self.unwrapVariables(x, y)

        if torch.is_tensor(x) and torch.is_tensor(y):
            if x.size() != y.size():
                super(TestCase, self).assertNotEqual(x.size(), y.size())
            self.assertGreater(x.numel(), 0)
            y = y.type_as(x)
            y = y.cuda(device=x.get_device()) if x.is_cuda else y.cpu()
            nan_mask = x != x
            if torch.equal(nan_mask, y != y):
                diff = x - y
                if diff.is_signed():
                    diff = diff.abs()
                diff[nan_mask] = 0
                max_err = diff.max()
                self.assertGreaterEqual(max_err, prec, message)
        elif type(x) == str and type(y) == str:
            super(TestCase, self).assertNotEqual(x, y)
        elif is_iterable(x) and is_iterable(y):
            super(TestCase, self).assertNotEqual(x, y)
        else:
            try:
                self.assertGreaterEqual(abs(x - y), prec, message)
                return
            except:
                pass
            super(TestCase, self).assertNotEqual(x, y, message)

    def assertObjectIn(self, obj, iterable):
        for elem in iterable:
            if id(obj) == id(elem):
                return
        raise AssertionError("object not found in iterable")
