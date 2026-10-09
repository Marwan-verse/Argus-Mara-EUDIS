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

const count=value=>new Intl.NumberFormat('en-GB').format(value);
const dateFormat=new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
const utc=value=>timestamp(value)!==null?dateFormat.format(new Date(value)).replace(',','')+' UTC':'Not yet received';
const compactUtc=value=>timestamp(value)!==null?new Date(value).toISOString().slice(11,19)+' UTC':'Not yet received';
export function ageText(receivedMs,now=Date.now()) {
  if(!finite(receivedMs))return'—';
  const seconds=Math.max(0,Math.floor((now-receivedMs)/1000));
  if(seconds<60)return seconds+' s';
  const minutes=Math.floor(seconds/60);if(minutes<60)return minutes+' min';
  const hours=Math.floor(minutes/60);if(hours<24)return hours+' h '+minutes%60+' min';
  return Math.floor(hours/24)+' d '+hours%24+' h';
}
const vesselName=vessel=>vessel.name||'Name unavailable';
function vesselType(type) {
  if(typeof type==='string'&&type.trim())return type;
  if(!finite(type)||type===0)return'Type unavailable';
  if(type>=70&&type<=79)return'Cargo';if(type>=80&&type<=89)return'Tanker';
  if(type>=60&&type<=69)return'Passenger';if(type>=40&&type<=49)return'High-speed craft';
  return ({30:'Fishing',31:'Towing',32:'Towing',33:'Dredging / underwater operations',34:'Diving operations',35:'Military operations',36:'Sailing',37:'Pleasure craft',50:'Pilot',51:'Search and rescue',52:'Tug',53:'Port tender',54:'Anti-pollution',55:'Law enforcement',58:'Medical transport',59:'Noncombatant ship'})[type]||'AIS type '+type;
}

