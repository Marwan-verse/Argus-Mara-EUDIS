import assert from 'node:assert/strict';
import test from 'node:test';
import {applyFeedStatus,applySnapshot,applyUpdate,createStore,normalizeVessel,project,unproject,zoomAt}
  from '../ui/live/live.mjs';

const observed={mmsi:'250000001',name:'TEST VESSEL',lat:53.2,lon:-6.1,
  sog_kn:8.5,cog_deg:40,received_utc:'2026-10-08T12:00:00Z',label:'simulated'};
const snapshot=(sequence=1,stream_id='test-stream',vessels=[observed])=>({
  schema_version:1,stream_id,sequence,generated_utc:'2026-10-08T12:00:00Z',
  feed:{status:'live',label:'simulated'},vessels,
});

test('metadata-only contacts remain in the directory without a map position',()=>{
  const store=createStore();
  const metadata={mmsi:'250000002',name:'METADATA ONLY',ship_type:70,ais_length_m:115,
    lat:null,lon:null,received_utc:null,metadata_received_utc:'2026-10-08T12:00:00Z',label:'simulated'};
  assert.equal(applySnapshot(store,snapshot(1,'test-stream',[observed,metadata])),true);
  assert.equal(store.vessels.size,2);
  assert.equal(store.vessels.get(metadata.mmsi).hasPosition,false);
  assert.equal(store.vessels.get(metadata.mmsi).lat,null);
  assert.equal(store.vessels.get(metadata.mmsi).received_ms,null);
  assert.equal(store.vessels.get(metadata.mmsi).ais_length_m,115);
  assert.equal([...store.vessels.values()].filter(v=>v.hasPosition).length,1);
});

test('duplicate or older events cannot replace current observations',()=>{
  const store=createStore();applySnapshot(store,snapshot(10));
  const update={stream_id:'test-stream',sequence:11,feed:{status:'live'},
    upserts:[{...observed,lat:54,received_utc:'2026-10-08T12:01:00Z'}],removals:[]};
  assert.equal(applyUpdate(store,update),'applied');
  assert.equal(applyUpdate(store,{...update,upserts:[observed]}),'old');
  assert.equal(applySnapshot(store,snapshot(10)),false);
  assert.equal(store.vessels.get(observed.mmsi).lat,54);
  assert.equal(store.sequence,11);
});

test('restarting the stream replaces its entire snapshot and accepts lower sequence',()=>{
  const store=createStore();applySnapshot(store,snapshot(80));
  assert.equal(applyUpdate(store,{stream_id:'new-stream',sequence:1,upserts:[],removals:[]}),'resync');
  assert.equal(store.vessels.size,1);
  assert.equal(applySnapshot(store,snapshot(0,'new-stream',[])),true);
  assert.equal(store.vessels.size,0);
  assert.equal(store.streamId,'new-stream');
  assert.equal(store.sequence,0);
});

test('upserts preserve reception order and removals clear expired contacts',()=>{
  const store=createStore();applySnapshot(store,snapshot());
  assert.equal(applyUpdate(store,{stream_id:'test-stream',sequence:2,upserts:[
    {...observed,lat:55,received_utc:'2026-10-08T11:59:00Z'},
  ],removals:[]}),'applied');
  assert.equal(store.vessels.get(observed.mmsi).lat,observed.lat);
  assert.equal(applyUpdate(store,{stream_id:'test-stream',sequence:3,upserts:[],removals:[observed.mmsi]}),'applied');
  assert.equal(store.vessels.size,0);
});

test('a status heartbeat cannot advance the vessel sequence past an undelivered update',()=>{
  const store=createStore();applySnapshot(store,snapshot(1));
  assert.equal(applyFeedStatus(store,{stream_id:'test-stream',sequence:2,feed:{status:'reconnecting'}}),true);
  assert.equal(store.sequence,1);
  assert.equal(store.feed.status,'reconnecting');
  assert.equal(applyUpdate(store,{stream_id:'test-stream',sequence:2,upserts:[
    {...observed,lat:54,received_utc:'2026-10-08T12:01:00Z'},
  ],removals:[]}),'applied');
  assert.equal(store.vessels.get(observed.mmsi).lat,54);
  assert.equal(applyFeedStatus(store,{stream_id:'different-stream',sequence:3,feed:{status:'stopped'}}),false);
  assert.equal(store.feed.status,'reconnecting');
});

test('missing AIS fields and unavailable sentinels remain unavailable',()=>{
  const vessel=normalizeVessel({...observed,sog_kn:102.3,cog_deg:360});
  assert.equal(vessel.sog_kn,null);assert.equal(vessel.cog_deg,null);
  assert.equal(normalizeVessel({...observed,lat:91}).hasPosition,false);
  assert.equal(normalizeVessel({...observed,received_utc:null}).hasPosition,false);
  assert.equal(normalizeVessel({...observed,label:'fictional'}),null);
  assert.equal(normalizeVessel({...observed,sog_kn:0,cog_deg:0}).sog_kn,0);
});

test('scroll zoom keeps the observed geographic point under the pointer and respects limits',()=>{
  const [x,y]=project(-7,53),view={x,y,scale:30000,minScale:100,maxScale:60000000};
  const width=800,height=550,px=170,py=210;
  const before=unproject(view.x+(px-width/2)/view.scale,view.y+(py-height/2)/view.scale);
  zoomAt(view,1.8,px,py,width,height);
  const after=unproject(view.x+(px-width/2)/view.scale,view.y+(py-height/2)/view.scale);
  assert.ok(Math.abs(before[0]-after[0])<1e-10);
  assert.ok(Math.abs(before[1]-after[1])<1e-10);
  zoomAt(view,1e10,width/2,height/2,width,height);assert.equal(view.scale,view.maxScale);
  zoomAt(view,1e-10,width/2,height/2,width,height);assert.equal(view.scale,view.minScale);
});
