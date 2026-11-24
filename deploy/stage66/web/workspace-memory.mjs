// Application snapshot adapter over native Web Storage; no result/abstract cache.
export const MODES=['search','recommend','saved','hidden','guide','readinglist'];
const TOPICS=['generative','cold','bias'];
const scopes=['all','core','multimodal','generative','cold','bias','unclassified'];
const yearValue=v=>typeof v==='string'&&/^(19|20|21)[0-9]{2}$/.test(v)&&Number(v)<=2100?v:'';
const finiteOffset=v=>Number.isFinite(v)&&v>=0?Math.min(v,10000000):0;
export function normalizeWorkspace(value){
 if(!value||typeof value!=='object'||!MODES.includes(value.mode)||!TOPICS.includes(value.topic))return null;
 if(typeof value.q!=='string'||value.q.length>1000||!['bm25','tfidf'].includes(value.method)||!['none','same','cross'].includes(value.context))return null;
 const target=typeof value.target==='string'&&/^\d{4}\.\d{4,5}$/.test(value.target)?value.target:null;
 const version=target&&value.versionKey===`arxiv:${target}v1`?value.versionKey:null;
 const f=value.favoriteFilters&&typeof value.favoriteFilters==='object'?value.favoriteFilters:{};
 return {searchYear:yearValue(value.searchYear),favoriteFilters:{scope:scopes.includes(f.scope)&&f.scope!=='core'?f.scope:'all',year:yearValue(f.year),reading:['all','none','to_read','reading','read'].includes(f.reading)?f.reading:'all'},abstractMode:value.abstractMode==='original'?'original':'clean',originalNeed:typeof value.originalNeed==='string'&&value.originalNeed.length<=1000?value.originalNeed:'',planReviewed:value.planReviewed===true,catalogScope:scopes.includes(value.catalogScope)?value.catalogScope:'core',noteQuery:typeof value.noteQuery==='string'&&value.noteQuery.length<=200?value.noteQuery:'',readingFilter:['all','to_read','reading','read','noted'].includes(value.readingFilter)?value.readingFilter:'all',mode:value.mode,topic:value.topic,q:value.q,method:value.method,context:value.context,
  target:version?target:null,versionKey:version,tab:value.tab==='trace'?'trace':'read',focused:value.focused===true,
  listScroll:finiteOffset(value.listScroll),readScroll:finiteOffset(value.readScroll),traceScroll:finiteOffset(value.traceScroll),
  listEnd:value.listEnd===true,readEnd:value.readEnd===true,traceEnd:value.traceEnd===true};
}

export function createWorkspaceMemory(catalogKey,providedStorage,previousCatalogKey){
 const key='papertrail.workspace.v1.'+catalogKey;
 const empty=()=>({schema:1,catalogKey,lastMode:'search',spaces:{}});
 let fallback=empty(),storage=providedStorage,persistent=true;
 if(providedStorage===undefined)try{storage=window.localStorage;}catch{storage=null;persistent=false;}
 if(!storage)persistent=false;
 function readDocument(){
  if(!storage)return fallback;
  let raw;
  try{raw=storage.getItem(key);}catch{persistent=false;storage=null;return fallback;}
  let migrating=false;
  if(!raw&&previousCatalogKey&&previousCatalogKey!==catalogKey){try{raw=storage.getItem('papertrail.workspace.v1.'+previousCatalogKey);migrating=!!raw;}catch{}}
  if(!raw)return empty();
  if(raw.length>32768)return empty();
  try{
   const data=JSON.parse(raw);
   if(!data||data.schema!==1||data.catalogKey!==(migrating?previousCatalogKey:catalogKey)||!data.spaces||typeof data.spaces!=='object')return empty();
   const out=empty();
   for(const mode of MODES){const clean=normalizeWorkspace(data.spaces[mode]);if(clean&&clean.mode===mode)out.spaces[mode]=clean;}
   out.lastMode=MODES.includes(data.lastMode)?data.lastMode:'search';
   return out;
  }catch{return empty();}
 }
 return {
  get(mode){return readDocument().spaces[mode]||null;},
  last(){const doc=readDocument();return doc.spaces[doc.lastMode]||Object.values(doc.spaces)[0]||null;},
  write(value){
   const clean=normalizeWorkspace(value);if(!clean)return false;
   const doc=readDocument();doc.spaces[clean.mode]=clean;doc.lastMode=clean.mode;fallback=doc;
   if(storage)try{storage.setItem(key,JSON.stringify(doc));}catch{persistent=false;storage=null;}
   return true;
  },
  clear(){fallback=empty();if(storage)try{storage.removeItem(key);if(previousCatalogKey&&previousCatalogKey!==catalogKey)storage.removeItem('papertrail.workspace.v1.'+previousCatalogKey);}catch{persistent=false;storage=null;}},
  get persistent(){return persistent;}
 };
}
