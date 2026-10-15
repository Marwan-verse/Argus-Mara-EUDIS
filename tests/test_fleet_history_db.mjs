// Execute the actual migration against an isolated in-memory PostgreSQL engine.
// npm install --prefix data/sql-test-runtime @electric-sql/pglite
// node tests/test_fleet_history_db.mjs
// No credentials or hosted database are used. The base fixture contains only
// the prior tables/columns this migration reads; it does not test AIS ingestion
// or PostGIS, nor multi-connection SKIP LOCKED contention.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const modulePath = process.env.ARGUS_PGLITE_MODULE || path.join(root, 'data/sql-test-runtime/node_modules/@electric-sql/pglite/dist/index.js');
const { PGlite } = await import(pathToFileURL(modulePath));
const db = new PGlite();
const version = 'fleet-received-history-v1';
const rpc = async (fn, placeholders, values = []) => (await db.query(`select public.${fn}(${placeholders}) as result`, values)).rows[0].result;
const result = (job) => ({mmsi: job.mmsi, version, completed: true, rows_checked: job.expected_rows,
  status: 'no_rule_cues', review_required: false, findings: []});
try {
  await db.exec(`
    create role anon;
    create role authenticated;
    create role service_role;
    create schema argus;
    revoke all on schema argus from public;
    grant usage on schema argus to service_role;
    create table argus.ais_positions (
      mmsi text not null, received_utc timestamptz not null, lat float8, lon float8,
      sog_kn real, cog_deg real, stream_id text, label text, timestamp_source text,
      primary key (mmsi, received_utc));
    create table argus.ais_static (
      mmsi text not null, field text not null, received_utc timestamptz not null, value text,
      primary key (mmsi, field, received_utc));
    create table argus.ais_sync_state (id smallint primary key, last_ok_utc timestamptz,
                                      last_error text, last_error_utc timestamptz);
    insert into argus.ais_sync_state values (1, now(), null, null);
    insert into argus.ais_positions values
      ('111111111', now()-interval '4 hours', 53, -7, 5, 0, 'epoch-a', 'real', 'received_time_assumption');
  `);
  await db.exec(await readFile(path.join(root, 'supabase/migrations/20261015201441_vessel_history_queue.sql'), 'utf8'));
  assert.equal((await rpc('argus_history_index', '')).summary.total_vessels, 1, 'preexisting fleet is queued');
  assert.ok((await rpc('argus_history_index', '')).summary.last_sync_utc);
  await db.exec("update argus.ais_sync_state set last_error='Synthetic source error',last_error_utc=now()+interval '1 second'");
  assert.equal((await rpc('argus_history_index', '')).summary.sync_error, 'Synthetic source error');
  await db.exec("update argus.ais_sync_state set last_ok_utc=now()+interval '2 seconds'");
  assert.equal((await rpc('argus_history_index', '')).summary.sync_error, null, 'a recovered sync does not retain a misleading active error');
  await db.exec(`
    insert into argus.ais_positions
    select '111111111', now()-interval '2 hours'+g*interval '1 second', 53, -7, 5, 0,
      'epoch-a', 'real', 'received_time_assumption' from generate_series(1, 1001) g;
    insert into argus.ais_static values ('222222222','name',now()-interval '1 hour','STATIC ONLY');
  `);
  const revision = (await db.query("select revision from argus.vessel_history_checks where mmsi='111111111'")).rows[0].revision;
  await db.exec(`insert into argus.ais_positions
    select * from argus.ais_positions where mmsi='111111111' order by received_utc limit 1
    on conflict do nothing;`);
  assert.equal((await db.query("select revision from argus.vessel_history_checks where mmsi='111111111'")).rows[0].revision,
    revision, 'duplicate reception does not dirty the history');
  const first = (await rpc('argus_history_claim', '$1', [version])).job;
  assert.equal(first.mmsi, '111111111');
  assert.equal(first.expected_rows, 1002);
  await assert.rejects(rpc('argus_history_claim', '$1', ['unknown-rule-version']), /Unsupported history/);
  const second = (await rpc('argus_history_claim', '$1', [version])).job;
  assert.equal(second.mmsi, '222222222', 'an actively leased vessel is not claimed twice');
  assert.equal((await rpc('argus_history_claim', '$1', [version])).job, null);
  const page = await rpc('argus_history_page', '$1,$2', [first.token, null]);
  assert.equal(page.rows.length, 1000);
  assert.equal(page.has_more, true);
  assert.deepEqual(await rpc('argus_history_page', '$1,$2', [first.token, null]), page, 'lost page response can be retried exactly');
  await db.exec(`insert into argus.ais_positions
    (mmsi,received_utc,lat,lon,sog_kn,cog_deg,stream_id,label,timestamp_source)
    values ('111111111',now()-interval '3 hours',53,-7,5,0,'epoch-a','real','received_time_assumption');`);
  const tail = await rpc('argus_history_page', '$1,$2', [first.token, page.next_after]);
  assert.equal(tail.rows.length, 2, 'late old-timestamp evidence stays outside the claimed revision');
  assert.equal(tail.has_more, false);
  await assert.rejects(rpc('argus_history_finish', '$1,$2', [first.token, {...result(first), rows_checked: 1001}]), /Incomplete/);
  await assert.rejects(rpc('argus_history_finish', '$1,$2', [first.token, {...result(first), completed: 'true'}]), /Incomplete/);
  await assert.rejects(rpc('argus_history_finish', '$1,$2', [first.token, {...result(first), review_required: 'false'}]), /Incomplete/);
  assert.equal((await rpc('argus_history_finish', '$1,$2', [first.token, result(first)])).saved, true);
  assert.equal((await rpc('argus_history_finish', '$1,$2', [first.token, result(first)])).already_saved, true);
  let index = await rpc('argus_history_index', '$1,$2,$3', ['', 1, false]);
  assert.equal(index.vessels.length, 1);
  assert.equal(index.next_after, first.mmsi);
  assert.equal(index.vessels[0].new_evidence_pending, true);
  assert.equal(index.summary.never_checked, 1);
  assert.equal((await rpc('argus_history_index', '$1,$2,$3', [index.next_after, 1, false])).vessels[0].mmsi, second.mmsi);
  assert.equal((await rpc('argus_history_index', '$1,$2,$3', ['', 100, true])).vessels.length, 0);
  await db.exec("update argus.vessel_history_checks set lease_until=now()-interval '1 second' where mmsi='222222222'");
  assert.equal((await rpc('argus_history_page', '$1,$2', [second.token, null])).lease_expired, true);
  const again = (await rpc('argus_history_claim', '$1', [version])).job;
  assert.equal(again.mmsi, second.mmsi, 'never-checked vessels precede changed histories');
  assert.notEqual(again.token, second.token);
  const empty = await rpc('argus_history_page', '$1,$2', [again.token, null]);
  assert.deepEqual(empty.rows, []);
  assert.equal(empty.next_after, null);
  await rpc('argus_history_finish', '$1,$2', [again.token, {...result(again), status: 'insufficient_history'}]);
  const changed = (await rpc('argus_history_claim', '$1', [version])).job;
  assert.equal(changed.expected_rows, 1003);
  await db.exec("delete from argus.ais_positions where mmsi='111111111' and received_utc=(select min(received_utc) from argus.ais_positions where mmsi='111111111')");
  assert.equal((await rpc('argus_history_finish', '$1,$2', [changed.token, result(changed)])).snapshot_changed, true,
    'retention cannot turn a partial snapshot into a completed check');
  const held = (await rpc('argus_history_claim', '$1', [version])).job;
  assert.equal((await rpc('argus_history_release', '$1,$2', [held.token, 'Synthetic incomplete history'])).released, true);
  assert.equal((await rpc('argus_history_claim', '$1', [version])).job, null, 'incomplete work backs off without being marked checked');
  assert.equal((await rpc('argus_history_index', '')).vessels.find(v => v.mmsi === held.mmsi).last_error, 'Synthetic incomplete history');
  for (const role of ['anon', 'authenticated']) {
    await db.exec(`set role ${role}`);
    try {
      await assert.rejects(rpc('argus_history_index', ''), /permission denied/);
      await assert.rejects(db.query('select * from argus.vessel_history_checks'), /permission denied/);
    } finally { await db.exec('reset role'); }
  }
  await db.exec('set role service_role');
  try { assert.equal((await rpc('argus_history_index', '')).summary.total_vessels, 2); }
  finally { await db.exec('reset role'); }
  assert.equal((await db.query("select relrowsecurity from pg_class where oid='argus.vessel_history_checks'::regclass")).rows[0].relrowsecurity, true);
  console.log('Fleet history SQL passed: backfill, revisions, leases, pagination, retries, incomplete snapshots, retention and role restrictions.');
} finally { await db.close(); }
