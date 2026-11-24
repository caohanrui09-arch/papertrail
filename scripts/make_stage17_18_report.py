"""Seal actual independent-runtime replay and local API results without new tuning."""
import contextlib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

from .manage_stage17_env import BASE, VENV, environment


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main() -> None:
    for number in (17, 18):
        if Path(f'reports/stage{number}/final-validation.json').exists():
            raise ValueError('Refuse to overwrite sealed extension stage')
    replay = json.loads((BASE/'replica/data/relocated-run.json').read_text(encoding='utf-8'))
    io = json.loads((BASE/'replica/data/isolated-io-proof.json').read_text())
    http = json.loads(Path('reports/stage18/http-validation.json').read_text())
    policy = json.loads(Path('reports/stage18/policy-validation.json').read_text())
    lifecycle = json.loads(Path('reports/stage18/lifecycle-validation.json').read_text())
    if replay['status'] != 'passed' or not replay['frozen_model_signature_exact'] or not replay['three_method_traces_exact']:
        raise ValueError('Independent runtime replay did not pass')
    if io['old_root_read_attempts'] or io['network_attempts']:
        raise ValueError('Replay escaped declared isolation')
    if http['status'] != 'passed' or http['observed_bind_addresses'] != ['127.0.0.1'] or policy['failures'] or policy['errors']:
        raise ValueError('Local HTTP/policy checks failed')
    if not lifecycle['stop_command_passed'] or not lifecycle['endpoint_unreachable_after_stop'] or not lifecycle['restarted_ready'] or not lifecycle['instance_changed']:
        raise ValueError('Lifecycle checks incomplete')
    from gsearch.relocated_demo import verify_bundle
    bundle = verify_bundle(BASE/'replica')
    # Read actual installed metadata with fresh Python; no old environment path bridge.
    code = "import importlib.metadata as m,json;print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"
    process = subprocess.run([str(VENV/'Scripts/python.exe'),'-E','-s','-c',code],cwd=BASE/'replica',
        env=environment(),check=True,capture_output=True,text=True)
    installed = json.loads(process.stdout)
    normalize = lambda name: re.sub(r'[-_.]+','-',name).lower()
    versions = {normalize(k):v for k,v in installed.items()}
    locked = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)',Path('reports/stage17/requirements-win-cpu.lock').read_text(),re.M))
    locked['torch'] = '2.6.0+cpu'
    if any(versions.get(normalize(name)) != version for name,version in locked.items()):
        raise ValueError('Service addition altered a base-runtime pin')
    log = Path('.cache/stage18/regression-tests.log')
    with log.open('w',encoding='utf-8') as stream, contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        tests = unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.discover('tests'))
    if not tests.wasSuccessful(): raise ValueError('Regression tests failed; see private log')
    from gsearch.benchmark_cold_fusion import history
    from gsearch.showcase import verify_receipt
    history()
    verify_receipt(Path('reports/stage15/final-validation.json'),('outputs','code','data','report'))
    verify_receipt(Path('reports/stage16/final-validation.json'),('code','materials','outputs','private_data','report'))
    from scripts.local_service_control import request, STATE
    state = json.loads(STATE.read_text()); status,health=request('GET','/health',port=state['port'])
    if status != 200 or health['instance_id'] != state['instance_id']:
        raise ValueError('Final accepted local instance is not ready')
    save(Path('reports/stage17/runtime-versions.json'),{'base_pins_verified':len(locked),'installed_versions':installed,
        'service_dependencies_added_after_base_replay':len(installed)-len(locked),
        'cpu_only':True,'python':'3.12.3','same_physical_machine':True})
    save(Path('reports/stage17/isolation-summary.json'),{**replay,'python_io_audit':io})
    report17 = f'''# 第十七阶段：同机独立运行时与迁移复现

已在新的CPython3.12.3、新CPU轮子环境和新绝对路径副本中复现万篇推荐→原v1读取，原模型签名及三路完整工具轨迹精确一致。用户目前只有当前电脑，因此**不把本阶段描述为真实第二台机器或跨OS验收**。

uv0.13.6官方Windows归档SHA在执行前核验，MIT/Apache许可与固定文档见upstream-audit。CPython由独立发行版安装，未启用user-site、写注册表或全局PATH；不沿用旧Miniconda标准库/父目录CUDA包。基础{len(locked)}包全部哈希锁定，Torch2.6.0+cpu替代共享CUDA构建；阶段18添加服务包后基础版本逐一确认未变，当前共{len(installed)}个包，原生uv pip check通过。

迁移副本{len(bundle['files'])}项资产包括10000篇明确v1和409份官方响应。训练CSV、文本、原始元数据和旧实现字节保持一致；只在内存中把raw_path映射到新副本。新代码只是定位/校验适配，原SAR、TFIDF、分支门控及原解析器直接复用。

Python层审计记录{io['application_file_opens']}次文件打开，旧根路径读取尝试0、socket连接尝试0；所有已导入文件模块与sys.path位于新隔离根。负向测试实际拒绝旧根文件读取与连接尝试。该检查不是OS容器或对恶意原生扩展的安全隔离证明。

保留的失败：首次直连官方归档被主机连接中止，沿用既有代理后TLS/哈希校验成功；首次回放因Transformers提前从venv加载sklearn被旧来源检查拒绝，启动器改为先加入本副本的目标目录，未放宽检查。一次直接uv检查漏设缓存目录、被沙箱拒绝持久化；改走项目内cache后检查通过。Docker客户端存在但引擎未运行，未启动系统守护进程。pip-tools原仓库重定向和部分uv源码路径不可读均如实记录。

{tests.testsRun}项原回归与迁移边界测试通过，旧阶段3—16冻结资产不变。仍未从空机器重新获取全部历史资产、完整重训早期T5或取得新独立反馈时段；公开评分源main仍为92b0fac，与旧源相同。

重建布局、步骤和边界见[独立回放说明](../docs/ISOLATED_REPLAY.md)。原用户派生资产仅留本地忽略目录，不作为公开安装包分发。
'''
    report18 = f'''# 第十八阶段：仅回环地址的本地工具服务

本地服务已实际启动、停止并重新启动，当前就绪地址为http://127.0.0.1:{state['port']}。采用固定FastAPI0.162.0/Pydantic原生验证、Uvicorn0.54.0 ASGI；GitHub源码、许可、Flask对照与适配边界见upstream-audit。服务运行在阶段17新CPU环境和迁移副本，不依赖旧CUDA包；无云费用、无公网绑定。

接口提供健康状态、原生schema、固定用户/时点/方法会话、推荐、原v1读取和会话清理。默认content；rrf0.5/cold_aware0.25是固定研究对照，未开放参数调优。各会话调用原ExpansionSession与smolagents工具，不重新实现Agent循环；源读取继续校验原始响应hash、ID与v1文本。

真实HTTP共{http['http_requests']}项检查通过：三路与冻结演示的排名/摘要精确相同；先推荐后读取；4次成功调用预算；64会话容量；未知/已删除会话、严格k1—10、时区/训练截止、额外参数、方法枚举均被正确处理。实际监听地址仅127.0.0.1。独立新API运行时还通过{policy['native_api_policy_tests']}项状态测试，含可控时钟TTL过期，未把等待15分钟当作已执行。

后台启动器首次使用PowerShell捕获输出，后台句柄导致返回等待；服务健康当时已能响应。核对实例/解释器后只停止该进程，改用CREATE_NO_WINDOW的原生进程句柄和私有日志。现一键启动可返回，状态独立可查；停止检查PID创建时间/模块/路径，端口停止后不可访问，重启实例已改变并再次就绪。未停止任何其他服务。

{tests.testsRun}项回归/迁移测试、原生API状态测试及HTTP检查均通过，旧阶段3—16不变。访问日志关闭、会话仅内存/创建后15分钟TTL、最大64、调用串行锁保护；公开报告只有聚合结果，原HTTP响应和日志在忽略的.cache/stage18。该本地原型未提供生产鉴权、跨机部署或并发QPS保证。

```powershell
.\\service.cmd start
.\\service.cmd status
.\\service.cmd stop
```

调用样例和状态码见[本地服务说明](../docs/LOCAL_SERVICE.md)。本阶段没有新增万篇T5检索、统一LLM自主策略、反馈学习或线上CTR/AB效果；新独立评分时段尚无可用源，后续按共同语料与独立评价协议推进，不改称旧dev为新测试。
'''
    p17=Path('reports/阶段17_独立运行时与迁移复现.md');p17.write_text(report17,encoding='utf-8')
    p18=Path('reports/阶段18_本地工具服务验收.md');p18.write_text(report18,encoding='utf-8')
    code17=('scripts/bootstrap_stage17_runtime.py','scripts/manage_stage17_env.py','scripts/prepare_stage17_bundle.py',
        'scripts/run_stage17_replay.py','gsearch/relocated_demo.py','tests/test_relocation.py','requirements-stage17.in','requirements-stage17-sklearn.in')
    code18=('gsearch/local_service.py','scripts/local_service_control.py','scripts/validate_local_service.py',
        'scripts/probe_local_service_state.py','scripts/make_stage17_18_report.py','requirements-stage18.in','service.cmd')
    for number,code,report,doc in ((17,code17,p17,Path('docs/ISOLATED_REPLAY.md')),(18,code18,p18,Path('docs/LOCAL_SERVICE.md'))):
        folder=Path(f'reports/stage{number}')
        receipt={'regression_tests':tests.testsRun,'failures':len(tests.failures),'errors':len(tests.errors),
            'stages3_16_unchanged':True,'physical_second_machine_tested':False,
            'code':{p:digest(Path(p)) for p in code},'docs':{str(doc):digest(doc)},
            'outputs':{str(p):digest(p) for p in sorted(folder.iterdir()) if p.is_file()},
            'report':{str(report):digest(report)}}
        if number==17:receipt['private_replay_assets']={str(BASE/'replica'/'bundle-manifest.json'):digest(BASE/'replica'/'bundle-manifest.json'),
            str(BASE/'replica/data/relocated-run.json'):digest(BASE/'replica/data/relocated-run.json'),
            str(BASE/'replica/data/isolated-io-proof.json'):digest(BASE/'replica/data/isolated-io-proof.json')}
        else:receipt.update({'http_checks':http['http_requests'],'api_policy_tests':policy['native_api_policy_tests'],
            'loopback_only':True,'url':f"http://127.0.0.1:{state['port']}",'running_at_acceptance':True,
            'service_state_is_mutable_and_not_sealed':True})
        save(folder/'final-validation.json',receipt)
    print(json.dumps({'tests':tests.testsRun,'http_checks':http['http_requests'],'api_policy_tests':policy['native_api_policy_tests'],
        'replay_exact':True,'service_ready':True,'reports':[str(p17),str(p18)]},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
