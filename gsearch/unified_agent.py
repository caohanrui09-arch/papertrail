"""Native smolagents client over the same loopback tools as the fixed policy."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def request(method: str, path: str, data: dict | None = None, port: int = 8766) -> tuple[int, dict]:
    if not 1024 <= port <= 65535 or not path.startswith('/sessions') and path != '/health':
        raise ValueError('Local paper-service route required')
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=body, method=method,
        headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=120) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


class ToolClient:
    def __init__(self, task: dict, port: int = 8766):
        self.port = port
        code, response = request('POST', '/sessions', {'user_id': task['user_id'], 'at': task['at'], 'method': 'content'}, port)
        if code != 200:
            raise ValueError(f'Session failed: {code}')
        self.token = response['session_id']
        self.accepted: dict | None = None
        self.accepted_input: dict | None = None

    def call(self, name: str, **arguments: object) -> dict:
        code, response = request('POST', f'/sessions/{self.token}/tools', {'name': name, 'arguments': arguments}, self.port)
        if code != 200:
            raise ValueError(str(response.get('detail', response)))
        return response

    def finalize(self, answer: object) -> dict:
        parsed = json.loads(answer) if isinstance(answer, str) else answer
        if not isinstance(parsed, dict) or set(parsed) != {'citations'}:
            raise ValueError('Answer must contain exactly citations')
        if self.accepted is not None:
            if parsed != self.accepted_input:
                raise ValueError('Already accepted a different answer')
            return self.accepted
        self.accepted = self.call('finalize', citations=parsed['citations'])
        self.accepted_input = parsed
        return self.accepted

    def snapshot(self) -> dict:
        code, response = request('GET', f'/sessions/{self.token}', port=self.port)
        if code != 200:
            raise ValueError('Session trace unavailable')
        return response

    def close(self) -> None:
        request('DELETE', f'/sessions/{self.token}', port=self.port)


def make_tools(client: ToolClient) -> list:
    from smolagents import tool

    @tool
    def search_papers(query: str, k: int = 3) -> str:
        """Search unread available papers by topic using native BM25.

        Args:
            query: Exact supplied query or a short English topic, up to 2000 characters.
            k: Number of papers from 1 to 3 for this controlled policy.
        """
        if type(k) is not int or not 1 <= k <= 3:
            # Server still records/bills invalid attempts instead of local repair.
            return json.dumps(client.call('search_papers', query=query, k=0))
        return json.dumps(client.call('search_papers', query=query, k=k), ensure_ascii=False)

    @tool
    def recommend_papers(k: int = 3) -> str:
        """Recommend unread available papers for the session's bound user.

        Args:
            k: Number of papers from 1 to 3 for this controlled policy.
        """
        return json.dumps(client.call('recommend_papers', k=k if type(k) is int and 1 <= k <= 3 else 0), ensure_ascii=False)

    @tool
    def read_paper(doc_id: str) -> str:
        """Read the verified original v1 abstract of a returned paper.

        Args:
            doc_id: Exact ID previously returned by search_papers or recommend_papers.
        """
        return json.dumps(client.call('read_paper', doc_id=doc_id), ensure_ascii=False)

    return [search_papers, recommend_papers, read_paper]


def fixed(client: ToolClient, task: dict) -> dict:
    selected = []
    if task['intent'] in ('search', 'mixed', 'empty'):
        hits = client.call('search_papers', query=task['query'], k=3)['papers']
        if hits:
            selected.append(hits[0]['doc_id'])
    if task['intent'] in ('recommend', 'mixed'):
        hits = client.call('recommend_papers', k=3)['papers']
        fresh = [p['doc_id'] for p in hits if p['doc_id'] not in selected]
        if fresh:
            selected.append(fresh[0])
    citations = []
    for doc in selected:
        client.call('read_paper', doc_id=doc)
        citations.append({'doc_id': doc, 'quote_index': 0})
    return client.finalize({'citations': citations})


def llm(client: ToolClient, task: dict, model: object) -> tuple[dict | None, dict]:
    from smolagents import ToolCallingAgent
    from .bundle_session import BundleBudget
    model.reset_budget(BundleBudget(max_steps=8, input_tokens=30000, output_tokens=1280))

    def final_check(answer: object, agent: object) -> bool:
        client.finalize(answer)
        return True

    agent = ToolCallingAgent(model=model, tools=make_tools(client), max_steps=7, max_tool_threads=1,
        final_answer_checks=[final_check], verbosity_level=0)
    prompt = Path(__file__).parent / 'prompts/unified.txt'
    agent.prompt_templates['system_prompt'] = prompt.read_text(encoding='utf-8')
    answer = None
    error = None
    try:
        answer = agent.run(json.dumps({key: task[key] for key in ('intent', 'query', 'instruction')}, ensure_ascii=False))
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    steps = [step.dict() for step in agent.memory.steps]
    exhausted = any(step.get('error', {}).get('type') == 'AgentMaxStepsError' for step in steps if step.get('error'))
    if error is None and not exhausted:
        try:
            client.finalize(answer)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            error = str(exc)
    result = client.accepted if error is None and not exhausted else None
    return result, {'error': error, 'framework_steps_exhausted': exhausted, 'steps': steps,
        'unverified_model_final': str(answer), 'llm_usage': {k: v for k, v in asdict(model.meter).items() if k != 'budget'},
        'prompt_sha256': hashlib.sha256(prompt.read_bytes()).hexdigest()}


def run(task: dict, policy: str, model: object | None = None, port: int = 8766) -> dict:
    start = time.perf_counter()
    client = ToolClient(task, port)
    result = None
    metadata = {}
    error = None
    try:
        if policy == 'fixed':
            result = fixed(client, task)
        elif policy == 'llm_agent':
            result, metadata = llm(client, task, model)
        else:
            raise ValueError('Unknown policy')
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
    finally:
        trace = client.snapshot()
        client.close()
    return {'task_id': task['id'], 'policy': policy, 'completed_protocol': result is not None,
        'answer': result, 'trace': trace, 'metadata': metadata, 'error': error,
        'seconds': time.perf_counter() - start}


def load_model() -> object:
    import torch
    from .budget_model import BudgetedToolModel
    from .qwen_messages import native_history

    class NativeQwenToolModel(BudgetedToolModel):
        def _prepare_completion_args(self, messages: list, *args: object, **kwargs: object) -> dict:
            # Native role-conversion API, then the original Transformers
            # apply_chat_template/generate and cumulative meter own execution.
            kwargs['custom_role_conversions'] = {'tool-call': 'assistant', 'tool-response': 'tool'}
            return super()._prepare_completion_args(native_history(messages), *args, **kwargs)

    torch.set_num_threads(4)
    return NativeQwenToolModel(model_id='.cache/models/Qwen2.5-1.5B-Instruct',
        device_map='cuda' if torch.cuda.is_available() else 'cpu',
        torch_dtype='bfloat16' if torch.cuda.is_available() else 'float32',
        model_kwargs={'local_files_only': True}, do_sample=False, max_new_tokens=160)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', choices=('fixed', 'llm_agent'), default='fixed')
    parser.add_argument('--intent', choices=('search', 'recommend', 'mixed'), default='recommend')
    parser.add_argument('--query', default='')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.intent in ('search', 'mixed') and not args.query.strip():
        raise ValueError('Search/mixed requires --query')
    import tempfile
    root = Path('data/stage19-unified').resolve(); root.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='demo-', dir=root)) / 'result.json'
    if not output.is_relative_to(root) or output.exists():
        raise ValueError('Use a new output inside private data/stage19-unified/')
    task = {'id': 'local-demo', 'user_id': None, 'at': '2025-02-23T05:28:26.401006+00:00',
        'intent': args.intent, 'query': args.query, 'instruction': 'Return one search paper' if args.intent == 'search' else
        'Return one personalized recommendation' if args.intent == 'recommend' else 'Return one search paper and one different personalized recommendation'}
    result = run(task, args.policy, load_model() if args.policy == 'llm_agent' else None)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if result['answer']:
        print(result['answer']['answer'], flush=True)
    print(json.dumps({'output': str(output), 'completed_protocol': result['completed_protocol']}), flush=True)
    if not result['completed_protocol']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
