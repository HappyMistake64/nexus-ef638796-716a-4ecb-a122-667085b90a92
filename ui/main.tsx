import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

type Dataset = {name:string;source:string;license:string;valid_on:string;cars:number;origin:string;hospital:string;nodes:{id:string;x:number;y:number}[];edges:{id:string;source:string;target:string;speed:number}[];bus_departures:number[]};
type Metric = {travel_s:number|null;bus_s:number|null;waiting_s:number|null;max_queue_m:number|null;hospital_freeflow_s:number|null;completed:number;unreachable:number;unfinished:number};
type Job = {id:string;status:string;closed:string;factor:number;seeds:number[];error:string|null;results:{seed:number;baseline:Metric;variant:Metric}[]};
declare global { interface Window { city:{api(method:string,path:string,body?:unknown):Promise<any>;importDataset():Promise<Dataset|null>;export(id:string,format:string):Promise<void>} } }
const done=(j:Job|null)=>!j||['completed','cancelled','failed'].includes(j.status);
const fmt=(v:number|null)=>v===null?'Nedostupné':v.toFixed(1);

function Network({data,closed,choose}:{data:Dataset;closed:string;choose:(id:string)=>void}) {
  const element=useRef<HTMLDivElement>(null), callback=useRef(choose);
  callback.current=choose;
  useEffect(()=>{
    const map=new maplibregl.Map({container:element.current!,style:{version:8,sources:{},layers:[{id:'bg',type:'background',paint:{'background-color':'#101e30'}}]},center:[14.4,50.08],zoom:14});
    const pos=(id:string):[number,number]=>{const n=data.nodes.find(n=>n.id===id)!;return [14.4+n.x/71400,50.08+n.y/111300];};
    map.on('load',()=>{
      map.addSource('roads',{type:'geojson',data:{type:'FeatureCollection',features:data.edges.map(e=>({type:'Feature',properties:{id:e.id,closed:e.id===closed},geometry:{type:'LineString',coordinates:[pos(e.source),pos(e.target)]}}))}});
      map.addLayer({id:'roads',type:'line',source:'roads',paint:{'line-width':9,'line-color':['case',['get','closed'],'#ff6d70','#64d6ba']}});
      map.on('click','roads',e=>{const id=e.features?.[0]?.properties?.id;if(id)callback.current(id);});
      for(const n of data.nodes){const label=document.createElement('div');label.className='node';label.textContent=n.id===data.hospital?'H · nemocnice':n.id===data.origin?'O · počátek':n.id;new maplibregl.Marker({element:label}).setLngLat(pos(n.id)).addTo(map);}
      const bounds=new maplibregl.LngLatBounds();data.nodes.forEach(n=>bounds.extend(pos(n.id)));map.fitBounds(bounds,{padding:65,duration:0,maxZoom:16});
    });
    return ()=>map.remove();
  },[data,closed]);
  return <div className="map" ref={element}/>;
}
function App(){
  const [data,setData]=useState<Dataset|null>(null),[closed,setClosed]=useState(''),[job,setJob]=useState<Job|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[factor,setFactor]=useState(1),[seeds,setSeeds]=useState('11,22,33');
  const act=async(fn:()=>Promise<void>)=>{setError('');setBusy(true);try{await fn();}catch(e){setError(String(e));}finally{setBusy(false);}};
  useEffect(()=>{act(async()=>{const d:Dataset=await window.city.api('GET','/dataset');setData(d);setClosed(d.edges.some(e=>e.id==='most')?'most':d.edges[0].id);});},[]);
  useEffect(()=>{if(done(job))return;let live=true;const t=setInterval(()=>{window.city.api('GET',`/jobs/${job!.id}`).then(j=>{if(live)setJob(j);}).catch(e=>{if(live)setError(String(e));});},800);return()=>{live=false;clearInterval(t);};},[job?.id,job?.status]);
  const locked=busy||!done(job);
  const rows:[keyof Metric,string][]=[['travel_s','Automobily: průměrná jízda [s]'],['bus_s','Autobusy: průměrná jízda [s]'],['waiting_s','Všechna vozidla: stání [s]'],['max_queue_m','Maximum fronty na jednom pruhu [m]'],['completed','Dokončené cesty'],['unreachable','Nedosažitelné cesty'],['unfinished','Nedokončené do 900 s'],['hospital_freeflow_s','Nemocnice: volný průjezd [s]']];
  const range=(key:keyof Metric,side:'baseline'|'variant')=>{const v=job!.results.map(r=>r[side][key]).filter((v):v is number=>v!==null);return v.length?`${fmt(v.reduce((a,b)=>a+b,0)/v.length)} (${fmt(Math.min(...v))}–${fmt(Math.max(...v))})`:'Nedostupné';};
  return <main><header><div className="logo">CF</div><div><h1>CITY FORGE</h1><p>Lokální laboratoř dopravních scénářů</p></div><strong>DEMONSTRACE</strong></header>
    <aside>Syntetická nekalibrovaná čtvrť. Není určeno pro vysílání záchranářů ani řízení infrastruktury.</aside>
    {error&&<pre role="alert" className="error">{error}</pre>}
    {data&&<><div className="layout"><section><h2>01 / Vstupy a varianta</h2><h3>{data.name}</h3><p>{data.source} · {data.license}<br/>Platnost: {data.valid_on}</p>
      <button disabled={locked} onClick={()=>act(async()=>{const d=await window.city.importDataset();if(d){setData(d);setClosed(d.edges[0].id);setJob(null);}})}>Importovat síť JSON</button>
      <p>{data.cars} automobilů / prvních 600 s<br/>{data.bus_departures.length} autobusových odjezdů</p>
      <label>Uzavřený orientovaný úsek<select disabled={locked} value={closed} onChange={e=>setClosed(e.target.value)}>{data.edges.map(e=><option key={e.id} value={e.id}>{e.id} · {e.source} → {e.target}</option>)}</select></label>
      <label>Interval uzavírky<input readOnly value="0–900 s (celý experiment)"/></label>
      <label>Poptávka × {factor.toFixed(1)}<input disabled={locked} type="range" min="0.5" max="1.5" step="0.1" value={factor} onChange={e=>setFactor(Number(e.target.value))}/></label>
      <label>Semínka (1–3)<input disabled={locked} value={seeds} onChange={e=>setSeeds(e.target.value)}/></label>
      <p>Objížďka: nejrychlejší dostupná cesta. Všechna vozidla znají uzavírku před odjezdem.</p>
      <button className="primary" disabled={locked} onClick={()=>act(async()=>{if(!/^\d+(\s*,\s*\d+){0,2}$/.test(seeds))throw new Error('Zadejte 1–3 celočíselná semínka');setJob(await window.city.api('POST','/jobs',{closed,seeds:seeds.split(',').map(Number),factor}));})}>Spustit základ + variantu</button>
      {!done(job)&&<button disabled={busy||job?.status==='cancelling'} onClick={()=>act(async()=>setJob(await window.city.api('POST',`/jobs/${job!.id}/cancel`,{})))}>Zrušit výpočet</button>}
    </section><section className="mapPanel"><Network data={data} closed={closed} choose={id=>{if(!locked)setClosed(id);}}/><p>Zelená: dostupný úsek · Červená: vybraná uzavírka<br/>Kliknutím vyberte úsek. Schematická mapa bez externích dlaždic.</p></section></div>
    <section className="results"><h2>02 / Porovnání experimentu</h2>{!job?<p>Vyberte úsek a spusťte skutečný SUMO.</p>:<><p>Stav: <b>{job.status}</b> · {job.id}</p><p>Uložený experiment: {job.closed}, poptávka × {job.factor}, semínka {job.seeds.join(', ')}. Mapa je výběr pro další běh.</p>{job.error&&<pre className="error">{job.error}</pre>}{job.status==='completed'&&<><p>Průměr (minimum–maximum) přes semínka, nikoli interval spolehlivosti. Jízdy a stání zahrnují jen dokončená vozidla.</p><table><thead><tr><th>Metrika</th><th>Základ</th><th>Uzavírka</th></tr></thead><tbody>{rows.map(([key,label])=><tr key={key}><td>{label}</td><td>{range(key,'baseline')}</td><td>{range(key,'variant')}</td></tr>)}</tbody></table>
    <h3>Změna autobusové jízdní doby</h3><p>{job.results.map(r=>`${r.seed}: ${r.baseline.bus_s===null||r.variant.bus_s===null?'nedostupné':fmt(r.variant.bus_s-r.baseline.bus_s)+' s'}`).join(' · ')}</p>
    <p>Nemocnice: teoretická volná cesta bez kolon, přednosti, křižovatkových zdržení a výjezdu posádky. Autobusy nemají zastávky; nejde o zpoždění proti úplnému jízdnímu řádu.</p>
    <button disabled={busy} onClick={()=>act(()=>window.city.export(job.id,'csv'))}>Export CSV</button> <button disabled={busy} onClick={()=>act(()=>window.city.export(job.id,'html'))}>Export HTML + vstupy</button><details><summary>Dohledatelnost</summary><pre>{JSON.stringify(job,null,2)}</pre></details></>}</>}</section></>}
    <footer>CITY FORGE 0.1.2 · SUMO · jeden worker · offline síť</footer></main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
