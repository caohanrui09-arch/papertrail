"""Exercise existing token meter boundaries without inference or altered budgets."""
import json
from pathlib import Path
from gsearch.budget_model import GenerationMeter
from gsearch.bundle_session import BundleBudget


def main():
    budget=BundleBudget(max_steps=8,input_tokens=30000,output_tokens=1280)
    checks=[]
    def reject(fn,name):
        try:fn()
        except ValueError:checks.append(name)
        else:raise AssertionError(name)
    meter=GenerationMeter(budget);assert meter.reserve_input(30000)==160
    reject(lambda:meter.reserve_input(1),'cumulative_input_limit')
    assert meter.calls==1 and meter.input_tokens==30000 and meter.denied_calls==1
    meter=GenerationMeter(budget)
    for _ in range(8):assert meter.reserve_input(1)==160;meter.record_output(160)
    reject(lambda:meter.reserve_input(0),'cumulative_output_and_call_limit')
    reject(lambda:meter.record_output(1),'output_overrun')
    meter=GenerationMeter(budget)
    for _ in range(8):meter.reserve_input(1)
    reject(lambda:meter.reserve_input(1),'call_limit_without_output_exhaustion')
    report={'status':'passed','native_meter':'gsearch.budget_model.GenerationMeter',
            'checks':checks,'budgets':{'calls':8,'input_tokens':30000,'output_tokens':1280},
            'model_inference_calls':0}
    Path('reports/stage71/token-budget-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))


if __name__=='__main__':main()
