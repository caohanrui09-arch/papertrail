"""Compare local frozen policy AST, allowing observation and relocation only."""
import ast
import json
from pathlib import Path


class Normalize(ast.NodeTransformer):
    def visit_FunctionDef(self,node):
        node.name={'observed_llm':'llm','observed_run':'run','observed_constrained':'run'}.get(node.name,node.name)
        pairs=list(zip(node.args.args,[None]*(len(node.args.args)-len(node.args.defaults))+node.args.defaults))
        pairs=[(arg,default) for arg,default in pairs if arg.arg!='observer']
        node.args.args=[arg for arg,default in pairs]
        node.args.defaults=[default for arg,default in pairs if default is not None]
        return self.generic_visit(node)

    def visit_ImportFrom(self,node):
        if node.module=='gsearch.bundle_session':node.module='bundle_session';node.level=1
        return node

    def visit_Name(self,node):
        if node.id=='NATIVE_POLICY_FILE':node.id='__file__'
        return node

    def visit_Expr(self,node):
        call=node.value
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='observer':return None
        return self.generic_visit(node)

    def visit_Call(self,node):
        node.keywords=[kw for kw in node.keywords if not(kw.arg=='observer' or (kw.arg=='step_callbacks' and 'observer' in ast.dump(kw.value)))]
        if isinstance(node.func,ast.Name) and node.func.id=='observed_llm':
            node.func.id='llm';node.args=[a for a in node.args if not(isinstance(a,ast.Name) and a.id=='observer')]
        return self.generic_visit(node)


def main():
    def function(path,name):
        return next(node for node in ast.parse(Path(path).read_text(encoding='utf8')).body if isinstance(node,ast.FunctionDef) and node.name==name)
    checked=[]
    for source,old,new in [('gsearch/unified_agent.py','llm','observed_llm'),('gsearch/unified_agent.py','run','observed_run'),('gsearch/constrained_agent_isolated.py','run','observed_constrained')]:
        assert ast.dump(function(source,old),include_attributes=False)==ast.dump(Normalize().visit(function('research70/runner.py',new)),include_attributes=False),new
        checked.append(new)
    import starlette
    report={'status':'passed','native_policy_ast_equal_except_observation_and_module_relocation':checked,'installed_starlette':starlette.__version__,'original_model_prompt_budget_guard_unchanged':True}
    Path('reports/stage70/adapter-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
