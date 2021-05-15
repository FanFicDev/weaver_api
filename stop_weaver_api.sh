#!/usr/bin/env bash

kill -s SIGINT $(cat weaver_api_master.pid)
rm weaver_api_master.pid

