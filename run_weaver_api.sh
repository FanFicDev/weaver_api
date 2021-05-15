#!/usr/bin/env bash

export OIL_DB_DBNAME=weaver
mkdir -p ./logs/

exec uwsgi --plugin python3 --enable-threads \
	--reuse-port --uwsgi-socket 127.0.0.1:9161 \
	--plugin logfile  \
	--logger file:logfile=./logs/weaver_api.log,maxsize=2000000 \
	--daemonize2 /dev/null \
	--pidfile weaver_api_master.pid \
	--master --processes 2 --threads 3 \
	--manage-script-name --mount /weaver=weaver_api:app

