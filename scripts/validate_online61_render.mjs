// Offline HTM render contracts. This is not a browser, screenshot or interaction test.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import vm from 'node:vm';
import htm from '../deploy/stage61/web/vendor/htm.mjs';
const root=new URL('../deploy/stage61/web/',import.meta.url),checks=[];
const live=JSON.parse(await readFile(new URL('../reports/stage61/live-probe.json',import.meta.url),'utf8'));
let slots=[],slot=0,rootNode;
const context=vm.createContext({location:{search:''},URLSearchParams,AbortController,performance,setTimeout,clearTimeout,console,document:{getElementById:()=>null}});
const h=(type,props,...children)=>({type,props:{...props,children}});
const preact=new vm.SyntheticModule(['h','render'],function(){this.setExport('h',h);this.setExport('render',v=>{rootNode=v;});},{context});
const hooks=new vm.SyntheticModule(['useState','useRef','useEffect'],function(){this.setExport('useState',v=>{const i=slot++;if(!(i in slots))slots[i]=v;return[slots[i],next=>slots[i]=typeof next==='function'?next(slots[i]):next];});this.setExport('useRef',v=>({current:v}));this.setExport('useEffect',()=>{});},{context});
const templates=new vm.SyntheticModule(['default'],function(){this.setExport('default',htm);},{context});
const modules=new Map();
async function load(url){
 if(modules.has(url.href))return modules.get(url.href);
 const module=new vm.SourceTextModule(await readFile(url,'utf8'),{context,identifier:url.href});modules.set(url.href,module);
 await module.link(async(specifier,parent)=>specifier==='preact'?preact:specifier==='preact/hooks'?hooks:specifier==='htm'?templates:load(new URL(specifier,parent.identifier)));
 return module;
}
await (await load(new URL('online.mjs',root))).evaluate();
function walk(node){
 if(Array.isArray(node))return node.flatMap(walk);
 if(node===null||node===undefined||typeof node==='boolean')return[];
 if(typeof node!=='object')return[String(node)];
 if(typeof node.type==='function')return walk(node.type(node.props));
 return[{tag:node.type,props:node.props,children:walk(node.props.children)}];
}
function render(state){slots=state;slot=0;return walk(rootNode);}
function flat(nodes){return nodes.flatMap(n=>typeof n==='string'?[n]:[n,...flat(n.children)]);}
function words(nodes){return flat(nodes).filter(n=>typeof n==='string').join(' ');}
function check(name,condition){assert.ok(condition,name);checks.push(name);}
const idle=render(['','arxiv','',null,null,'idle','',false]);
check('idle_paper_style_shell_and_empty_reader',words(idle).includes('让好问题，找到更多线索。')&&words(idle).includes('先看摘要，再决定深入。'));
check('empty_search_submit_disabled',flat(idle).some(n=>n.tag==='button'&&n.props.class==='online-submit'&&n.props.disabled));
const result={...live.find(r=>r.provider==='arxiv').response,elapsed:3000};
const returned=render([result.query,'arxiv','',result,result.papers[0],'returned','',false]);
check('all_actual_returned_papers_render',flat(returned).filter(n=>n.tag==='article').length===10);
check('selected_real_abstract_and_version',words(returned).includes(result.papers[0].abstract)&&words(returned).includes(result.papers[0].version));
check('links_only_as_safe_href_no_raw_html',flat(returned).filter(n=>typeof n==='object').every(n=>!n.props.dangerouslySetInnerHTML));
check('trace_uses_actual_response_receipt',words(render([result.query,'arxiv','',result,result.papers[0],'returned','',true])).includes(result.response_sha256));
const missing={...result.papers[0],abstract:null,abstract_source:null,version:null,access:'metadata_only',provider:'openalex',open_url:null};
const noAbstract={...result,provider:'openalex',papers:[missing]};
check('missing_abstract_not_replaced_by_generated_text',words(render([result.query,'openalex','',noAbstract,missing,'returned','',false])).includes('没有用模型生成摘要代替原文'));
check('error_is_not_empty_search_claim',words(render(['test','arxiv','',null,null,'error','论文来源响应超时',false])).includes('这次在线查询未完成'));
const dirty=render(['changed query','arxiv','',result,result.papers[0],'returned','',false]);
check('changed_criteria_notice',words(dirty).includes('条件已修改，请重新查询'));
check('dirty_pagination_disabled',flat(dirty).filter(n=>n.tag==='button'&&words(n.children).includes('下一页')).every(n=>n.props.disabled));
await writeFile(new URL('../reports/stage61/render-validation.json',import.meta.url),JSON.stringify({status:'passed',passed:checks.length,checks,scope:'offline actual HTM templates with hook stubs and real source records; no browser, layout or user-interaction claim'},null,2)+'\n');
console.log({passed:checks.length});
