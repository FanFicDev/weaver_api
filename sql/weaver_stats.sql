\timing on

select l.id, l.key, count(r.id), count(r.id) / 300.0 as qps
from weaver_request_log r
join weaver_limiter l on l.id = r.lid
where created >= (now() - (interval '300 seconds'))
group by l.id;

select * from weaver_request_log order by id desc limit 15;

