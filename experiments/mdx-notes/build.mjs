import {readFile, mkdir, writeFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {compile} from '@mdx-js/mdx';
const root=dirname(fileURLToPath(import.meta.url));
await mkdir(resolve(root,'dist'),{recursive:true});
await build({
  absWorkingDir:root,entryPoints:['index.jsx'],bundle:true,format:'esm',minify:true,
  outfile:'dist/note.js',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},
  plugins:[{name:'trusted-mdx',setup(builder){
    builder.onLoad({filter:/\.mdx$/},async({path})=>({
      contents:String(await compile({path,value:await readFile(path,'utf8')})),
      loader:'js',resolveDir:dirname(path)
    }));
  }}]
});
await writeFile(resolve(root,'dist/index.html'),`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Monarch MDX note experiment</title><link rel="stylesheet" href="note.css"></head><body><main id="root"></main><script type="module" src="note.js"></script></body></html>`);
console.log('Built experiments/mdx-notes/dist');
