
import os
import os.path
import sys
import time

import itertools as it
import subprocess as sp

from contextlib import contextmanager

import boto3
import botocore.exceptions

_DEVNULL = open(os.devnull, "wb")
_SECRET_PREFIX = "secret://"

def get_tag(tag_list, key, default=None):
    result = default
    for tag in tag_list:
        name = tag.get("Key")
        if name is None: continue
        if name == key:
            result = tag.get("Value")
            break

    return result

def get_from_parser(parser, key):
    result = parser.get("default", key)
    if result.startswith(_SECRET_PREFIX):
        path = result[len(_SECRET_PREFIX):]
        result = sp.check_output(
            [ "gpg", "--decrypt", os.path.join("files", path) ],
            stderr=_DEVNULL
        )[:-1]

    return result

class Deployment(object):

    def __init__(self):
        self.security_count = 0
        self.bot_msg_cache = set()
        try:
            from configparser import SafeConfigParser as ConfigParser
        except ImportError:
            from ConfigParser import SafeConfigParser as ConfigParser

        parser = ConfigParser()
        parser.read([os.path.join("files", "aws-config")])

        access_key_id = get_from_parser(parser, "aws_access_key_id")
        secret_access_key = get_from_parser(parser, "aws_secret_access_key")

        self.region = get_from_parser(parser, "region")
        self.namespace = get_from_parser(parser, "namespace")
        self.ami = get_from_parser(parser, "ami")

        self.admin_name = get_from_parser(parser, "admin_name")
        self.admin_pass = get_from_parser(parser, "admin_pass")

        self.public_name = get_from_parser(parser, "public_name")
        self.public_pass = get_from_parser(parser, "public_pass")

        self.staging_ip    = get_from_parser(parser, "staging_ip")
        self.production_ip = get_from_parser(parser, "production_ip")

        self.ssl_cert = get_from_parser(parser, "ssl_cert")
        self.ssl_chain = get_from_parser(parser, "ssl_chain")
        self.ssl_key = get_from_parser(parser, "ssl_key")

        self.s3_staging_bucket = (
            get_from_parser(parser, "s3_staging_bucket"))
        self.s3_production_bucket = (
            get_from_parser(parser, "s3_production_bucket"))

        self.ssh_key = {
            "name": get_from_parser(parser, "ssh_key_name"),
            "pub": get_from_parser(parser, "ssh_key_pub"),
            "sub": get_from_parser(parser, "ssh_key_sub")
        }

        try: os.makedirs("scratch", mode=0o700)
        except OSError: pass

        self.ssh_key_path = os.path.join("scratch", "ssh-key")
        if not os.path.exists(self.ssh_key_path):
            with open(self.ssh_key_path, "w") as f:
                f.write(self.ssh_key["sub"])

        os.chmod(self.ssh_key_path, 0o600)

        self.session = boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=self.region
        )

        self.aws_access_key_id = access_key_id
        self.aws_secret_access_key = secret_access_key

        self.ec2 = self.session.resource("ec2")

        self.vpc = next(iter(self.ec2.vpcs.all()))

        self.static_security_group_conf = (
            {
                "name": "web",
                "rules": (
                    {
                        "flow": "in",
                        "proto": "tcp",
                        "port": [80, 443],
                        "cidr_ip": "0.0.0.0/0"
                    },

                    {
                        "flow": "out",
                        "proto": "all",
                        "cidr_ip": "0.0.0.0/0"
                    },

                    {
                        "flow": "sym",
                        "proto": "all",
                        "groups": ("internal", "temp", "web")
                    },
                )
            },

            {
                "name": "internal",
                "rules": (
                    {
                        "flow": "sym",
                        "proto": "all",
                        "groups": ("internal", "temp", "web")
                    },
                    {
                        "flow": "out",
                        "proto": "all",
                        "cidr_ip": "0.0.0.0/0"
                    },
                )
            },

            {
                "name": "temp",
                "rules": (
                    {
                        "flow": "in",
                        "proto": "tcp",
                        "port": [22, 80, 443, 8080],
                        "cidr_ip": "0.0.0.0/0"
                    },

                    {
                        "flow": "out",
                        "proto": "all",
                        "cidr_ip": "0.0.0.0/0"
                    },

                    {
                        "flow": "sym",
                        "proto": "all",
                        "groups": ("internal", "temp", "web")
                    },
                )
            },
        )

        self.static_security_groups = {}

        self.static_instance_conf = {
            "p/db": {
                "type": "t2.medium",
                "volumes": [20],
                "groups": ["internal"],
            },

            "p/queue": {
                "type": "t2.medium",
                "volumes": [20],
                "groups": ["internal"],
            },

            "s/db+mq": {
                "type": "t2.medium",
                "volumes": [20],
                "groups": ["internal"],
            },
        }

        self.dynamic_instance_conf = {
            "web": {
                "type": "t2.medium",
                "volumes": [20],
                "groups": ["web"],
            },

            "worker": {
                "type": "t2.medium",
                "volumes": [20],
                "groups": ["internal"],
            },
        }

        self.instances = {}

    def run_play(self, inventory_name, playbook_name, fragments,
                 global_vars=None):
        if global_vars is None: global_vars = {}
        inventory_path = os.path.join("scratch", inventory_name)

        with open(inventory_path, "w") as f:
            f.write("\n".join(
                self.generate_inventory_fragment(
                    group_name, group_keys, global_vars)

                for group_name, group_keys in fragments.items()
            ))

            f.flush()

        sp.check_call([
            "ansible-playbook",
            "-i",
            inventory_path,
            os.path.join("files", "playbooks", playbook_name),
        ])

    def send_bot(self, msg):
        if msg in self.bot_msg_cache:
            return

        self.bot_msg_cache.add(msg)
        print("BOT: {}".format(msg))
        sys.stdout.flush()

    def ensure_static_key_pair(self):
        self.send_bot("checking key pair")
        key_pair = self.ec2.key_pairs.filter(Filters=[{
            "Name": "key-name", "Values": [self.namespace]
        }])

        key_pair_tuple = tuple(iter(key_pair))
        if key_pair_tuple:
            key_pair = key_pair_tuple[0]
        else:
            key_pair = self.ec2.import_key_pair(
                KeyName=self.namespace,
                PublicKeyMaterial=self.ssh_key["pub"]
            )

        self.key_pair = key_pair

    def ensure_static_security_groups(self):
        self.send_bot("checking security groups")
        security_groups = self.ec2.security_groups.filter(Filters=[{
            "Name": "tag:namespace", "Values": [self.namespace],
        }]).filter(Filters=[{
            "Name": "tag:role", "Values": [
                sg["name"] for sg in self.static_security_group_conf]
        }]).filter(Filters=[{
            "Name": "vpc-id", "Values": [self.vpc.id]
        }])

        todo_list = []
        for sg in self.static_security_group_conf:
            sg_name = sg["name"]
            sg_rules = sg["rules"]

            fq_name = "/".join((self.namespace, sg_name))
            sub_sg = security_groups.filter(Filters=[{
                "Name": "group-name", "Values": [fq_name]
            }])

            new_sg_tuple = tuple(iter(sub_sg))
            if new_sg_tuple:
                new_sg = new_sg_tuple[0]
            else:
                new_sg = self.ec2.create_security_group(
                    GroupName=fq_name,
                    Description="test-description",
                    VpcId=self.vpc.id,
                )

            self.static_security_groups[sg_name] = new_sg.id
            todo_list.append((new_sg, sg_name, sg_rules))

        time.sleep(5)

        for new_sg, sg_name, sg_rules in todo_list:
            self.ec2.create_tags(
                Resources=[new_sg.id],
                Tags=[
                    {"Key": "namespace", "Value": self.namespace},
                    {"Key": "role", "Value": sg_name}
                ]
            )

            ingress_permissions = []
            egress_permissions = []
            for rule in sg_rules:
                flow = rule.get("flow", "in")
                do_ingress = (flow == "sym" or flow == "in")
                do_egress = (flow == "sym" or flow == "out")

                ports = []
                port = rule.get("port")
                if port is not None:
                    try:
                        for port_entry in port:
                            try:
                                from_port, to_port = tuple(port_entry)
                            except TypeError:
                                from_port = port_entry
                                to_port = port_entry
                            ports.append((from_port, to_port))
                    except TypeError:
                        ports.append((port, port))

                if not ports:
                    ports.append(None)

                groups = rule.get("groups")
                if isinstance(groups, basestring) or groups is None:
                    groups = [groups]

                protos = rule.get("proto", "all")
                if isinstance(protos, basestring):
                    if protos == "all":
                        protos = ["tcp", "udp", "icmp"]
                    else:
                        protos = [protos]

                iterator = it.product(ports, groups, protos)
                for (port_entry, group, proto) in iterator:
                    perm_entry = {}
                    from_port, to_port = (
                        2*(-1,) if proto == "icmp" else
                        (0, (1 << 16) - 1)
                    )

                    if port_entry is not None:
                        from_port, to_port = port_entry

                    perm_entry["IpProtocol"] = proto
                    perm_entry["FromPort"] = from_port
                    perm_entry["ToPort"] = to_port

                    cidr_ip = rule.get("cidr_ip")
                    if cidr_ip is not None:
                        perm_entry["IpRanges"] = [{ "CidrIp": cidr_ip }]

                    if group is not None:
                        perm_entry["UserIdGroupPairs"] = [{
                            "GroupId": self.static_security_groups[group],
                            "VpcId": self.vpc.id
                        }]

                    if do_ingress:
                        ingress_permissions.append(perm_entry)

                    if do_egress:
                        egress_permissions.append(perm_entry)

            new_sg.revoke_ingress(IpPermissions=[{
                "IpProtocol": "-1",
                "FromPort": -1,
                "ToPort": -1,
                "IpRanges": [{ "CidrIp": "0.0.0.0/0" }]
            }])

            new_sg.revoke_egress(IpPermissions=[{
                "IpProtocol": "-1",
                "FromPort": -1,
                "ToPort": -1,
                "IpRanges": [{ "CidrIp": "0.0.0.0/0" }]
            }])

            for perm in ingress_permissions:
                try: new_sg.authorize_ingress(IpPermissions=[perm])
                except botocore.exceptions.ClientError: pass

            for perm in egress_permissions:
                try: new_sg.authorize_egress(IpPermissions=[perm])
                except botocore.exceptions.ClientError: pass

    def ensure_static_instances(self):
        self.send_bot("checking static instances")
        instances =  self.ec2.instances.filter(Filters=[{
            "Name": "tag:namespace", "Values": [self.namespace]
        }]).filter(Filters=[{
            "Name": "tag:role", "Values": self.static_instance_conf.keys()
        }]).filter(Filters=[{
            "Name": "instance-state-name", "Values": [
                "pending", "running", "stopping", "stopped"
            ]
        }])

        journal = []
        for role, instance in self.static_instance_conf.items():
            count = instance.get("count", 1)
            i_type = instance.get("type", "t2.nano")
            volumes = instance.get("volumes", [])
            groups = instance.get("groups", [])

            subinstances = instances.filter(Filters=[{
                "Name": "tag:role", "Values": [role],
            }])

            instance_tuple = tuple(subinstances)
            journal_entry = list(instance_tuple)

            num_instances = max(count - len(instance_tuple), 0)
            if num_instances > 0:
                new_instances = self.ec2.create_instances(
                    ImageId=self.ami,
                    KeyName=self.namespace,
                    InstanceType=i_type,
                    MinCount=num_instances,
                    MaxCount=num_instances,
                    BlockDeviceMappings=[
                        {
                            "DeviceName": "xvd" + chr(ord("b") + index),
                            "Ebs": {
                                "VolumeSize": volume,
                                "DeleteOnTermination": True
                            }
                        }
                        for (index, volume) in enumerate(volumes)
                    ],
                    SecurityGroupIds=[
                        self.static_security_groups[group_name]
                        for group_name in groups
                    ]
                )

                journal_entry.extend(new_instances)
                for instance in new_instances:
                    instance.wait_until_running()

                self.ec2.create_tags(
                    Resources=[inst.id for inst in new_instances],
                    Tags=[
                        {"Key": "Name",
                         "Value": "/".join((self.namespace, role))},
                        {"Key": "namespace", "Value": self.namespace},
                        {"Key": "role", "Value": role},
                        {"Key": "state", "Value": "static"}
                    ]
                )

            journal.append((role, journal_entry))

        for role, instance_list in journal:
            for instance in instance_list: instance.wait_until_running()
            self.instances[role] = list(instances.filter(InstanceIds=[
                instance.id for instance in instance_list
            ]))

    def ensure_dynamic_instances(self, rev="master"):
        self.send_bot("checking dynamic instances")
        instances =  self.ec2.instances.filter(Filters=[{
            "Name": "tag:namespace", "Values": [self.namespace]
        }]).filter(Filters=[{
            "Name": "tag:role", "Values": self.dynamic_instance_conf.keys()
        }]).filter(Filters=[{
            "Name": "instance-state-name", "Values": [
                "pending", "running", "stopping", "stopped"
            ]
        }])

        prestage = False
        predeploy = False
        for role in self.dynamic_instance_conf.keys():
            subinstances = instances.filter(Filters=[{
                "Name": "tag:role", "Values": [role],
            }])

            self.instances[role] = {
                state: list(subinstances.filter(Filters=[{
                    "Name": "tag:state", "Values": [state],
                }]))

                for state in ("live", "staged", "pending")
            }

            prestage = (prestage or not self.instances[role]["staged"])
            predeploy = (predeploy or not self.instances[role]["live"])

        for flag, state in ((predeploy, "live"), (prestage, "staged")):
            if not flag: continue

            rev, _ = self.check_rev(rev)

            for role in self.dynamic_instance_conf.keys():
                instance_entry = self.instances.get(role)
                if not instance_entry: continue

                instances = instance_entry.get(state)
                if not instances: continue

                self.ec2.instances.filter(InstanceIds=[
                    instance.id for instance in instances
                ]).terminate()

            journal = []
            for role, instance in self.dynamic_instance_conf.items():
                count = instance.get("count", 1)
                i_type = instance.get("type", "t2.nano")
                volumes = instance.get("volumes", [])
                groups = instance.get("groups", [])

                new_instances = self.ec2.create_instances(
                    ImageId=self.ami,
                    KeyName=self.namespace,
                    InstanceType=i_type,
                    MinCount=count,
                    MaxCount=count,
                    BlockDeviceMappings=[
                        {
                            "DeviceName": "xvd" + chr(ord("b") + index),
                            "Ebs": {
                                "VolumeSize": volume,
                                "DeleteOnTermination": True
                            }
                        }
                        for (index, volume) in enumerate(volumes)
                    ],
                    SecurityGroupIds=[
                        self.static_security_groups[group_name]
                        for group_name in groups
                    ]
                )

                for instance in new_instances:
                    instance.wait_until_running()

                self.ec2.create_tags(
                    Resources=[inst.id for inst in new_instances],
                    Tags=[
                        {"Key": "Name",
                         "Value": "/".join((self.namespace, role))},
                        {"Key": "namespace", "Value": self.namespace},
                        {"Key": "role", "Value": role},
                        {"Key": "state", "Value": state}
                    ]
                )

                journal.append((role, new_instances))

            time.sleep(5)

            for role, instance_list in journal:
                for instance in instance_list: instance.wait_until_running()
                self.instances[role][state] = list(
                    self.ec2.instances.filter(InstanceIds=[
                        instance.id for instance in instance_list
                    ])
                )

            self.run_play(
                "prep-inventory",
                "prep.yml",
                {
                    "web": (("web", state),),
                    "worker": (("worker", state),),
                    "db": ("p/db",) if state == "live" else ("s/db+mq",),
                    "queue": ("p/queue",) if state == "live" else ("s/db+mq",),
                    "dynamic": (("web", state), ("worker", state))
                },
                {
                    "revision": rev,
                    "admin_name": self.admin_name,
                    "admin_pass": self.admin_pass,
                    "public_name": self.public_name,
                    "public_pass": self.public_pass,
                    "deploy_mode": (
                        "production" if state == "live" else "staging"),
                    "s3_bucket": (
                        self.s3_production_bucket
                        if state == "live" else
                        self.s3_staging_bucket),
                    "aws_access_key_id": self.aws_access_key_id,
                    "aws_secret_access_key": self.aws_secret_access_key,
                    "ssl_cert": self.ssl_cert,
                    "ssl_chain": self.ssl_chain,
                    "ssl_key": self.ssl_key,
                }
            )

            next(iter(
                self.ec2.vpc_addresses.filter(PublicIps=[
                    self.production_ip
                    if state == "live" else
                    self.staging_ip
                ])
            )).associate(
                InstanceId=self.instances["web"][state][0].id
            )

            for role, entry in self.instances.items():
                if not isinstance(entry, dict): continue
                for instance in entry.get(state, ()):
                    instance.create_tags(Tags=[
                        {"Key": "revision", "Value": rev},
                    ])

    def open_security(self):
        static_sg = self.static_security_groups["temp"]

        for instance in self.ec2.instances.filter(Filters=[{
                    "Name": "tag:namespace", "Values": [self.namespace]
                }]).filter(Filters=[{
                    "Name": "instance-state-name", "Values": [
                        "pending", "running", "stopping", "stopped"
                    ]
                }]):
            security_groups = [sg["GroupId"] for sg in instance.security_groups]
            need_temp = all(sg != static_sg for sg in security_groups)

            if need_temp:
                self.ec2.meta.client.modify_instance_attribute(
                    InstanceId=instance.id,
                    Groups=security_groups + [static_sg])

    def close_security(self):
        static_sg = self.static_security_groups["temp"]

        for instance in self.ec2.instances.filter(Filters=[{
                    "Name": "tag:namespace", "Values": [self.namespace]
                }]).filter(Filters=[{
                    "Name": "instance-state-name", "Values": [
                        "pending", "running", "stopping", "stopped"
                    ]
                }]):
            security_groups = [sg["GroupId"] for sg in instance.security_groups]
            remove_temp = any(sg == static_sg for sg in security_groups)

            if remove_temp:
                self.ec2.meta.client.modify_instance_attribute(
                    InstanceId=instance.id,
                    Groups=[sg for sg in security_groups if sg != static_sg])

    @contextmanager
    def security(self):
        if self.security_count == 0:
            self.open_security()

        self.security_count += 1
        yield

        self.security_count -= 1
        if self.security_count == 0:
            self.close_security()

    def check_rev(self, rev="master"):
        submodule = "osumo-project"

        sp.check_call(
            ["git", "submodule", "update", "--init", submodule],
            stdout=_DEVNULL,
            stderr=_DEVNULL,
        )

        sp.check_call(
            ["git", "fetch", "--all"],
            cwd=submodule,
            stdout=_DEVNULL,
            stderr=_DEVNULL,
        )

        sp.check_call(
            ["git", "checkout", rev],
            cwd=submodule,
            stdout=_DEVNULL,
            stderr=_DEVNULL,
        )

        is_branch = (
            sp.check_output(
                ["git", "status", "--branch", "--porcelain"],
                cwd=submodule,
                stderr=_DEVNULL,
            ).split("\n")[0] != "## HEAD (no branch)"
        )

        if is_branch:
            sp.check_call(
                ["git", "pull"],
                cwd=submodule,
                stdout=_DEVNULL,
                stderr=_DEVNULL,
            )

        rev = sp.check_output(
            ["git", "rev-parse", "--no-flags", rev],
            cwd=submodule,
            stderr=_DEVNULL,
        )[:-1]

        sp.check_call(
            ["git", "checkout", rev],
            cwd=submodule,
            stdout=_DEVNULL,
            stderr=_DEVNULL,
        )

        staged_web = list(
            self.ec2.instances.filter(Filters=[{
                "Name": "tag:namespace", "Values": [self.namespace],
            }]).filter(Filters=[{
                "Name": "tag:role", "Values": ["web"],
            }]).filter(Filters=[{
                "Name": "instance-state-name", "Values": [
                    "pending", "running", "stopping", "stopped"
                ]
            }]).filter(Filters=[{
                "Name": "tag:state", "Values": ["staged"]
            }])
        )

        already_staged = False
        if staged_web:
            already_staged = (
                get_tag(staged_web[0].tags, "revision") == rev)

        return rev, already_staged

    def generate_inventory_fragment_iterator(self, group, keys, env):
        if group is not None:
            yield "[{}]".format(group)

        for key in keys:
            try: key, subkey = key
            except (TypeError, ValueError): subkey = None

            instances = self.instances[key]
            if subkey is not None:
                instances = instances[subkey]

            yield "\n".join(
                "{} ansible_ssh_private_key_file={} aws_private_ip={}".format(
                    instance.public_ip_address,
                    self.ssh_key_path,
                    instance.private_ip_address,
                )
                for instance in instances
            )

        yield ""

        if group is not None:
            yield "[{}:vars]".format(group)

            for key, value in env.items():
                yield "{}={}".format(key, value)

    def generate_inventory_fragment(self, group, keys, env):
        return "\n".join(
            self.generate_inventory_fragment_iterator(group, keys, env))

    def rolling_base(self):
        self.ensure_static_resources()
        self.send_bot("provisioning base services")

        self.run_play(
            "base-inventory",
            "base.yml",
            {
                "db": ("s/db+mq", "p/db"),
                "mq": ("s/db+mq", "p/queue"),
                "stage": ("s/db+mq", ),
                "prod": ("p/queue", ),
            }
        )

    def rolling_stage(self, rev="master"):
        rev, already_staged = self.check_rev(rev)
        self.send_bot("staging revision: {}".format(rev))

        instance_query = None
        for role in self.dynamic_instance_conf.keys():
            instance_entry = self.instances.get(role)
            if not instance_entry: continue

            pending_instances = instance_entry.get("pending")
            if not pending_instances: continue

            if instance_query is None:
                instance_query = self.ec2.instances.filter(Filters=[{
                    "Name": "tag:namespace", "Values": [self.namespace]
                }]).filter(Filters=[{
                    "Name": "tag:role",
                        "Values": self.dynamic_instance_conf.keys()
                }]).filter(Filters=[{
                    "Name": "instance-state-name", "Values": [
                        "pending", "running", "stopping", "stopped"
                    ]
                }])

            instance_query.filter(InstanceIds=[
                instance.id for instance in pending_instances
            ]).terminate()

        journal = []
        for role, instance in self.dynamic_instance_conf.items():
            count = instance.get("count", 1)
            i_type = instance.get("type", "t2.nano")
            volumes = instance.get("volumes", [])
            groups = instance.get("groups", [])

            new_instances = self.ec2.create_instances(
                ImageId=self.ami,
                KeyName=self.namespace,
                InstanceType=i_type,
                MinCount=count,
                MaxCount=count,
                BlockDeviceMappings=[
                    {
                        "DeviceName": "xvd" + chr(ord("b") + index),
                        "Ebs": {
                            "VolumeSize": volume,
                            "DeleteOnTermination": True
                        }
                    }
                    for (index, volume) in enumerate(volumes)
                ],
                SecurityGroupIds=[
                    self.static_security_groups[group_name]
                    for group_name in (groups + ["temp"])
                ]
            )

            for instance in new_instances:
                instance.wait_until_running()

            self.ec2.create_tags(
                Resources=[inst.id for inst in new_instances],
                Tags=[
                    {"Key": "Name",
                     "Value": "/".join((self.namespace, role))},
                    {"Key": "namespace", "Value": self.namespace},
                    {"Key": "role", "Value": role},
                    {"Key": "state", "Value": "pending"}
                ]
            )

            journal.append((role, new_instances))

        time.sleep(5)

        for role, instance_list in journal:
            for instance in instance_list: instance.wait_until_running()
            self.instances[role]["pending"] = list(self.ec2.instances.filter(
                InstanceIds=[
                    instance.id for instance in instance_list
                ]
            ))

        self.run_play(
            "prep-inventory",
            "prep.yml",
            {
                "web": (("web", "pending"),),
                "worker": (("worker", "pending"),),
                "db": ("s/db+mq",),
                "queue": ("s/db+mq",),
                "dynamic": (("web", "pending"), ("worker", "pending"))
            },
            {
                "revision": rev,
                "admin_name": self.admin_name,
                "admin_pass": self.admin_pass,
                "public_name": self.public_name,
                "public_pass": self.public_pass,
                "deploy_mode": "staging",
                "s3_bucket": self.s3_staging_bucket,
                "aws_access_key_id": self.aws_access_key_id,
                "aws_secret_access_key": self.aws_secret_access_key,
                "ssl_cert": self.ssl_cert,
                "ssl_chain": self.ssl_chain,
                "ssl_key": self.ssl_key,
            }
        )


        next(iter(
            self.ec2.vpc_addresses.filter(PublicIps=[self.staging_ip])
        )).associate(
            InstanceId=self.instances["web"]["pending"][0].id
        )

        journal = []
        for role, entry in self.instances.items():
            if not isinstance(entry, dict): continue
            if entry["staged"]:
                journal.extend(entry["staged"])

            entry["staged"] = entry.pop("pending")
            for instance in entry["staged"]:
                instance.create_tags(Tags=[
                    {"Key": "state", "Value": "staged"},
                    {"Key": "revision", "Value": rev},
                ])

        for instance in journal: instance.terminate()
        for instance in journal: instance.wait_until_terminated()

    def rolling_deploy(self):
        self.send_bot("deploying")

        self.run_play(
            "reconfigure-inventory",
            "reconfigure.yml",
            {
                "web": (("web", "staged"),),
                "worker": (("worker", "staged"),),
                "db": ("p/db",),
                "queue": ("p/queue",),
                "dynamic": (("web", "staged"), ("worker", "staged"))
            },
            {
                "admin_name": self.admin_name,
                "admin_pass": self.admin_pass,
                "public_name": self.public_name,
                "public_pass": self.public_pass,
                "deploy_mode": "production",
                "s3_bucket": self.s3_production_bucket,
                "aws_access_key_id": self.aws_access_key_id,
                "aws_secret_access_key": self.aws_secret_access_key,
                "ssl_cert": self.ssl_cert,
                "ssl_chain": self.ssl_chain,
                "ssl_key": self.ssl_key,
            }
        )

        # swap ips
        next(iter(
            self.ec2.vpc_addresses.filter(PublicIps=[self.production_ip])
        )).associate(
            InstanceId=self.instances["web"]["staged"][0].id
        )
        next(iter(
            self.ec2.vpc_addresses.filter(PublicIps=[self.staging_ip])
        )).associate(
            InstanceId=self.instances["web"]["live"][0].id
        )

        # rebrand staged -> live
        # rebrand live -> staged
        for role, entry in self.instances.items():
            if not isinstance(entry, dict): continue
            staged_instances = entry["staged"]
            live_instances = entry["live"]

            for instance in staged_instances:
                instance.create_tags(Tags=[
                    {"Key": "state", "Value": "live"},
                ])

            for instance in live_instances:
                instance.create_tags(Tags=[
                    {"Key": "state", "Value": "staged"},
                ])

            entry["live"] = staged_instances
            entry["staged"] = live_instances

        # refresh local instance cache (to reflect changes in elastic ip)
        time.sleep(30)
        for role, entry in self.instances.items():
            if not isinstance(entry, dict): continue
            for state in ("live", "staged"):
                entry[state] = list(
                    self.ec2.instances.filter(InstanceIds=[
                        instance.id for instance in entry[state]
                    ])
                )

        self.run_play(
            "reconfigure-inventory",
            "reconfigure.yml",
            {
                "web": (("web", "staged"),),
                "worker": (("worker", "staged"),),
                "db": ("s/db+mq",),
                "queue": ("s/db+mq",),
                "dynamic": (("web", "staged"), ("worker", "staged"))
            },
            {
                "admin_name": self.admin_name,
                "admin_pass": self.admin_pass,
                "public_name": self.public_name,
                "public_pass": self.public_pass,
                "deploy_mode": "staging",
                "s3_bucket": self.s3_staging_bucket,
                "aws_access_key_id": self.aws_access_key_id,
                "aws_secret_access_key": self.aws_secret_access_key,
                "ssl_cert": self.ssl_cert,
                "ssl_chain": self.ssl_chain,
                "ssl_key": self.ssl_key,
            }
        )

    def ensure_static_resources(self):
        self.ensure_static_key_pair()
        self.ensure_static_security_groups()
        self.ensure_static_instances()

