// Real PostgreSQL/PostGIS execution, isolated from hosted services and credentials.
// npm install --prefix data/sql-test-runtime @electric-sql/pglite @electric-sql/pglite-postgis
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dependency = name => pathToFileURL(path.join(root, 'data/sql-test-runtime/node_modules/@electric-sql', name, 'dist/index.js'));
const { PGlite } = await import(dependency('pglite'));
const { postgis } = await import(dependency('pglite-postgis'));
const db = new PGlite({ extensions: { postgis } });
const sql = name => readFile(path.join(root, 'supabase/migrations', name), 'utf8');
const ts = '2026-10-15T12:00:00Z';
const evidence = {version:'image-ais-review-v2', image_input_verified:true, clear_footprint_radius_m:100};
const scene = {id:'test-scene',sensor:'Sentinel-2', acquired_utc:ts, bbox:[-6.2,53.2,-6,53.4],source:'test',label:'real',review_evidence:evidence,
  observed_areas:[[-6.2,53.2,-6,53.4]],contacts:[]};
const rpc = async (name, placeholders='', args=[]) => (await db.query(`select public.${name}(${placeholders}) as r`, args)).rows[0].r;
const save = async overrides => rpc('argus_save_scene','$1::jsonb',[JSON.stringify({...scene,...overrides})]);
const compare = () => rpc('argus_compare_scene','$1',['test-scene']);
const contact = (id, lat=53.3, lon=-6.1, extra={}) => ({external_id:id, lat,lon,source:'tensorx_ai',label:'assumption',...extra});
const position = async (mmsi, offset=0, lat=53.3, lon=-6.1, stream='epoch-a', sog=null,cog=null,label='real') => db.query(
  `insert into argus.ais_positions (mmsi,received_utc,lat,lon,sog_kn,cog_deg,nav_status,stream_id,label) values ($1,$2::timestamptz+make_interval(secs=>$3),$4,$5,$6,$7,0,$8,$9)`,[mmsi,ts,offset,lat,lon,sog,cog,stream,label]);
