"""One-time explicit adaptation of the new, unsealed v24 UI copy."""
from pathlib import Path


def main():
    path=Path('web/papertrail-v24/dist/app.mjs')
    s=path.read_text(encoding='utf-8')
    def replace(old,new):
        nonlocal s
        if old not in s:raise ValueError('Missing UI adaptation anchor: '+old[:80])
        s=s.replace(old,new)
    replace("const html=htm.bind(h);", "const html=htm.bind(h);\nconst profileLabel=p=>p==='personal'?'我的收藏画像':p==='warm'?'训练画像用户':'冷启动用户';")
    replace("papertrail.thread", "papertrail.v24.thread")
    replace("[profile,setProfile]=useState('warm')", "[profile,setProfile]=useState('personal')")
    replace("function PaperCard({paper,onRead,copy})", "function PaperCard({paper,onRead,copy,feedback,prefs,disabled})")
    replace('<h3>${paper.title}</h3><blockquote>', '<h3>${paper.title}</h3><${PreferenceButtons} paper=${paper} prefs=${prefs} feedback=${feedback} disabled=${disabled}/><${Reason} explanation=${paper.explanation}/><blockquote>')
    replace('function Message({run,onRead,openTrace,copy,retry})', 'function Message({run,onRead,openTrace,copy,retry,feedback,prefs,disabled})')
    replace("const fallback=run.trace?", "const fallback=run.trace?")
    replace("run.params?.query||(run.params?.profile==='cold'?'为冷启动用户推荐未读论文。':'根据我的训练画像，推荐一篇未读论文。')", "run.params?.query||(run.params?.profile==='personal'?'根据我的收藏，推荐未读论文。':run.params?.profile==='cold'?'为冷启动用户推荐未读论文。':'根据训练画像，推荐一篇未读论文。')")
    replace("${run.params?.profile==='cold'?'冷启动用户':'训练画像用户'}", "${profileLabel(run.params?.profile)}${run.profile_revision!=null?' · 偏好版本 '+run.profile_revision:''}")
    replace('该用户没有训练画像，本次推荐使用流行度回退。', '暂无有效兴趣画像，本次按冻结训练期点赞数回退推荐。')
    replace('paper=${p} onRead=${paper=>onRead({...paper,runId:run.id},run)} copy=${copy}', "paper=${{...p,explanation:papersOf(run).find(x=>x.doc_id===p.doc_id)?.explanation}} onRead=${paper=>onRead({...paper,runId:run.id},run)} copy=${copy} feedback=${(paper,value)=>feedback(paper,value,run.id)} prefs=${prefs} disabled=${disabled}")
    replace("  const scroll=useRef(null)", "  const [prefs,setPrefs]=useState({revision:0,items:[]}),[saving,setSaving]=useState(false),[quality,setQuality]=useState(null),[resetReady,setResetReady]=useState(false);\n  const scroll=useRef(null)")
    replace("api('/config').then(setConfig)", "api('/profile').then(setPrefs).catch(e=>setToast(e.message));api('/config').then(setConfig)")
    replace("profile:picked.profile||'warm'", "profile:picked.profile||'personal'")
    replace("  const allRuns=", '''  async function feedback(paper,value,runId){if(saving||busy)return;setSaving(true);try{setPrefs(await api('/profile/feedback',jsonPost({doc_id:paper.doc_id,value,revision:prefs.revision,run_id:runId||null})));setToast(value==='like'?'已收藏，下次推荐将使用新画像':value==='hide'?'已设为不感兴趣，下次结果将过滤这篇论文':'已移除偏好');}catch(e){setToast(e.message);api('/profile').then(setPrefs).catch(()=>{});}finally{setSaving(false);}}
  async function resetProfile(){if(!resetReady){setResetReady(true);return;}setSaving(true);try{setPrefs(await api('/profile/reset',jsonPost({revision:prefs.revision})));setResetReady(false);setToast('偏好已重置；旧会话仍保留当时的结果');}catch(e){setToast(e.message);api('/profile').then(setPrefs).catch(()=>{});}finally{setSaving(false);}}
  async function showQuality(){setModal({type:'quality'});try{setQuality(await api('/quality-status'));}catch(e){setToast(e.message);}}
  const allRuns=''' )
    replace('<nav><button class="nav-item active"', '<nav><button class="nav-item" onClick=${()=>{setResetReady(false);setModal({type:\'profile\'});api(\'/profile\').then(setPrefs).catch(e=>setToast(e.message));}}><${Icon} name="Heart"/>我的兴趣<span class="small-count">${prefs.items.filter(x=>x.preference===\'like\').length}</span></button><button class="nav-item" onClick=${showQuality}><${Icon} name="Check"/>人工评价准备</button><button class="nav-item active"')
    replace('根据训练画像推荐未读论文', '从你的收藏建立兴趣，发现未读论文')
    replace('copy=${copy} retry=${perform}', 'copy=${copy} retry=${perform} feedback=${feedback} prefs=${prefs} disabled=${busy||saving}')
    replace("${profile==='warm'?'训练画像用户':'冷启动用户'}", '${profileLabel(profile)}')
    replace('历史回放 · 2025-02-23', '冻结目录 · 2025-02-23')
    replace('<h2>${selected.title}</h2><${SourceLink}', '<h2>${selected.title}</h2><${PreferenceButtons} paper=${selected} prefs=${prefs} disabled=${busy||saving} feedback=${(p,v)=>feedback(p,v,selected.runId)}/><${Reason} explanation=${selected.explanation}/><${SourceLink}')
    replace('<div class="candidate-intro">本次真实检索与推荐返回的候选。<br/>点击论文查看原始摘要。</div>', '<div class="candidate-intro">本次真实检索与推荐返回的候选。<br/>点击论文阅读，或收藏来建立兴趣。</div>')
    replace('html`<button class="candidate-card"', 'html`<div class="candidate-wrap"><button class="candidate-card"')
    replace('<span class="candidate-id">arXiv ${p.doc_id}</span></button>`', '<span class="candidate-id">arXiv ${p.doc_id}</span></button><${PreferenceButtons} paper=${p} prefs=${prefs} disabled=${busy||saving} feedback=${(p,v)=>feedback(p,v,latest.id)}/><${Reason} explanation=${p.explanation}/></div>`')
    replace("modal.type==='trace'?'真实调用轨迹':modal.type==='settings'?'工作台设置':modal.type==='evidence'?'实验与证据':", "modal.type==='profile'?'我的兴趣':modal.type==='quality'?'人工评价准备':modal.type==='trace'?'真实调用轨迹':modal.type==='settings'?'工作台设置':modal.type==='evidence'?'实验与证据':")
    replace("${modal.type==='settings'?html`", "${modal.type==='profile'?html`<p class=\"modal-description\">收藏用于构建内容兴趣；不感兴趣只过滤对应论文，不推断整个主题。变更用于下一次请求，旧会话保留原结果。</p><div class=\"profile-summary\"><strong>${prefs.items.filter(x=>x.preference==='like').length} 篇收藏</strong><span>${prefs.items.filter(x=>x.preference==='hide').length} 篇不感兴趣 · 版本 ${prefs.revision}</span></div><button class=\"new-thread\" disabled=${busy||saving} onClick=${()=>{setProfile('personal');setModal(null);perform({mode:'recommend',query:'',profile:'personal'});}}>用当前兴趣更新推荐</button>${prefs.items.length?prefs.items.map(p=>html`<div class=\"preference-row\"><span>${p.preference==='like'?'收藏':'不感兴趣'} · ${p.doc_id}v${p.version}</span><h3>${p.title}</h3><${SourceLink} paper=${p}/><button class=\"text-button\" disabled=${busy||saving} onClick=${()=>feedback(p,'none')}>移除偏好</button></div>`):html`<div class=\"profile-empty\">还没有偏好。先搜索一个主题，在论文卡片上点“收藏”。没有收藏时使用训练期流行度回退。</div>`}<button class=\"reset-profile\" disabled=${busy||saving||!prefs.items.length} onClick=${resetProfile}>${resetReady?'确认清空全部偏好':'重置我的偏好'}</button>${resetReady&&html`<button class=\"text-button\" onClick=${()=>setResetReady(false)}>取消重置</button>`}<p class=\"small-note\">仅此浏览器空间。清除浏览器 Cookie 会失去此空间的访问凭据。偏好独立于实验数据，不算人工相关性标签。</p>`:modal.type==='quality'?html`<p class=\"modal-description\">先确认需求，再盲标候选。模型草稿和自动化测试都不能代替真人判断。</p><p>已有 24 条需求草稿、423 个盲标候选对。标注按“不相关 / 部分相关 / 高度相关”进行。</p><pre class=\"quality-state\">${quality?JSON.stringify(quality,null,2):'正在核查本地标注状态…'}</pre><p class=\"small-note\">使用项目 docs/QUALITY_ANNOTATION.md 与 annotation-status.cmd 继续原流程；当前页面仅查看状态，不自动填写标签。完成 tuning 后冻结配置，再评价后段。</p>`:modal.type==='settings'?html`")
    replace('<option value="warm">训练画像用户', '<option value="personal">我的收藏画像 · 当前浏览器偏好</option><option value="warm">训练画像用户')
    replace('这里不会自动加入今天的新论文，也不会回写用户反馈。', '个人收藏独立保存；预设训练画像保持不变。当前偏好作用于历史目录，不代表历史回放质量。')
    replace('这些设置只控制展示请求，不更新训练历史。', '选择自己的收藏画像，或切换到冻结的实验演示画像。')
    insertion='''
function PreferenceButtons({paper,prefs,feedback,disabled}){const value=prefs.items.find(p=>p.doc_id===paper.doc_id)?.preference;return html`<div class="preference-actions"><button disabled=${disabled} class=${value==='like'?'active':''} aria-pressed=${value==='like'} onClick=${()=>feedback(paper,value==='like'?'none':'like')}><${Icon} name="Heart" size=${13}/>${value==='like'?'已收藏':'收藏'}</button><button disabled=${disabled} class=${value==='hide'?'active':''} aria-pressed=${value==='hide'} onClick=${()=>feedback(paper,value==='hide'?'none':'hide')}><${Icon} name="X" size=${13}/>${value==='hide'?'撤销不感兴趣':'不感兴趣'}</button></div>`;}
function Reason({explanation:e}){if(!e)return null;return html`<details class="recommend-reason"><summary>为什么推荐${e.kind==='popularity_fallback'?' · 流行度回退':''}</summary>${e.kind==='popularity_fallback'?html`<p>${e.reason}，训练期 ${e.training_likes} 次点赞。</p>`:html`<p>与收藏画像的内容相似度 ${e.cosine.toFixed(4)}。${e.anchors.length?'主要关联这些收藏：':'没有非零词项重合；零分按论文 ID 排序。'}</p>${e.anchors.map(a=>html`<div class="reason-anchor"><${SourceLink} paper=${a}>${a.title}</${SourceLink}><small>对总分贡献 ${a.score_contribution.toFixed(4)}</small></div>`)}<div class="reason-terms">${e.terms.map(t=>html`<span>${t.term} <small>${t.contribution.toFixed(4)}</small></span>`)}</div><p class="small-note">仅解释实际词项与收藏贡献，不代表语义正确性。偏好版本 ${e.profile_revision}。</p>`}</details>`;}
'''
    replace('function App(){',insertion+'\nfunction App(){')
    path.write_text(s,encoding='utf-8')


if __name__=='__main__':main()
