"""Public launcher: never rerun or overwrite an already-started evaluation cell."""
import json
import subprocess

from research73.common import ROOT,DATA,read


def main():
    order=read(DATA/'inputs/run-order.json')
    started=[c['cell'] for c in order if (DATA/'agent-runs'/c['cell']/'started.json').exists()]
    finished=[c['cell'] for c in order if (DATA/'agent-runs'/c['cell']/'result.json').exists()]
    if started:
        print(json.dumps({'status':'existing_evaluation_retained','started':len(started),'finished':len(finished),
                          'new_model_runs':0,'next':'Use research73.evaluate to recheck records. Repeat inference only in a separate copied workspace/version; do not overwrite this evaluation.'}))
        return
    subprocess.run([str(ROOT/'.cache/stage6-env/Scripts/python.exe'),'-E','-s','-u','-m','research73.agent_worker'],cwd=ROOT,check=True)


if __name__=='__main__':main()