const length = async (mmsi, hours=1, value='100') => db.query(`insert into argus.ais_static (mmsi,field,received_utc,value) values ($1,'length_m',$2::timestamptz-make_interval(hours=>$3),$4)`,[mmsi,ts,hours,value]);
const clear = () => db.exec('truncate argus.ais_positions, argus.ais_static');
try {
  await db.exec(`create role anon; create role authenticated; create role service_role;
    create schema extensions; create extension postgis schema extensions; create schema argus;
    create table argus.ais_positions (mmsi text,received_utc timestamptz,lat float8,lon float8,sog_kn real,cog_deg real,nav_status smallint,stream_id text,label text,timestamp_source text);
    create table argus.ais_static (mmsi text,field text,received_utc timestamptz,value text,stream_id text);
    create table argus.ais_sync_state (id int,last_ok_utc timestamptz,last_error text,last_error_utc timestamptz,stream_id text,sequence bigint);
    create table argus.ais_sync_runs (run_utc timestamptz);
    create schema cron; create function cron.schedule(text,text,text) returns bigint language sql as 'select 1::bigint';`);
  await db.exec(await sql('20261015174759_argus_satellite_compare.sql'));
  await db.exec(await sql('20261015174836_argus_compare_scene_volatile.sql'));
  await db.exec(await sql('20261015221628_align_satellite_ais_comparison.sql'));
  await position('111111111'); await length('111111111'); await save();
  let r=await compare();
  assert.equal(r.counts.ais_vessels_at_acquisition,1,'exact fix requires no speed/course');
  assert.equal(r.ais_not_seen.length,1,'verified clear footprint permits a provisional missing-detection lead');
  assert.match(r.ais_not_seen[0].review,/detection misses/i);
  await save({review_evidence:{}}); r=await compare(); assert.equal(r.ais_not_seen.length,0,'legacy visibility alone is insufficient');
  await save({review_evidence:{...evidence,image_input_verified:'true'}}); r=await compare(); assert.equal(r.ais_not_seen.length,0,'verification must be a JSON boolean');
  await save({review_evidence:{...evidence,clear_footprint_radius_m:0}}); r=await compare(); assert.equal(r.ais_not_seen.length,0,'clear centre alone is insufficient');
  await save(); await db.exec("update argus.sat_observed_areas set quality='cloud'"); r=await compare(); assert.equal(r.ais_not_seen.length,0,'cloudy area cannot support missing detection');
  await save(); await db.exec('update argus.ais_positions set nav_status=5'); r=await compare(); assert.equal(r.ais_not_seen.length,0,'moored vessels withheld');
  await db.exec('update argus.ais_positions set nav_status=0');
  await save({label:'simulated'}); r=await compare(); assert.equal(r.ais_not_seen.length,0);
  await save({contacts:[contact('one'),contact('two',53.3001)]}); r=await compare();
  assert.equal(r.matches.length,1); assert.equal(r.seen_without_ais.length,0,'assignment conflict is not silence');
  await save({contacts:[contact('distant',53.33)]}); r=await compare(); assert.equal(r.seen_without_ais.length,1);
  await save({contacts:[contact('distant',53.33,-6.1,{overlap_ambiguous:true})]});
  r=await compare(); assert.equal(r.seen_without_ais.length,0,'possible overlap duplicates withheld');
  await save({contacts:[]}); r=await compare(); assert.equal(r.counts.image_contacts,0,'republishing replaces obsolete contacts');
  await db.exec('truncate argus.ais_static'); await length('111111111',25); r=await compare(); assert.equal(r.ais_not_seen.length,0,'size expires after 24 hours');
  await db.exec('truncate argus.ais_static'); await length('111111111',1,'null'); r=await compare(); assert.equal(r.ais_not_seen.length,0,'cleared size cannot support negative lead');
  await clear(); await position('111111111',-60,53.299); await position('111111111',60,53.301); await length('111111111');
  r=await compare(); assert.equal(r.ais_not_seen.length,1); assert.equal(r.ais_not_seen[0].ais_position_method,'interpolated');
  await position('111111111',-30,53.3,-6.1,'epoch-b',0,0); r=await compare(); assert.equal(r.counts.ais_vessels_at_acquisition,0,'multiple eligible epochs withheld');
  await clear(); await position('111111111',-60,53.2); await position('111111111',0,53.3); await length('111111111');
  r=await compare(); assert.equal(r.ais_not_seen.length,0,'implausible segment cannot support missing detection');
  await save({contacts:[contact('near')]}); r=await compare(); assert.equal(r.matches.length,0); assert.equal(r.seen_without_ais.length,0,'bad motion is still nearby AIS evidence');
  await clear(); await position('111111111',-120,53.3,-6.1,'epoch-a',10,90); await length('111111111'); await save();
  r=await compare(); assert.equal(r.ais_not_seen[0].ais_position_method,'projected');
  await clear(); await position('111111111',-120,53.3,-6.1,'epoch-a',102.3,360); r=await compare(); assert.equal(r.counts.ais_vessels_at_acquisition,0,'unavailable motion sentinels cannot project');
  await clear(); await position('111111111',-301,53.3,-6.1,'epoch-a',10,90); r=await compare(); assert.equal(r.counts.ais_vessels_at_acquisition,0,'old fix cannot project');
  await clear(); await position('111111111',30,53.3,-6.1,'epoch-a',10,90); r=await compare(); assert.equal(r.counts.ais_vessels_at_acquisition,0,'future fix cannot backdate');
  await clear(); await position('111111111',0,53.3,-6.1,'epoch-a',null,null,'simulated');
  await save({contacts:[contact('near')]}); r=await compare(); assert.equal(r.matches.length,0); assert.equal(r.seen_without_ais.length,0,'no genuine regional AIS means cannot judge');
  await assert.rejects(rpc('argus_compare_scene',"$1, 'NaN'::float8",['test-scene']),/invalid comparison/);
  for(const role of ['anon','authenticated']) {
    await db.exec(`set role ${role}`);
    await assert.rejects(compare(),/permission denied/);
    await assert.rejects(save(),/permission denied/);
    await db.exec('reset role');
  }
  console.log('PASS: actual satellite comparison migrations, PostGIS joins, provenance, motion, ambiguity, expiry and role restrictions');
} catch (error) {
  console.error(error.message, error.detail || '', error.where || '', error.stack?.split('\n').slice(1,4).join('\n') || '');
  process.exitCode = 1;
} finally { await db.close(); }
