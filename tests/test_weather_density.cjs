const {test}=require('node:test');
const assert=require('node:assert/strict');
const {weatherDensityGrid}=require('../src/monarch_phenology/templates/weather_density.js');

const points=Array.from({length:2000},(_,i)=>{
    const angle=i*2.399963229728653, radius=Math.sqrt((i+.5)/2000);
    return [10+radius*Math.cos(angle),20+2*radius*Math.sin(angle)];
});

test('density preserves every point and selects at least 95 percent of smoothed mass',()=>{
    const d=weatherDensityGrid(points);
    assert.ok(Math.abs(d.mass-points.length)<1e-8);
    assert.equal(d.count,2000);
    assert.ok(d.enclosedMass>=.95&&d.enclosedMass<.955);
    assert.ok(d.threshold>0&&d.threshold<100);
    const flat=d.z.flat();
    const enclosed=flat.filter(v=>v>=d.threshold).reduce((a,b)=>a+b,0)/flat.reduce((a,b)=>a+b,0);
    assert.ok(Math.abs(enclosed-d.enclosedMass)<1e-12);
    assert.equal(Math.max(...flat),100);
});

test('Celsius to Fahrenheit conversion does not change the density region',()=>{
    const c=weatherDensityGrid(points,80),f=weatherDensityGrid(points.map(([x,y])=>[x*1.8+32,y*1.8+32]),80);
    assert.ok(Math.abs(c.threshold-f.threshold)<1e-9);
    assert.ok(Math.abs(c.enclosedMass-f.enclosedMass)<1e-12);
    for(let i=0;i<c.x.length;i++)assert.ok(Math.abs(c.x[i]*1.8+32-f.x[i])<1e-10);
});

test('sparse, missing and constant axes do not invent a two-dimensional region',()=>{
    assert.equal(weatherDensityGrid([]),null);
    assert.equal(weatherDensityGrid(points.slice(0,19)),null);
    assert.equal(weatherDensityGrid(Array.from({length:100},(_,i)=>[1,i])),null);
    const d=weatherDensityGrid([...points,[NaN,3],[2,Infinity]]);
    assert.equal(d.count,2000);
});

test('separate clusters can remain separate instead of forcing a single ellipse',()=>{
    const d=weatherDensityGrid([...points,...points.map(([x,y])=>[x+20,y+20])]);
    const midpoint=d.z[Math.floor(d.size/2)][Math.floor(d.size/2)];
    assert.ok(midpoint<d.threshold);
    assert.ok(d.enclosedMass>=.95);
});
