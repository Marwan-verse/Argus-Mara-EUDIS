/* Shared AIS observations. No forecast, synthetic fallback or alert calculation. */
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const timestamp=value=>typeof value==='string'&&Number.isFinite(Date.parse(value))?Date.parse(value):null;

export function normalizeVessel(raw) {
  if (!raw || !['real','simulated'].includes(raw.label) || !raw.mmsi) return null;
  const hasPosition=finite(raw.lat)&&finite(raw.lon)&&raw.lat>=-90&&raw.lat<=90
    &&raw.lon>=-180&&raw.lon<=180&&timestamp(raw.received_utc)!==null;
  return {
    mmsi:String(raw.mmsi), name:typeof raw.name==='string'?raw.name.trim():'',
    type:raw.ship_type??raw.type??null, hasPosition,
    ais_length_m:finite(raw.ais_length_m)&&raw.ais_length_m>0?raw.ais_length_m:null,
    metadata_received_utc:timestamp(raw.metadata_received_utc)!==null?raw.metadata_received_utc:null,
    lat:hasPosition?raw.lat:null, lon:hasPosition?raw.lon:null,
    sog_kn:finite(raw.sog_kn)&&raw.sog_kn>=0&&raw.sog_kn<102.3?raw.sog_kn:null,
    cog_deg:finite(raw.cog_deg)&&raw.cog_deg>=0&&raw.cog_deg<360?raw.cog_deg:null,
    received_utc:hasPosition?raw.received_utc:null, received_ms:hasPosition?timestamp(raw.received_utc):null, label:raw.label,
  };
}

export const createStore=()=>({streamId:null,sequence:-1,vessels:new Map(),feed:{},generatedUtc:null});

export function applySnapshot(store,payload) {
  if (!payload || payload.schema_version!==1 || typeof payload.stream_id!=='string'
      || !Number.isInteger(payload.sequence) || !Array.isArray(payload.vessels)) return false;
  if (store.streamId===payload.stream_id && payload.sequence<store.sequence) return false;
  const vessels=new Map();
  for (const raw of payload.vessels) {const vessel=normalizeVessel(raw);if(vessel)vessels.set(vessel.mmsi,vessel);}
  store.streamId=payload.stream_id;store.sequence=payload.sequence;store.vessels=vessels;
  store.feed=payload.feed&&typeof payload.feed==='object'?{...payload.feed}:{};
  store.generatedUtc=payload.generated_utc??null;
  return true;
}

export function applyUpdate(store,payload) {
  if (!payload || typeof payload.stream_id!=='string' || !Number.isInteger(payload.sequence)) return 'invalid';
  if (store.streamId!==payload.stream_id) return 'resync';
  if (payload.sequence<=store.sequence) return 'old';
  for (const mmsi of Array.isArray(payload.removals)?payload.removals:[]) store.vessels.delete(String(mmsi));
  for (const raw of Array.isArray(payload.upserts)?payload.upserts:[]) {
    const vessel=normalizeVessel(raw);if(!vessel)continue;
    const previous=store.vessels.get(vessel.mmsi);
    const newerPosition=previous?.received_ms!==null&&vessel.received_ms!==null&&vessel.received_ms<previous?.received_ms;
    if (!newerPosition) store.vessels.set(vessel.mmsi,vessel);
  }
  store.sequence=payload.sequence;
  if(payload.feed&&typeof payload.feed==='object')store.feed={...store.feed,...payload.feed};
  return 'applied';
}

export function applyFeedStatus(store,payload) {
  if(!payload?.feed||typeof payload.feed!=='object')return false;
  if(payload.stream_id&&store.streamId&&payload.stream_id!==store.streamId)return false;
  // Status and heartbeat counters are not evidence that vessel upserts arrived.
  store.feed={...store.feed,...payload.feed};
  return true;
}

export function project(lon,lat) {
  const safeLat=Math.max(-85.051129,Math.min(85.051129,lat));
  return [(lon+180)/360,(1-Math.log(Math.tan(Math.PI/4+safeLat*Math.PI/360))/Math.PI)/2];
}
export function unproject(x,y) {
  return [x*360-180,Math.atan(Math.sinh(Math.PI*(1-2*y)))*180/Math.PI];
}
export function zoomAt(view,factor,x,y,width,height) {
  const wx=view.x+(x-width/2)/view.scale,wy=view.y+(y-height/2)/view.scale;
  view.scale=Math.max(view.minScale,Math.min(view.maxScale,view.scale*factor));
  view.x=wx-(x-width/2)/view.scale;view.y=wy-(y-height/2)/view.scale;
  view.y=Math.max(-.2,Math.min(1.2,view.y));
}
