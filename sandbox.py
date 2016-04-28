#! /usr/bin/env python

import os.path

from code import InteractiveConsole
from deployment import Deployment

D = Deployment()

console = InteractiveConsole(locals={"D": D, "ec2": D.ec2})
pyrc = os.path.expanduser(os.path.join("~", ".pythonrc.py"))
if os.path.exists(pyrc):
    console.runsource(open(pyrc).read())
console.interact()

