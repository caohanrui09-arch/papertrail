// Invariants are checked against independent native records, including corrupted-source cases.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const box={window:{}};vm.runInNewContext(fs.readFileSync('research74/visuals.js','utf8'),box);const V=box.window.PapertrailVisuals;
const read=name=>JSON.parse(fs.readFileSync('reports/stage74/'+name,'utf8')),clone=x=>JSON.parse(JSON.stringify(x)),checks=[];
function check(name,test){assert.ok(test,name);checks.push(name)}
const rows=read('example-rows.json'),rank=read('rank-diagnostic.json');
const ranked=V.rankData(rank);check('full_pool_including_positions_below_10',ranked.rows.length===rank.pool_ids.length);
check('exact_native_ranks',ranked.rows.every(p=>p.before===rank.methods.pool_content.findIndex(x=>x.doc_id===p.doc_id)+1&&p.after===rank.methods.profile_rerank.findIndex(x=>x.doc_id===p.doc_id)+1));
let bad=clone(rank);bad.method_info.profile_rerank.pool_ids_sha256='other';check('different_pool_hash_rejected',!!V.rankData(bad).error);
bad=clone(rank);bad.methods.profile_rerank[0].doc_id='not-in-original-pool';check('different_ids_despite_same_hash_rejected',!!V.rankData(bad).error);
bad=clone(rank);bad.methods.profile_rerank.push(bad.methods.profile_rerank[0]);check('duplicate_ranks_rejected',!!V.rankData(bad).error);
const chain=V.chainData(rows.fixed);check('two_exact_native_chains',chain.length===2&&chain.every(c=>c.verified));
bad=clone(rows.fixed);bad.trace.trace=bad.trace.trace.filter(e=>e.tool!=='read_paper');check('unread_citation_not_verified',V.chainData(bad).every(c=>!c.verified));
bad=clone(rows.fixed);bad.answer.citations[0].quote+=' fabricated';check('fabricated_excerpt_rejected',!V.chainData(bad)[0].verified);
bad=clone(rows.fixed);bad.answer.citations[0].version=2;check('version_mismatch_rejected',!V.chainData(bad)[0].verified);
bad=clone(rows.fixed);bad.answer.citations[0].source_url='https://arxiv.org/abs/other';check('source_mismatch_rejected',!V.chainData(bad)[0].verified);
bad=clone(rows.fixed);bad.trace.trace.unshift(bad.trace.trace.pop());check('finalize_before_read_not_verified',V.chainData(bad).every(c=>!c.verified));
bad=clone(rows.fixed);bad.trace.trace=bad.trace.trace.filter(e=>!['search_papers','recommend_papers'].includes(e.tool));check('never_returned_citation_not_verified',V.chainData(bad).every(c=>!c.verified));
const sourceChecks=[];for(const row of read('evaluation-summary.json').agent.rows){const value=read('evaluation-'+row.cell+'.json');for(const c of V.chainData(value.result))sourceChecks.push(c.verified)}
check('all_8_accepted_evaluation_citations_verified',sourceChecks.length===8&&sourceChecks.every(Boolean));
check('retained_empty_has_no_synthetic_chain',V.chainData(read('retained-no_results.json').record.result.results[0]).length===0);
fs.writeFileSync('reports/stage74/data-validation.json',JSON.stringify({status:'passed',checks:checks.length,passed:checks},null,2));console.log({status:'passed',checks:checks.length});
