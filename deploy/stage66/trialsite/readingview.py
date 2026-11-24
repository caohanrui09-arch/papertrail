"""Conservative display-only adapter over pinned pylatexenc 2.10, never TeX execution."""
from pathlib import Path
import hashlib
import json
import re
import sys
from fastapi import HTTPException
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'third-party'))
from pylatexenc.latex2text import LatexNodes2Text
from pylatexenc.latexwalker import LatexWalkerError

class PlainText(LatexNodes2Text):
    def __init__(self):
        super().__init__(math_mode='verbatim',keep_comments=True,strict_latex_spaces='based-on-source')
        self.unsupported=set()
    def read_input_file(self,fn):raise ValueError('External TeX input is disabled')
    def macro_node_to_text(self,node):
        spec=self.latex_context.get_macro_spec(node.macroname)
        if spec is None or (spec.discard and not spec.simplify_repl):
            self.unsupported.add(node.macroname);return node.latex_verbatim()
        return super().macro_node_to_text(node)
    def environment_node_to_text(self,node):
        spec=self.latex_context.get_environment_spec(node.environmentname)
        if spec is None or spec.discard:
            self.unsupported.add(node.environmentname);return node.latex_verbatim()
        return super().environment_node_to_text(node)
def clean_view(text:str)->dict:
    original_hash=hashlib.sha256(text.encode()).hexdigest();warnings=[]
    if len(text)>50000 or re.search(r'\\(?:input|include|write|openout|read|def|newcommand|usepackage|catcode)\b',text):
        return {'text':text,'changed':False,'warnings':['含不支持的TeX指令，保留原文。'],'source_sha256':original_hash,'converter':'pylatexenc2.10-conservative'}
    converter=PlainText()
    try:
        output=converter.latex_to_text(text,tolerant_parsing=False)
        if converter.unsupported:
            output=text;warnings=['部分标记不支持，保留原文：'+', '.join(sorted(converter.unsupported))]
    except (ValueError,RecursionError,LatexWalkerError):
        output=text;warnings=['格式解析未完成，保留原文。']
    return {'text':output,'changed':output!=text,'warnings':warnings,'source_sha256':original_hash,'converter':'pylatexenc2.10-conservative'}
def install_readingview(app):
    c=app.state.catalog;views={d:clean_view(c.read(d)['abstract']) for d in c.catalog}
    comparison=json.loads((ROOT/'comparison-evidence.json').read_text(encoding='utf8'))
    for doc,fields in comparison['papers'].items():
        row=c.read(doc)
        for entry in fields.values():
            if entry is not None and (not entry['evidence'] or entry['evidence'] not in row['abstract']):raise ValueError('Comparison evidence must match the original v1 abstract')
    @app.get('/api/paper-reading/{doc}')
    def reading(doc:str):
        original=c.read(doc)
        return {'paper':original,'reading_view':views[doc],'comparison':comparison['papers'].get(doc),
            'comparison_scope':'基于本站缓存的明确v1摘要整理；未复现论文效果，未明确的项留空。',
            'trace':[{'tool':'读取官方原v1摘要','doc_id':doc,'source_verified':True},{'tool':'摘要显示整理','converter':views[doc]['converter'],'original_preserved':True,'source_sha256':views[doc]['source_sha256']}]}
    app.state.reading_views=views
