#! /usr/bin/env python

import json
import os.path

from argparse import ArgumentParser
from time import sleep

from girder.constants import AssetstoreType
from girder_client import GirderClient

def find_user(username):
    result = None
    offset = 0
    while True:
        users = client.get(
            'user',
            parameters=dict(
                text=username,
                limit=50,
                offset=offset,
                sort="login"
            )
        )

        if not users: break

        for user in users:
            if user["login"] == username:
                result = user
                break

        if result:
            break

        offset += 50

    return result

def ensure_user(client, **kwds):
    username = kwds['login']
    password = kwds['password']

    user = find_user(username)
    if user:
        client.put(
            'user/{}'.format(user["_id"]),
            parameters=dict(email=kwds['email'],
                            firstName=kwds['firstName'],
                            lastName=kwds['lastName']))

        client.put(
            'user/{}/password'.format(user["_id"]),
            parameters=dict(password=password))
    else:
        client.post('user', parameters=dict(login=username,
                                            password=password,
                                            email=kwds['email'],
                                            firstName=kwds['firstName'],
                                            lastName=kwds['lastName']))

def find_assetstore(name):
    offset = 0
    limit = 50
    result = None
    while result is None:
        assetstore_list = client.get('assetstore',
                                     parameters=dict(limit=str(limit),
                                                     offset=str(offset)))

        if not assetstore_list:
            break

        for assetstore in assetstore_list:
            if assetstore['name'] == name:
                result = assetstore['_id']
                break

        offset += limit

    return result

parser = ArgumentParser(description='Initialize the girder environment')
parser.add_argument('--admin', help='name:pass for the admin user')
parser.add_argument('--host', help='host to connect to')
parser.add_argument('--port', type=int, help='port to connect to')
parser.add_argument('--broker', help='girder worker broker URI')
parser.add_argument('--sumo-user', help='name:pass for sumo public user')
parser.add_argument('--s3', help='name of S3 bucket')
parser.add_argument('--aws-key-id', help='aws key id')
parser.add_argument('--aws-secret-key', help='aws secret key')

args = parser.parse_args()

client = GirderClient(host=args.host, port=args.port)

user, password = args.admin.split(":", 1)
ensure_user(client,
            login=user,
            password=password,
            email='admin@osumo.org',
            firstName='Girder',
            lastName='Admin')

client.authenticate(user, password)

user, password = args.sumo_user.split(":", 1)
ensure_user(client,
            login=user,
            password=password,
            email='public@osumo.org',
            firstName='Osumo',
            lastName='Public')

s3_assetstore_name = 's3'

if find_assetstore(s3_assetstore_name) is None:
    client.post('assetstore',
                parameters=dict(name=s3_assetstore_name,
                                type=str(AssetstoreType.S3),
                                bucket=args.s3,
                                accessKeyId=args.aws_key_id,
                                secret=args.aws_secret_key))

client.put(
    'system/plugins',
    parameters=dict(plugins=json.dumps(['jobs', 'worker', 'osumo']))
)

client.put('system/restart')

sleep(30)

client.put('system/setting',
           parameters=dict(list=json.dumps([
               dict(key='worker.broker', value=args.broker),
               dict(key='worker.backend', value=args.broker)])))

client.put('system/restart')

