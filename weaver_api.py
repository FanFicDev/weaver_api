from typing import Any, Dict, Union, Tuple, Optional, cast
import os
import threading
import traceback
import math
import datetime
from enum import IntEnum
from flask import Flask, Response, request, render_template, \
	make_response
import werkzeug.wrappers
from werkzeug.exceptions import HTTPException, NotFound
import psycopg2
import requests
import urllib.parse
from oil import oil

app = Flask(__name__, static_url_path='')
defaultRequestTimeout = 60
defaultUserAgent = 'weaver_api'
skitterBaseUrl = 'https://athena.fanfic.dev/skitter/'

import priv
skitterApiKey = priv.skitterApiKey
skitterUser = priv.skitterUser

BasicFlaskResponse = Union[Response, werkzeug.wrappers.Response, str, Dict[str, Any]]
FlaskResponse = Union[BasicFlaskResponse, Tuple[BasicFlaskResponse, int]]

CACHE_BUSTER=1

class WeaverLimiter:
	def __init__(self, id_: int, key_: str, capacity_: float, flow_: float,
			value_: float, lastDrain_: datetime.datetime) -> None:
		self.id = id_
		self.key = key_
		self.capacity = capacity_
		self.flow = flow_
		self.value = value_
		self.lastDrain = lastDrain_

	def burst(self) -> float:
		return max(0, self.capacity - self.value)

	def isAnon(self) -> bool:
		return self.key.startswith('anon:')

	@staticmethod
	def fromRow(row: Any) -> 'WeaverLimiter':
		return WeaverLimiter(*row)

	@staticmethod
	def select(db: 'psycopg2.connection', key: str) -> Optional['WeaverLimiter']:
		with db, db.cursor() as curs:
			curs.execute('''
				select id, key, capacity, flow, value, lastDrain
				from weaver_limiter wl
				where wl.key = %s''', (key,))
			r = curs.fetchone()
			return None if r is None else WeaverLimiter.fromRow(r)

	@staticmethod
	def create(db: 'psycopg2.connection', key: str) -> 'WeaverLimiter':
		with db, db.cursor() as curs:
			curs.execute('''
				insert into weaver_limiter(key, capacity, flow, value, lastDrain)
				values(%s, %s, %s, %s, now())''', (key, 5, 1.0/20, 0))
		limiter = WeaverLimiter.select(db, key)
		assert(limiter is not None)
		return limiter

	def refresh(self, db: 'psycopg2.connection') -> 'WeaverLimiter':
		limiter = WeaverLimiter.select(db, self.key)
		assert(limiter is not None)
		return limiter

	def retryAfter(self, db: 'psycopg2.connection', value: float
			) -> Optional[float]:
		with db, db.cursor() as curs:
			curs.execute('select weaver_fill_limiter(%s, %s)', (self.key, value))
			r = curs.fetchone()
			if r is None:
				raise Exception('WeaverLimiter.retryAfter: no fill limit response')
			v = float(r[0])
			if v <= 0:
				return None
			return v

	def retryAfterResponse(self, db: 'psycopg2.connection', value: float
			) -> Optional[FlaskResponse]:
		retryAfter = self.retryAfter(db, value)
		if retryAfter is None:
			return None

		retryAfter = int(math.ceil(retryAfter))

		res = make_response(
				{'err':-429,'msg':'too many requests','retryAfter':retryAfter},
				429)
		res.headers['Retry-After'] = retryAfter
		return res

class WeaverRequestLog:
	@staticmethod
	def log(db: 'psycopg2.connection', lid: int, url: Optional[str]) -> None:
		with db, db.cursor() as curs:
			curs.execute('''
				insert into weaver_request_log(lid, url, created)
				values(%s, %s, now())''', (lid, url))

class WebError(IntEnum):
	success = 0
	no_query = -1

errorMessages = {
		WebError.success: 'success',
		WebError.no_query: 'no query',
	}

def getErr(err: WebError, extra: Optional[Dict[str, Any]] = None
		) -> Dict[str, Any]:
	base = {'err':int(err),'msg':errorMessages[err]}
	if extra is not None:
		base.update(extra)
	return base

@app.errorhandler(404)
def page_not_found(e: HTTPException) -> FlaskResponse:
	# FIXME should we limit here too?
	return make_response({'err':-404,'msg':'not found'}, 404)

