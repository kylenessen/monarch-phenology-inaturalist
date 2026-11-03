// Equal-weight, binned two-dimensional Gaussian density for the selected observations.
// A highest-density region encloses smoothed mass, not confidence in a mean.
function weatherDensityGrid(points, size=128, coverage=0.95) {
    if(!Number.isFinite(coverage)||coverage<=0||coverage>=1)throw Error('Density coverage must be between zero and one');
    const valid=points.filter(p=>Number.isFinite(p[0])&&Number.isFinite(p[1]));
    if(valid.length<20)return null;
    let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
    for(const [x,y] of valid){xmin=Math.min(xmin,x);xmax=Math.max(xmax,x);ymin=Math.min(ymin,y);ymax=Math.max(ymax,y);}
    if(xmin===xmax||ymin===ymax)return null;
    if(!Number.isInteger(size)||size<32||size>256)throw Error('Density grid size must be between 32 and 256');
    const pad=8,sigma=1.5,radius=5,dx=(xmax-xmin)/(size-2*pad-1),dy=(ymax-ymin)/(size-2*pad-1);
    const xs=Array.from({length:size},(_,i)=>xmin+(i-pad)*dx);
    const ys=Array.from({length:size},(_,i)=>ymin+(i-pad)*dy);
    const counts=new Float64Array(size*size);
    // Bilinear binning reduces sensitivity to the exact grid origin.
    for(const [x,y] of valid){
        const fx=(x-xmin)/dx+pad,fy=(y-ymin)/dy+pad,ix=Math.floor(fx),iy=Math.floor(fy),rx=fx-ix,ry=fy-iy;
        counts[iy*size+ix]+=(1-rx)*(1-ry);
        counts[iy*size+ix+1]+=rx*(1-ry);
        counts[(iy+1)*size+ix]+=(1-rx)*ry;
        counts[(iy+1)*size+ix+1]+=rx*ry;
    }
    const kernel=Array.from({length:radius*2+1},(_,i)=>Math.exp(-0.5*((i-radius)/sigma)**2));
    const kernelTotal=kernel.reduce((a,b)=>a+b,0);
    for(let i=0;i<kernel.length;i++)kernel[i]/=kernelTotal;
    const horizontal=new Float64Array(size*size),smooth=new Float64Array(size*size);
    for(let y=0;y<size;y++)for(let x=0;x<size;x++)for(let k=-radius;k<=radius;k++){
        if(x+k>=0&&x+k<size)horizontal[y*size+x]+=counts[y*size+x+k]*kernel[k+radius];
    }
    for(let y=0;y<size;y++)for(let x=0;x<size;x++)for(let k=-radius;k<=radius;k++){
        if(y+k>=0&&y+k<size)smooth[y*size+x]+=horizontal[(y+k)*size+x]*kernel[k+radius];
    }
    const ranked=Array.from(smooth).filter(v=>v>0).sort((a,b)=>b-a);
    const total=ranked.reduce((a,b)=>a+b,0),peak=ranked[0];
    let cumulative=0,threshold=0;
    for(const value of ranked){cumulative+=value;threshold=value;if(cumulative>=coverage*total)break;}
    const enclosed=ranked.filter(v=>v>=threshold).reduce((a,b)=>a+b,0)/total;
    return {x:xs,y:ys,z:Array.from({length:size},(_,y)=>Array.from(smooth.subarray(y*size,(y+1)*size),v=>100*v/peak)),
        threshold:100*threshold/peak,mass:total,enclosedMass:enclosed,count:valid.length,size,sigmaCells:sigma};
}
if(typeof module!=='undefined'&&module.exports)module.exports={weatherDensityGrid};
