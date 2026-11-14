import {useState} from 'react';
export function WeatherLab({initialStage='all',initialUnits='F'}) {
  const [stage,setStage]=useState(initialStage);
  const [units,setUnits]=useState(initialUnits);
  const [shown,setShown]=useState(true);
  const url=new URL('http://127.0.0.1:8769/');
  url.search=new URLSearchParams({embed:'plot',stage,units}).toString();
  url.hash='overnight';
  return <section aria-label="Interactive monarch weather figure" className="figure">
    <div className="controls">
      <label>Life stage <select value={stage} onChange={e=>setStage(e.target.value)}>
        <option value="all">Larvae and pupae</option><option value="larva">Larvae</option><option value="pupa">Pupae</option>
      </select></label>
      <label>Temperature units <select value={units} onChange={e=>setUnits(e.target.value)}>
        <option value="F">Fahrenheit</option><option value="C">Celsius</option>
      </select></label>
      <button onClick={()=>setShown(!shown)}>{shown?'Hide figure':'Show figure'}</button>
      <a href="http://127.0.0.1:8769/#overnight" target="_blank" rel="noreferrer">Full weather lab</a>
    </div>
    {shown&&<iframe key={url.href} title="Monarch seven-day weather density" src={url.href} />}
    <p className="caption">November 2, 2026 observation snapshot. The figure reloads when the note controls change. The local weather server must be running on this computer.</p>
  </section>;
}
