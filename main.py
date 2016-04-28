
import os
import os.path
import shutil
import sys

from argparse import ArgumentParser
from contextlib import contextmanager

from deployment import Deployment

class FileLockError(Exception):
    pass

@contextmanager
def file_lock():
    dir_path = os.path.join(os.getcwd(), "lock")
    try:
        os.mkdir(dir_path)
    except OSError:
        raise FileLockError()
    else:
        yield
        shutil.rmtree(dir_path)

def deploy(args):
    D = Deployment()
    D.ensure_static_resources()
    D.rolling_base()
    D.ensure_dynamic_instances(args.revision)
    D.rolling_deploy()

def stage(args):
    D = Deployment()
    D.ensure_static_resources()
    D.rolling_base()
    D.ensure_dynamic_instances(args.revision)
    D.rolling_stage(args.revision)

def status(args):
    pass

def update(args):
    pass

def main(args):
    {
        "deploy": deploy,
        "stage": stage,
        "status": status,
        "update": update,
    }[args.operation](args)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "operation", choices=("deploy", "stage", "status", "update"),
        help="operation to perform"
    )
    parser.add_argument(
        "-v", "--revision", help="git revision to stage", default="master"
    )

    args = parser.parse_args()

    need_file_lock = args.operation in ("deploy", "stage", "update")

    if need_file_lock:
        try:
            with file_lock():
                main(args)
        except FileLockError:
            sys.stderr.write("locking operation currently taking place\n")
            sys.exit(1)
    else:
        main(args)

