import {findAll} from './vendor/highlight-words-core.mjs';
// Presentation only: bounded, literal, case-insensitive whitespace-separated query terms.
export function queryWords(query=''){
 return [...new Set(query.trim().split(/\s+/u).filter(word=>word.length>=2&&word.length<=80))].slice(0,24);
}
export function highlightParts(text='',query=''){
 return findAll({textToHighlight:text,searchWords:queryWords(query),autoEscape:true,caseSensitive:false});
}
