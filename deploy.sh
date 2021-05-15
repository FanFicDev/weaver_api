#!/usr/bin/bash
set -e

if [[ ! -f secrets.py ]]; then
	echo "err: secrets.py does not exist"
	exit 1
fi

mypy weaver_api.py

rsync -aPv ../weaver_api ../python-oil weaver:
rsync -aPv --no-owner --no-group ./etc/ root@weaver:/etc/

ssh weaver './weaver_api/setup_weaver_env.sh'

