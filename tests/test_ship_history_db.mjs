// Isolated PostgreSQL: preserve complete received objects without losing queryable AIS.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {PGlite} from '../data/sql-test-runtime/node_modules/@electric-sql/pglite/dist/index.js';

const db = new PGlite();
try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema argus; create schema cron;
    create table cron.job (jobid bigint, jobname text);
    insert into cron.job values (1, 'argus-ais-retention'), (2, 'argus-ais-sync');
    create function cron.unschedule(bigint) returns boolean language sql as
      'with removed as (delete from cron.job where jobid=$1 returning *) select exists(select 1 from removed)';
    create table argus.ais_positions (mmsi text, received_utc timestamptz, lat float8, lon float8,
      sog_kn real, cog_deg real, heading_deg smallint, nav_status smallint, stream_id text,
      label text, timestamp_source text,
      primary key (mmsi, received_utc));
    create table argus.ais_static (mmsi text, field text, value text, received_utc timestamptz,
      stream_id text, primary key (mmsi, field, received_utc));
    create table argus.ais_sync_state (id int primary key, source_url text);
    insert into argus.ais_sync_state values (1, 'https://example.invalid');
  `);
  await db.exec(await readFile(new URL('../supabase/migrations/20261016130559_preserve_ship_history.sql', import.meta.url), 'utf8'));
  const now = new Date().toISOString();
  const old = new Date(Date.now() - 30*86400000).toISOString();
  const ship = {mmsi:'123456789', label:'real', received_utc:old, lat:53, lon:-6,
    sog_kn:8, cog_deg:90, name:'SYNTHETIC TEST', metadata_received_utc:now,
    destination:'TEST', destination_received_utc:now, imo:'TEST-ONLY', extra:{future_field:'retained'}};
  const packet = {schema_version:1, feed:{label:'real'}, stream_id:'test-stream', sequence:1,
    generated_utc:now, vessels:[ship]};
  const ingest = async value => (await db.query('select argus.ingest_ais_packet($1) as result', [JSON.stringify(value)])).rows[0].result;
  assert.equal((await ingest(packet)).observations_new, 1);
  assert.equal((await ingest(packet)).observations_new, 0, 'exact retry is idempotent');
  const observation = (await db.query('select payload from argus.ais_observations')).rows[0].payload;
  assert.deepEqual(observation, ship, 'retain every supplied field without inventing declarations');
  assert.equal((await ingest({...packet, vessels:[{...ship, imo:'CORRECTION'}]})).observations_new, 1,
    'same position timestamp with changed details retains both observations');
  assert.equal((await db.query('select count(*)::int as n from argus.ais_positions')).rows[0].n, 1);
  assert.equal((await ingest({...packet, vessels:[{mmsi:'987654321', label:'real', name:'METADATA ONLY'}]})).observations_new, 1);
  assert.equal((await ingest({...packet, vessels:[{mmsi:'111111111', label:'simulated'}]})).observations_new, 0);
  assert.equal((await db.query('select argus.ais_retention() as result')).rows[0].result.positions_deleted, 0);
  assert.equal((await db.query('select count(*)::int as n from argus.ais_positions')).rows[0].n, 1,
    'a 30-day-old position survives retention');
  assert.deepEqual((await db.query('select jobname from cron.job')).rows, [{jobname:'argus-ais-sync'}]);
  assert.equal((await db.query("select rowsecurity from pg_tables where schemaname='argus' and tablename='ais_observations'")).rows[0].rowsecurity, true);
  assert.equal((await db.query("select has_table_privilege('anon','argus.ais_observations','select') as allowed")).rows[0].allowed, false);
  const root = fileURLToPath(new URL('..', import.meta.url));
  const python = process.env.ARGUS_PYTHON || (process.platform === 'win32' ? path.join(root,'.venv/Scripts/python.exe') : 'python3');
  const archiveRow = {mmsi:'222222222', msg_type:'ShipStaticData', recv_utc:old,
    stream_id:'test-stream', label:'real', ship_name:"O'Brien'); drop table argus.ais_positions; --",
    present_fields:'name', call_sign:'ORIGINAL-EXTRA'};
  const importedSQL = execFileSync(python, ['-c',
    'import json,sys; from scripts.export_ship_history_sql import prepare,batch_sql; print(batch_sql([prepare(json.load(sys.stdin), "0"*64, "'+now+'")]))'],
    {cwd:root,input:JSON.stringify(archiveRow),encoding:'utf8'});
  assert.equal((await db.query(importedSQL.split('\n').slice(1).join('\n'))).rows[0].observations_added, 1);
  assert.equal((await db.query("select value from argus.ais_static where mmsi='222222222'")).rows[0].value, archiveRow.ship_name);
  assert.deepEqual((await db.query("select payload from argus.ais_observations where mmsi='222222222'")).rows[0].payload, archiveRow);
  assert.equal((await db.query(importedSQL.split('\n').slice(1).join('\n'))).rows[0].observations_added, 0);
  console.log('Ship history preservation, full objects, retries, corrections and access checks passed.');
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await db.close();
}
