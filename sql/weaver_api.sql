
create table if not exists weaver_limiter (
	id bigserial primary key,
	key text not null,
	capacity double precision,
	flow double precision,
	value double precision,
	lastDrain timestamp,
	unique(key)
);

insert into weaver_limiter(key, capacity, flow, value, lastDrain)
select 'global_anon', 15, .1, 0, now()
where not exists (select 1 from weaver_limiter where key = 'global_anon');

drop function if exists weaver_fill_limiter(text, double precision);
create or replace function weaver_fill_limiter (
	w_key text,
	w_value double precision
) returns double precision
as $$
declare
	shortfall double precision;
	retryAfter timestamp;
begin

	if (select 1 from weaver_limiter wl where wl.key = w_key) is null then
		return 60;
	end if;

	lock table weaver_limiter in exclusive mode;

	select (capacity - (w_value + greatest(0,
			value - (extract(epoch from (now() - lastDrain)) * flow)
		))) / flow
	into shortfall
	from weaver_limiter
	where key = w_key;

	if shortfall < 0 then
		return -1.0 * shortfall;
	end if;

	update weaver_limiter
	set lastDrain = now(),
		value = (w_value + greatest(0,
			value - (extract(epoch from (now() - lastDrain)) * flow)
		))
	where key = w_key;

	return -1.0;
end
$$ LANGUAGE plpgsql;

create table if not exists weaver_request_log (
	id bigserial primary key,
	lid bigint references weaver_limiter(id),
	url text,
	created timestamp
);

create index if not exists
	idx_weaver_request_log_created on weaver_request_log(created);

