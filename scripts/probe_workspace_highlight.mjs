import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {highlightParts,queryWords} from '../web/papertrail-v38/dist/highlight.mjs';
const cases=[
 ['Document Retrieval and document retrieval','document Retrieval',['Document','Retrieval','document','retrieval']],
 ['abab <script>alert(1)</script>','aba ab',['abab']],
 ['literal (a+)+ and axxxx','(a+)+',['(a+)+']],
 ['<img src=x onerror=alert(1)>','<img',['<img']],
 ['论文😀 retrieval','论文 😀',['论文','😀']],
 ['unchanged sentence','[] .*',[]],['No query','',[]],['single a','a',[]]
];
for(const [text,query,expected] of cases){
 const chunks=highlightParts(text,query);
 assert.equal(chunks.map(c=>text.slice(c.start,c.end)).join(''),text);
 assert.deepEqual(chunks.filter(c=>c.highlight).map(c=>text.slice(c.start,c.end)),expected);
}
assert.equal(queryWords('x '.repeat(100)).length,0);
assert.equal(queryWords('z'.repeat(90)).length,0);
assert.equal(queryWords(Array.from({length:40},(_,i)=>'word'+i).join(' ')).length,24);
writeFileSync('reports/stage38/highlight-validation.json',JSON.stringify({status:'passed',cases:cases.length,bounded_terms:true,text_preserved:true,literal_regex_metacharacters:true,html_remains_text:true,unicode_preserved:true},null,2)+'\n');
console.log('8 highlight boundary cases and term bounds passed');