function startDashboard() {
  const $=id=>document.getElementById(id),store=createStore(),canvas=$('map'),ctx=canvas.getContext('2d');
  const view={x:.47,y:.32,scale:1000,minScale:100,maxScale:60000000};
  let width=0,height=0,dpr=1,landLevels={},ports=[],landFailed=false,selected=null,listLimit=90;
  let connected=false,initialReceived=false,renderPending=false,backgroundDirty=true,markers=[];
  let eventSource=null,snapshotPending=null,retryTimer=null,latestStatus='Connecting';
  const background=document.createElement('canvas'),bctx=background.getContext('2d'),rowNodes=new Map();
  const text=(id,value)=>{if($(id).textContent!==value)$(id).textContent=value;};
  const shipSVG='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><path d="m10 2 5 13-5-2-5 2 5-13Z"/><path d="M3 17c1 0 1 .8 2 .8s1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8 1-.8 2-.8 1 .8 2 .8"/></svg>';
  const nowMs=()=>Date.now();
  function connection(isConnected,description) {
    connected=isConnected;latestStatus=description;
    $('connection-pill').classList.toggle('connected',isConnected);
    $('connection-pill').classList.toggle('disconnected',!isConnected&&description!=='Connecting');
    text('connection-text',description);
  }
  function feedState() {
    const status=String(store.feed.status||'starting').toLowerCase();
    const received=timestamp(store.feed.last_received_utc),quiet=received!==null&&nowMs()-received>120000;
    const states={
      no_key:['Waiting for feed','Shared service ready; AIS feed has not started'],
      disabled:['Feed paused','No provider feed is running'],
      starting:['Starting feed','Waiting for the first AIS message'],
      connecting:['Connecting feed','Connecting to the AIS provider'],
      waiting:['Waiting for AIS','No AIS message has been received yet'],
      connected:['Feed connected','Provider connection is established'],
      live:['Receiving AIS','Messages received from the shared provider feed'],
      streaming:['Receiving AIS','Messages received from the shared provider feed'],
      receiving:['Receiving AIS','Messages received from the shared provider feed'],
      disconnected:['Feed interrupted','Retaining the last received observations'],
      reconnecting:['Feed reconnecting','Retaining the last received observations'],
      backoff:['Feed reconnecting','Waiting before reconnecting to the provider'],
      error:['Feed interrupted','The shared feed is currently unavailable'],
      stopped:['Feed stopped','Retaining the last received observations'],
      rate_limited:['Feed waiting','The provider connection is temporarily limited'],
      auth_error:['Feed unavailable','The AIS provider has not authorised the connection'],
      archive_error:['Recording unavailable','The shared recorder reported a storage problem'],
      stopping:['Feed stopping','Retaining the last received observations'],
    };
    let result=states[status]||['Feed status unknown','Waiting for a reported provider status'];
    if(quiet&&['connected','live','streaming','receiving'].includes(status))result=['Feed quiet','No AIS message received in the last two minutes'];
    return result;
  }
  function renderMetrics() {
    const contacts=[...store.vessels.values()],vessels=contacts.filter(v=>v.hasPosition),real=vessels.filter(v=>v.label==='real').length,simulated=vessels.length-real;
    text('metric-vessels',count(vessels.length));
    text('metric-source',contacts.length?count(contacts.length)+' contacts · '+(simulated?count(simulated)+' simulated positions':count(real)+' real positions'):'No positions received');
    $('feed-label').hidden=store.feed.label!=='simulated';$('feed-label').classList.toggle('simulated',store.feed.label==='simulated');
    text('map-subtitle',store.feed.label==='simulated'?'Simulated test source · received positions':'Latest received AIS positions');
    const [status,description]=feedState();
    text('metric-feed',initialReceived?status:'Connecting');text('feed-description',initialReceived?description:'Checking the shared service');
    let latestPosition=store.feed.last_position_utc;
    if(timestamp(latestPosition)===null&&vessels.length)latestPosition=new Date(Math.max(...vessels.map(v=>v.received_ms))).toISOString();
    text('metric-message-age',ageText(timestamp(store.feed.last_received_utc)));
    text('metric-message-time',compactUtc(store.feed.last_received_utc));
    text('metric-position-age',ageText(timestamp(latestPosition)));text('metric-position-time',compactUtc(latestPosition));
    $('simulated-legend').hidden=!simulated&&store.feed.label!=='simulated';
    $('map-empty').hidden=Boolean(vessels.length);
    text('empty-title',!connected&&initialReceived?'Connection interrupted':'Waiting for received positions');
    text('empty-description',!connected&&initialReceived?'The display will reconnect automatically. No vessel positions have been received yet.':store.feed.label==='simulated'?'This service is using an explicitly simulated test source. Its received test positions will appear here.':store.feed.status==='no_key'?'The shared service is ready. Vessel markers will appear when the AIS feed starts.':'The map will show AIS observations as the shared feed receives them.');
  }
  function renderDirectory() {
    const query=$('search').value.trim().toLocaleLowerCase('en-GB');
    const filtered=[...store.vessels.values()].filter(v=>(v.name+' '+v.mmsi).toLocaleLowerCase('en-GB').includes(query))
      .sort((a,b)=>vesselName(a).localeCompare(vesselName(b),'en-GB')||a.mmsi.localeCompare(b.mmsi));
    text('directory-count',count(filtered.length)+(query?' matches':' vessels'));
    $('no-results').hidden=Boolean(filtered.length)||!store.vessels.size;
    const list=$('vessel-list'),visible=filtered.slice(0,listLimit),ids=new Set(visible.map(v=>v.mmsi));
    for(const [id,row] of rowNodes){if(!ids.has(id)){row.button.remove();rowNodes.delete(id);}}
    let previous=null;
    for(const vessel of visible) {
      let row=rowNodes.get(vessel.mmsi);
      if(!row){
        const button=document.createElement('button');button.className='vessel-row';button.dataset.mmsi=vessel.mmsi;
        const icon=document.createElement('span');icon.className='vessel-symbol';icon.innerHTML=shipSVG;
        const words=document.createElement('span');words.className='vessel-text';
        const name=document.createElement('div');name.className='vessel-name';
        const id=document.createElement('div');id.className='vessel-id mono';words.append(name,id);
        const age=document.createElement('span');age.className='vessel-age mono';button.append(icon,words,age);
        button.addEventListener('click',()=>selectVessel(vessel.mmsi));row={button,name,id,age};rowNodes.set(vessel.mmsi,row);
      }
      row.name.textContent=vesselName(vessel);row.id.textContent=vessel.mmsi+(vessel.label==='simulated'?' · Simulated':'');
      row.age.textContent=vessel.hasPosition?ageText(vessel.received_ms):'No position';row.button.classList.toggle('selected',selected===vessel.mmsi);
      row.button.classList.toggle('simulated',vessel.label==='simulated');row.button.setAttribute('aria-pressed',String(selected===vessel.mmsi));
      const next=previous?previous.nextSibling:list.firstChild;
      if(next!==row.button)list.insertBefore(row.button,next);previous=row.button;
    }
    $('show-more').hidden=filtered.length<=listLimit;
    text('show-more','Show more · '+count(Math.max(0,filtered.length-listLimit))+' remaining');
  }
  function renderSelection() {
    const vessel=store.vessels.get(selected);$('selection').hidden=!vessel;
    if(!vessel){selected=null;return;}
    text('selected-name',vesselName(vessel));text('selected-source',vessel.label==='real'?'Real AIS':'Simulated');
    $('selected-source').classList.toggle('simulated',vessel.label==='simulated');
    text('selected-mmsi','MMSI '+vessel.mmsi);text('selected-type',vesselType(vessel.type)+(vessel.ais_length_m!==null?' · '+vessel.ais_length_m.toFixed(1)+' m':''));
    text('selected-time',vessel.hasPosition?utc(vessel.received_utc):'No position received');text('selected-age',vessel.hasPosition?'Observation age: '+ageText(vessel.received_ms):'Metadata only contact');
    text('selected-coordinates',vessel.hasPosition?Math.abs(vessel.lat).toFixed(5)+'°'+(vessel.lat>=0?'N':'S')+' · '+Math.abs(vessel.lon).toFixed(5)+'°'+(vessel.lon>=0?'E':'W'):'Position unavailable');
    text('selected-speed',!vessel.hasPosition||vessel.sog_kn===null?'Unavailable':vessel.sog_kn.toFixed(1)+' kn');
    text('selected-course',!vessel.hasPosition||vessel.cog_deg===null?'Unavailable':vessel.cog_deg.toFixed(1)+'°');
    $('center-selected').disabled=!vessel.hasPosition;
  }
  function selectVessel(mmsi) {selected=mmsi;renderSelection();renderDirectory();scheduleDraw();}
  function renderState() {renderMetrics();renderDirectory();renderSelection();scheduleDraw();}
  let stateRenderTimer=null;
  function changed() {if(!stateRenderTimer)stateRenderTimer=setTimeout(()=>{stateRenderTimer=null;renderState();},120);}

  async function snapshot() {
    if(snapshotPending)return snapshotPending;
    snapshotPending=(async()=>{
      const response=await fetch('/api/v1/vessels',{cache:'no-store',headers:{Accept:'application/json'}});
      if(!response.ok)throw new Error('Snapshot unavailable');
      const payload=await response.json();
      if(applySnapshot(store,payload)){initialReceived=true;changed();}
      else if(!initialReceived)throw new Error('Invalid snapshot');
    })().finally(()=>{snapshotPending=null;});
    return snapshotPending;
  }
  const parseEvent=event=>{try{return JSON.parse(event.data);}catch{return null;}};
  function connectEvents() {
    if(eventSource)return;
    eventSource=new EventSource('/api/v1/events');
    eventSource.onopen=()=>{connection(true,'Shared service connected');if(!initialReceived)snapshot().catch(()=>{});renderMetrics();};
    eventSource.onerror=()=>{connection(false,'Reconnecting');renderMetrics();};
    eventSource.addEventListener('snapshot',event=>{const payload=parseEvent(event);if(applySnapshot(store,payload)){initialReceived=true;connection(true,'Shared service connected');changed();}});
    eventSource.addEventListener('update',event=>{
      const payload=parseEvent(event),previous=store.sequence,result=applyUpdate(store,payload);
      if(result==='resync'){snapshot().catch(()=>{});return;}
      if(result==='applied'){
        initialReceived=true;connection(true,'Shared service connected');changed();
        if(payload.sequence>previous+1)snapshot().catch(()=>{});
      }
    });
    eventSource.addEventListener('status',event=>{
      const payload=parseEvent(event);if(!payload)return;
      if(payload.stream_id&&store.streamId&&payload.stream_id!==store.streamId){snapshot().catch(()=>{});return;}
      applyFeedStatus(store,payload);
      initialReceived=true;connection(true,'Shared service connected');changed();
    });
    eventSource.addEventListener('heartbeat',event=>{
      const payload=parseEvent(event);applyFeedStatus(store,payload);
      connection(true,'Shared service connected');renderMetrics();
    });
  }
  async function initializeConnection() {
    try{await snapshot();}catch{connection(false,'Service unavailable');}
    connectEvents();
    retryTimer=setInterval(()=>{if(!initialReceived)snapshot().catch(()=>{});},10000);
  }

  function fitBounds(bounds,pad=52) {
    const a=project(bounds[0],bounds[3]),b=project(bounds[2],bounds[1]);
    view.x=(a[0]+b[0])/2;view.y=(a[1]+b[1])/2;
    view.scale=Math.max(view.minScale,Math.min(view.maxScale,Math.min(Math.max(80,width-pad*2)/Math.max(.00005,b[0]-a[0]),Math.max(80,height-pad*2)/Math.max(.00005,b[1]-a[1]))));
    backgroundDirty=true;scheduleDraw();
  }
  function fitIreland(){fitBounds([-17,49,-4.5,57.5]);}
  function fitWorld(){fitBounds([-180,-68,180,82],25);}
  function fitVessels(){const values=[...store.vessels.values()].filter(v=>v.hasPosition);if(!values.length){fitIreland();return;}fitBounds([Math.min(...values.map(v=>v.lon)),Math.min(...values.map(v=>v.lat)),Math.max(...values.map(v=>v.lon)),Math.max(...values.map(v=>v.lat))]);}
  function zoom(factor,x=width/2,y=height/2){zoomAt(view,factor,x,y,width,height);backgroundDirty=true;scheduleDraw();}
  function centerSelected(){const vessel=store.vessels.get(selected);if(!vessel?.hasPosition)return;[view.x,view.y]=project(vessel.lon,vessel.lat);view.scale=Math.max(view.scale,50000);backgroundDirty=true;scheduleDraw();}
  function resize(){const rect=$('map-area').getBoundingClientRect(),first=!width;dpr=Math.min(2,window.devicePixelRatio||1);width=rect.width;height=rect.height;canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);view.minScale=Math.max(100,width*.7);backgroundDirty=true;if(first)fitIreland();else scheduleDraw();}
  new ResizeObserver(resize).observe($('map-area'));
  function landRing(ring) {
    const points=[];let previous=null;
    for(const p of ring){if(!Array.isArray(p)||!finite(p[0])||!finite(p[1]))continue;let [x,y]=project(p[0],p[1]);if(previous!==null)x+=Math.round(previous-x);points.push([x,y]);previous=x;}
    if(points.length<3)return null;
    return {points,bounds:[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]};
  }
  async function loadAssets() {
    const results=await Promise.allSettled([
      fetch('/assets/world_land.json').then(r=>{if(!r.ok)throw new Error('Coastline unavailable');return r.json();}),
      fetch('/assets/world_ports.json').then(r=>{if(!r.ok)throw new Error('Ports unavailable');return r.json();}),
    ]);
    if(results[0].status==='fulfilled'){
      for(const [level,rings] of Object.entries(results[0].value.levels||{}))landLevels[level]=rings.map(landRing).filter(Boolean);
      landFailed=!Object.keys(landLevels).length;
    }else landFailed=true;
    if(results[1].status==='fulfilled')ports=results[1].value.ports||[];
    else{$('show-ports').disabled=true;$('show-ports').title='Reference ports unavailable';}
    backgroundDirty=true;scheduleDraw();
  }
  function renderBackground() {
    background.width=canvas.width;background.height=canvas.height;bctx.setTransform(dpr,0,0,dpr,0,0);
    bctx.fillStyle='#e9f3f8';bctx.fillRect(0,0,width,height);
    const x0=view.x-width/2/view.scale,x1=view.x+width/2/view.scale,y0=view.y-height/2/view.scale,y1=view.y+height/2/view.scale;
    const span=(x1-x0)*360,step=[.01,.02,.05,.1,.2,.5,1,2,5,10,15,30,45,90].find(s=>s>=span/7)||90;
    bctx.strokeStyle='#d3e2eb';bctx.lineWidth=.6;bctx.font='9px Consolas,monospace';bctx.fillStyle='#87a0b0';
    for(let lon=Math.ceil((x0*360-180)/step)*step;lon<=x1*360-180;lon+=step){const x=((lon+180)/360-view.x)*view.scale+width/2;bctx.beginPath();bctx.moveTo(x,0);bctx.lineTo(x,height);bctx.stroke();if(x>40&&x<width-30){const label=((lon+180)%360+360)%360-180;bctx.fillText(Math.abs(label).toFixed(step<1?2:0)+'°'+(label>=0?'E':'W'),x+3,height-45);}}
    const low=unproject(0,y1)[1],high=unproject(0,y0)[1];
    for(let lat=Math.ceil(low/step)*step;lat<=high;lat+=step){if(Math.abs(lat)>85)continue;const y=(project(0,lat)[1]-view.y)*view.scale+height/2;bctx.beginPath();bctx.moveTo(0,y);bctx.lineTo(width,y);bctx.stroke();if(y>50&&y<height-50)bctx.fillText(Math.abs(lat).toFixed(step<1?2:0)+'°'+(lat>=0?'N':'S'),7,y-4);}
    bctx.fillStyle='#fcfdfd';bctx.strokeStyle='#acbfcc';bctx.lineWidth=.8;
    const rings=landLevels[span>35?'110m':'50m']||landLevels['110m']||[];
    for(const ring of rings){const bb=ring.bounds,baseShift=Math.round(view.x-(bb[0]+bb[2])/2);if(bb[3]<y0||bb[1]>y1)continue;
      for(const offset of [-1,0,1]){const shift=baseShift+offset;if(bb[2]+shift<x0||bb[0]+shift>x1)continue;bctx.beginPath();ring.points.forEach((p,i)=>{const x=(p[0]+shift-view.x)*view.scale+width/2,y=(p[1]-view.y)*view.scale+height/2;i?bctx.lineTo(x,y):bctx.moveTo(x,y);});bctx.closePath();bctx.fill();bctx.stroke();}}
    if($('show-ports').checked){
      bctx.fillStyle='#497c8b';const clusters=new Map();
      for(const port of ports){let [x,y]=project(port[3],port[2]);x+=Math.round(view.x-x);x=(x-view.x)*view.scale+width/2;y=(y-view.y)*view.scale+height/2;if(x<0||x>width||y<0||y>height)continue;
        if(span>30){const key=Math.floor(x/30)+':'+Math.floor(y/30),group=clusters.get(key)||[0,0,0];group[0]+=x;group[1]+=y;group[2]++;clusters.set(key,group);}
        else{bctx.beginPath();bctx.arc(x,y,2.2,0,Math.PI*2);bctx.fill();}}
      for(const [sx,sy,total] of clusters.values()){const x=sx/total,y=sy/total;bctx.beginPath();bctx.arc(x,y,total>1?6:2.5,0,Math.PI*2);bctx.fill();if(total>1){bctx.fillStyle='#fff';bctx.font='8px Arial';bctx.textAlign='center';bctx.fillText(String(total),x,y+2.5);bctx.textAlign='left';bctx.fillStyle='#497c8b';}}
    }
    const lat=unproject(view.x,view.y)[1],km=65/view.scale*40075*Math.max(.001,Math.cos(lat*Math.PI/180));
    text('map-scale-text',km>=1?km.toLocaleString('en-GB',{maximumFractionDigits:km>20?0:1})+' km':Math.round(km*1000)+' m');
    text('map-attribution',landFailed?'Coastline unavailable':$('show-ports').checked?'Natural Earth · NGA ports':'Natural Earth · public domain');
    backgroundDirty=false;
  }
  function drawMarker(vessel,x,y) {
    const isSelected=selected===vessel.mmsi,old=nowMs()-vessel.received_ms>1800000,r=isSelected?6:3.3;
    ctx.save();ctx.translate(x,y);ctx.fillStyle=vessel.label==='simulated'?'#b2813e':isSelected?'#5546b5':old?'#8199a9':'#2556c8';ctx.strokeStyle='#fff';ctx.lineWidth=.75;
    if(isSelected){ctx.beginPath();ctx.arc(0,0,11,0,Math.PI*2);ctx.fillStyle='#ffffffbf';ctx.fill();ctx.strokeStyle='#5546b5';ctx.stroke();ctx.fillStyle=vessel.label==='simulated'?'#b2813e':'#5546b5';ctx.strokeStyle='#fff';}
    if(vessel.cog_deg!==null&&vessel.sog_kn!==null&&vessel.sog_kn>.3){ctx.rotate(vessel.cog_deg*Math.PI/180);ctx.beginPath();ctx.moveTo(0,-r*1.5);ctx.lineTo(r*.85,r);ctx.lineTo(0,r*.5);ctx.lineTo(-r*.85,r);ctx.closePath();ctx.fill();ctx.stroke();}
    else{ctx.beginPath();ctx.arc(0,0,r,0,Math.PI*2);ctx.fill();ctx.stroke();}ctx.restore();
  }
  function draw() {
    renderPending=false;if(!width||!height)return;if(backgroundDirty)renderBackground();
    ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(background,0,0);ctx.setTransform(dpr,0,0,dpr,0,0);markers=[];
    let mapped=0;
    for(const vessel of store.vessels.values()){if(!vessel.hasPosition)continue;mapped++;let [x,y]=project(vessel.lon,vessel.lat);x+=Math.round(view.x-x);x=(x-view.x)*view.scale+width/2;y=(y-view.y)*view.scale+height/2;if(x<-15||x>width+15||y<-15||y>height+15)continue;markers.push({vessel,x,y});if(vessel.mmsi!==selected)drawMarker(vessel,x,y);}
    const chosen=markers.find(m=>m.vessel.mmsi===selected);
    if(chosen){drawMarker(chosen.vessel,chosen.x,chosen.y);const name=vesselName(chosen.vessel);ctx.font='600 11px Segoe UI,Arial';const tw=Math.min(210,ctx.measureText(name).width),x=Math.min(width-tw-20,Math.max(5,chosen.x+14)),y=Math.max(20,chosen.y-9);ctx.fillStyle='#fffffff0';ctx.fillRect(x-5,y-12,tw+13,23);ctx.strokeStyle='#d1dce8';ctx.strokeRect(x-5,y-12,tw+13,23);ctx.fillStyle='#273c56';ctx.fillText(name,x,y+3,210);}
    text('map-status',count(markers.length)+' of '+count(mapped)+' positioned vessels in view · last received positions');
  }
  function scheduleDraw(){if(!renderPending){renderPending=true;requestAnimationFrame(draw);}}
  const pointers=new Map();let drag=null,pinch=null;
  canvas.addEventListener('pointerdown',event=>{canvas.setPointerCapture(event.pointerId);pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});if(pointers.size===1){drag={x:event.clientX,y:event.clientY,cx:view.x,cy:view.y,moved:false};canvas.classList.add('dragging');}else if(pointers.size===2){const p=[...pointers.values()],r=canvas.getBoundingClientRect();pinch={distance:Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y),scale:view.scale,x:(p[0].x+p[1].x)/2-r.left,y:(p[0].y+p[1].y)/2-r.top};if(drag)drag.moved=true;}});
  canvas.addEventListener('pointermove',event=>{if(pointers.has(event.pointerId)){pointers.set(event.pointerId,{x:event.clientX,y:event.clientY});if(pointers.size>1&&pinch){const p=[...pointers.values()];zoom(pinch.scale*Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)/Math.max(1,pinch.distance)/view.scale,pinch.x,pinch.y);}else if(drag){const dx=event.clientX-drag.x,dy=event.clientY-drag.y;if(Math.hypot(dx,dy)>4)drag.moved=true;view.x=drag.cx-dx/view.scale;view.y=Math.max(-.2,Math.min(1.2,drag.cy-dy/view.scale));backgroundDirty=true;scheduleDraw();}}else{const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top,closest=markers.find(m=>Math.hypot(m.x-x,m.y-y)<8);canvas.style.cursor=closest?'pointer':'grab';if(closest)text('map-status',vesselName(closest.vessel)+' · MMSI '+closest.vessel.mmsi+' · observation age '+ageText(closest.vessel.received_ms));}});
  function pointerEnd(event){const click=drag&&!drag.moved&&pointers.size===1;pointers.delete(event.pointerId);pinch=null;if(!pointers.size){drag=null;canvas.classList.remove('dragging');}else{const p=[...pointers.values()][0];drag={x:p.x,y:p.y,cx:view.x,cy:view.y,moved:true};}if(click){const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;let nearest=null,limit=14;for(const m of markers){const distance=Math.hypot(m.x-x,m.y-y);if(distance<limit){limit=distance;nearest=m;}}if(nearest)selectVessel(nearest.vessel.mmsi);}}
  canvas.addEventListener('pointerup',pointerEnd);canvas.addEventListener('pointercancel',event=>{pointers.delete(event.pointerId);drag=null;pinch=null;canvas.classList.remove('dragging');});
  canvas.addEventListener('wheel',event=>{if(!event.deltaY||event.shiftKey)return;event.preventDefault();const r=canvas.getBoundingClientRect(),units=event.deltaMode===1?16:event.deltaMode===2?height:1;zoom(Math.exp(-Math.max(-160,Math.min(160,event.deltaY*units))*.0035),event.clientX-r.left,event.clientY-r.top);},{passive:false});
  canvas.addEventListener('keydown',event=>{if(['+','=','-','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)){event.preventDefault();if(event.key==='+'||event.key==='=')zoom(1.5);else if(event.key==='-')zoom(1/1.5);else{view.x+=(event.key==='ArrowLeft'?-60:event.key==='ArrowRight'?60:0)/view.scale;view.y+=(event.key==='ArrowUp'?-60:event.key==='ArrowDown'?60:0)/view.scale;backgroundDirty=true;scheduleDraw();}}});
  $('zoom-in').addEventListener('click',()=>zoom(1.5));$('zoom-out').addEventListener('click',()=>zoom(1/1.5));
  for(const id of ['fit-ireland','nav-ireland'])$(id).addEventListener('click',fitIreland);
  for(const id of ['fit-world','nav-world'])$(id).addEventListener('click',fitWorld);
  $('fit-vessels').addEventListener('click',fitVessels);$('center-selected').addEventListener('click',centerSelected);
  $('nav-map').addEventListener('click',()=>canvas.focus());$('nav-vessels').addEventListener('click',()=>{$('search').focus();});
  $('clear-selection').addEventListener('click',()=>selectVessel(null));
  $('search').addEventListener('input',()=>{listLimit=90;renderDirectory();});
  $('show-more').addEventListener('click',()=>{listLimit+=90;renderDirectory();});
  $('show-ports').addEventListener('change',()=>{backgroundDirty=true;scheduleDraw();});
  function openData(){$('api-url').value=new URL('/api/v1/vessels',location.origin).href;$('copy-status').textContent='';$('data-dialog').showModal();}
  for(const id of ['nav-data','data-access'])$(id).addEventListener('click',openData);
  $('close-data').addEventListener('click',()=>$('data-dialog').close());
  $('data-dialog').addEventListener('click',event=>{if(event.target===$('data-dialog')){const r=$('data-dialog').getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)$('data-dialog').close();}});
  $('copy-url').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('api-url').value);text('copy-status','URL copied');}catch{$('api-url').focus();$('api-url').select();text('copy-status','Select and copy the URL above');}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('data-dialog').open)selectVessel(null);});
  setInterval(()=>{text('clock',dateFormat.format(new Date()).replace(',','')+' UTC');renderMetrics();renderSelection();renderDirectory();scheduleDraw();},1000);
  window.addEventListener('pagehide',()=>{eventSource?.close();if(retryTimer)clearInterval(retryTimer);});
  text('clock',dateFormat.format(new Date()).replace(',','')+' UTC');
  renderState();resize();loadAssets();initializeConnection();
}

if(typeof document!=='undefined')startDashboard();
