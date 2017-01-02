
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

    # The idea behind the D.security() context manager is to have an easy way to
    # expose port 22 on AWS instances, run ansible playbooks on them, and then
    # promptly close off port 22 access.
    #
    # However, D.security() will only consider instances that were around at the
    # time the context was created.  So, if ensure_dynamic_instances ends up
    # deciding that it needs to (re)create some instances, then the new instanes
    # will not have their ports exposed.
    #
    # The straightforward solution, which is what is implemented here, is to
    # just exit the security context and enter a new one, at which point we'd be
    # sure to have all the ports we need exposed.
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

        # See above comment explaining why we use two separate block contexts
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

