import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const root=process.argv[2];
if(!root) throw Error('Supply the bundled absolute lucide package directory');
const meta=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
if(meta.version!=='1.8.0'||meta.license!=='ISC') throw Error('Expected audited bundled lucide1.8.0 ISC');
const require=createRequire(import.meta.url), lib=require(path.join(root,meta.main));
const names=['Search','Plus','BookOpen','FileText','Compass','History','Settings2','Sun','Moon','ChevronDown','ChevronRight','Copy','Download','X','Menu','ExternalLink','Database','ArrowUp','ArrowUpRight','PanelLeft','PanelRight','Check','Clock','CircleAlert','SlidersHorizontal','Layers','MessageSquare','Sparkles','Terminal','GitBranch'];
const icons={};
for(const name of names){if(!lib.icons[name])throw Error('Unknown native icon '+name);icons[name]=lib.icons[name];}
const dest=path.resolve('web/papertrail/dist/vendor');fs.mkdirSync(dest,{recursive:true});
fs.writeFileSync(path.join(dest,'icons.json'),JSON.stringify(icons));
fs.copyFileSync(path.join(root,'LICENSE'),path.join(dest,'LUCIDE_LICENSE'));
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const value={package:'lucide',version:meta.version,license:meta.license,source:'Codex bundled runtime package; native icon node arrays selected without editing paths',icons:names,
files:Object.fromEntries(['icons.json','LUCIDE_LICENSE'].map(name=>[path.relative(process.cwd(),path.join(dest,name)),sha(path.join(dest,name))]))};
fs.writeFileSync('reports/stage23/icons-lock.json',JSON.stringify(value,null,2)+'\n');
console.log(JSON.stringify({icons:names.length,version:meta.version}));