@app.route('/')
def index() -> FlaskResponse:
	return render_template('index.html', CACHE_BUSTER=CACHE_BUSTER)

def get_limiter(db: 'psycopg2.connection', remoteAddr: str,
		apiKey: Optional[str]) -> WeaverLimiter:
	if apiKey is not None:
		limiter = WeaverLimiter.select(db, apiKey)
		if limiter is not None:
			return limiter

	apiKey = f'anon:{remoteAddr}'
	limiter = WeaverLimiter.select(db, apiKey)
	if limiter is not None:
		return limiter
	return WeaverLimiter.create(db, apiKey)

@app.route('/v0', methods=['GET'], strict_slashes=False)
@app.route('/v0/status', methods=['GET'])
def v0_status() -> FlaskResponse:
	remoteAddr = request.remote_addr
	apiKey = request.values.get('apiKey', None)

	with oil.open() as db:
		limiter = get_limiter(db, remoteAddr, apiKey)
		retryAfterResponse = limiter.retryAfterResponse(db, .1)
		if retryAfterResponse is not None:
			return retryAfterResponse

		limiter = limiter.refresh(db)
		return make_response({'err':0,'status':'ok',
				'pid':os.getpid(),'tident':threading.get_ident(),
				'burst':int(math.floor(limiter.burst()))})

@app.route('/v0/remote', methods=['GET'])
def v0_remote() -> FlaskResponse:
	return request.remote_addr

@app.route('/v0/ffn/crawl', methods=['GET'])
def v0_ffn_crawl() -> FlaskResponse:
	remoteAddr = request.remote_addr
	apiKey = request.values.get('apiKey', None)

	q = request.values.get('q', None)
	if q is not None and len(q) > 4096:
		q = q[:4096]
	print(f'v0_ffn_crawl: {q=}')

	with oil.open() as db:
		limiter = get_limiter(db, remoteAddr, apiKey)
		WeaverRequestLog.log(db, limiter.id, q)

		if limiter.isAnon():
			glimiter = WeaverLimiter.select(db, 'global_anon')
			if glimiter is None:
				return make_response({'err':-5,'msg':'no global limiter'}, 500)
			retryAfterResponse = glimiter.retryAfterResponse(db, 1)
			if retryAfterResponse is not None:
				return retryAfterResponse

		retryAfterResponse = limiter.retryAfterResponse(db, 1)
		if retryAfterResponse is not None:
			return retryAfterResponse

	if (q is None or len(q.strip()) < 1):
		return make_response({'err':-1,'msg':'missing q param'}, 400)

	prefixMunge = [
			('http://', 'https://'),
			('https://fanfiction.net/', 'https://www.fanficton.net/'),
			#('https://m.fanfiction.net/', 'https://www.fanficton.net/'),
		]
	for munge in prefixMunge:
		if q.startswith(munge[0]):
			q = munge[1] + q[len(munge[0]):]

	if not q.startswith('https://www.fanfiction.net/') \
			and not q.startswith('https://m.fanfiction.net/'):
		return make_response({'err':-2,'msg':'url is not ffn','arg':q}, 400)

	try:
		global defaultRequestTimeout, defaultUserAgent
		global skitterBaseUrl, skitterApiKey, skitterUser

		cookies: Dict[str, str] = {}
		headers = { 'User-Agent': defaultUserAgent }
		url = urllib.parse.urljoin(skitterBaseUrl, 'v0/crawl')

		r = requests.get(url, headers=headers, cookies=cookies,
				params={'q': q}, data={'apiKey': skitterApiKey}, auth=skitterUser,
				timeout=defaultRequestTimeout)
		if r.status_code != 200:
			return make_response({'err':-3,'msg':'skitter error','arg':q}, 500)

		fres = make_response(r.content)
		for rh in r.headers:
			if rh.startswith('X-Weaver'):
				fres.headers[rh] = r.headers[rh]
		return fres
	except Exception as e:
		print(f'v0_ffn_crawl: exception {q}: {e}\n{traceback.format_exc()}')

	return make_response({'err':-4,'msg':'no return','arg':q}, 500)

if __name__ == '__main__':
	app.run(debug=True)
