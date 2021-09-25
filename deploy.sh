#!/usr/bin/bash
set -e

if [[ ! -f priv.py ]]; then
	echo "err: priv.py does not exist"
	exit 1
fi

target="${1-weaver}"
echo "pushing to host: $target"

mypy weaver_api.py

rsync -aPv ../weaver_api ../python-oil weaver@${target}:
rsync -aPv --no-owner --no-group ./etc/ root@${target}:/etc/

ssh weaver@${target} './weaver_api/setup_weaver_env.sh'

