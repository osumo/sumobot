
import os
import os.path
import shutil
import sys

from argparse import ArgumentParser

from deployment import Deployment

def deploy(args):
    D = Deployment()
    D.ensure_static_resources()

    with D.security():
        D.rolling_base()
        D.ensure_dynamic_instances(args.revision)

    with D.security():
        D.rolling_deploy()

    D.send_bot("deploy complete")

def stage(args):
    D = Deployment()
    rev, staged = D.check_rev(args.revision)
    if staged:
        D.send_bot("revision {} already staged".format(rev))
    else:
        D.ensure_static_resources()
        with D.security():
            D.rolling_base()
            D.ensure_dynamic_instances(args.revision)

        with D.security():
            D.rolling_stage(args.revision)

        D.send_bot("revision {} successfully staged".format(rev))

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
        dir_path = os.path.join(os.getcwd(), "lock")
        try:
            os.mkdir(dir_path)
        except OSError:
            sys.stderr.write("locking operation currently taking place\n")
            sys.exit(1)

        try:
            main(args)
        finally:
            shutil.rmtree(dir_path)
    else:
        main(args)

