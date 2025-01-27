# Copyright © 2023-2024 Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

from .rules import kernels as triton_kernels
from .tuning_database import KernelTuningDatabase
import io
import shutil
import argparse
import json
from pathlib import Path

SOURCE_PATH = Path(__file__).resolve()
COMPILER = SOURCE_PATH.parent / 'compile.py'

def parse():
    p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--target_gpus", type=str, default=None, nargs='*',
                   help="Ahead of Time (AOT) Compile Architecture. PyTorch is required for autodetection if --targets is missing.")
    p.add_argument("--build_dir", type=str, default='build/', help="build directory")
    p.add_argument("--python", type=str, default=None, help="python binary to run compile.py")
    p.add_argument("--enable_zstd", type=str, default=None, help="Use zstd to compress the compiled kernel")
    # p.add_argument("--autotune_data", type=str, default=None, help="Autotune results generated by tune_flash.py")
    args = p.parse_args()
    # print(args)
    return args

def gen_from_object(args, o : 'ObjectFileDescription', makefile):
    target_fn = f'{o.KERNEL_FAMILY}/gpu_kernel_image.{o.SHIM_KERNEL_NAME}/{o._hsaco_kernel_path.name}'
    print('#', o.human_readable_signature, file=makefile)
    print(target_fn, ':', o.src.absolute(), COMPILER.absolute(), file=makefile)
    cmd  = f'LD_PRELOAD=$(LIBHSA_RUNTIME64) {COMPILER} {o.src.absolute()} --kernel_name {o.entrance} -o {o.obj.absolute()}'
    cmd += f' -g 1,1,1 --num_warps {o.num_warps} --num_stages {o.num_stages} --waves_per_eu {o.waves_per_eu}'
    if o.target_gpu is not None:
        cmd += f" --target '{o.target_gpu}'"
        target_gpu = o.target_gpu
    else:
        target_gpu = 'native'
    cmd += f" --signature '{o.signature}'"
    print('\t', cmd, file=makefile)
    if args.enable_zstd is not None:
        print('\t', f'{args.enable_zstd} -f {o.obj.absolute()}', '\n', file=makefile)
    print('', file=makefile)
    return target_fn

def gen_from_kernel(args, k, build_dir, makefile):
    outpath = build_dir / k.KERNEL_FAMILY / f'gpu_kernel_image.{k.SHIM_KERNEL_NAME}'
    outpath.mkdir(parents=True, exist_ok=True)
    target_all = f'compile_{k.SHIM_KERNEL_NAME}'
    all_targets = []
    object_rules = io.StringIO()
    arches = [None] if args.target_gpus is None else args.target_gpus
    ktd = KernelTuningDatabase(SOURCE_PATH.parent / 'rules', k)
    if True: # Debugging
        if k.SHIM_KERNEL_NAME == 'attn_fwd':
            assert not ktd.empty
    k.set_target_gpus(arches)
    for o in k.gen_all_object_files(outpath, tuned_db=ktd):
        all_targets.append(gen_from_object(args, o, object_rules))
    print(target_all, ': ', end='', file=makefile)
    for t in all_targets:
        print(t, end=' ', file=makefile)
    print('\n\n', file=makefile)
    object_rules.seek(0)
    shutil.copyfileobj(object_rules, makefile)
    return target_all

def main():
    args = parse()
    build_dir = Path(args.build_dir)
    with open(build_dir / 'Makefile.compile', 'w') as f:
        print('LIBHSA_RUNTIME64=/opt/rocm/lib/libhsa-runtime64.so\n', file=f)
        makefile_content = io.StringIO()
        per_kernel_targets = []
        for k in triton_kernels:
            k.set_target_gpus(args.target_gpus)
            per_kernel_targets.append(gen_from_kernel(args, k, build_dir, makefile_content))
        print('all: ', end='', file=f)
        for t in per_kernel_targets:
            print(t, end=' ', file=f)
        print('\n', file=f)
        makefile_content.seek(0)
        shutil.copyfileobj(makefile_content, f)
        print('.PHONY: all ', ' '.join(per_kernel_targets), file=f)

if __name__ == '__main__':
    main()
