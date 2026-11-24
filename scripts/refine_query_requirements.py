"""Create a new assistant-authored requirements draft; never edit frozen query pools."""
import csv
import hashlib
import json
from pathlib import Path

SOURCE=Path('data/stage20-quality/inputs/queries.json')
OUT=Path('data/stage25-requirements')

# English request, Chinese request, required focus, secondary preference,
# partial-relevance boundary, unrelated boundary. No document judgments.
DRAFTS=[
('Find papers on sequence-to-sequence retrieval that directly generates document identifiers. I would also like comparisons with lexical retrieval such as BM25.',
 '查找通过序列到序列模型直接生成文档ID来完成检索的论文，优先包含与BM25等词法检索的对照。',
 '直接生成文档ID用于检索', '与词法检索对照', '只讨论生成式检索的某个组件，或无法从摘要确认是否直接输出文档ID', '仅生成回答、生成扩展查询或普通向量检索，未涉及生成文档ID'),
('Using the supplied reading history as context, recommend papers about how document identifiers are designed or learned for generative document retrieval.',
 '结合提供的阅读上下文，推荐研究生成式文档检索中ID如何设计或学习的论文。',
 '文档ID的设计或学习用于生成式文档检索', '与提供上下文的研究问题有联系', '涉及生成式文档检索但摘要未说明ID设计或学习', '仅讨论推荐物品ID或普通数据库主键，未涉及文档检索'),
('Find papers that retrieve documents by generating their identifiers, and use the supplied reading history to prioritize useful follow-up reading.',
 '查找直接生成文档ID进行检索的论文，并结合提供的阅读上下文确定后续阅读顺序。',
 '直接生成文档ID用于检索', '适合作为上下文论文的后续阅读', '只涉及该检索链路的局部组件或抽象描述不足以确认输出形式', '只涉及回答生成、工具调用或词法检索'),
('Find papers on learned semantic item identifiers or codebooks for generative recommendation. Prioritize papers explaining how the identifiers represent items; handling newly added items is a secondary interest.',
 '查找生成式推荐中学习语义物品ID或码本的论文，重点看ID如何表示物品，兼顾新物品加入时的处理。',
 '学习得到的语义物品ID或码本用于生成式推荐', '物品表征、码本学习及新物品处理', '仅研究语义量化或推荐表征，摘要未明确其用于生成式推荐ID', '仅研究图像压缩码本、文档编号或其他无推荐关联的ID'),
('Recommend papers on learned semantic identifiers for generative recommendation, using the supplied history to favor relevant connections in item representation learning.',
 '结合提供的阅读上下文，推荐生成式推荐中的语义ID研究，优先与物品表征学习有关的论文。',
 '语义ID用于生成式推荐', '物品表征学习与上下文联系', '涉及生成式推荐但未说明语义ID，或只有通用表征学习', '纯词法检索或未涉及推荐的通用量化'),
('Find work on learning semantic item identifiers for generative recommendation, then prioritize papers whose representation-learning ideas connect to the supplied history.',
 '查找学习语义物品ID的生成式推荐工作，再结合提供上下文优先排列相关表征学习思路。',
 '学习语义物品ID用于生成式推荐', '表征学习方法与上下文联系', '覆盖语义ID或生成式推荐中的一部分，关联关系在摘要中不明确', '无物品推荐场景或不涉及学习的语义标识'),
('Find recommendation methods that can score items with no previous interactions by using their text or other content features. Distinguish item cold start from user cold start.',
 '查找使用文本或其他内容特征，为没有历史交互的物品打分的推荐方法；区分物品冷启动和用户冷启动。',
 '利用内容为无交互物品推荐或打分', '明确区分用户冷启动与物品冷启动', '内容推荐或冷启动相关，但摘要未明确无交互物品条件', '仅解决新用户问题或已有大量交互物品的普通协同过滤'),
('Using the supplied history, recommend studies combining collaborative and content signals for items with no interactions. Favor analyses of how missing collaborative support affects ranking.',
 '结合提供的阅读上下文，推荐协同与内容融合处理无交互物品的研究，优先解释缺少协同支持如何影响排序。',
 '协同与内容结合处理物品冷启动', '缺失协同信号对排序的影响及上下文联系', '只有内容推荐或通用融合，未明确物品冷启动', '仅有充分交互物品的纯协同方法，或只讨论新用户'),
('Find papers on item cold start using content features, and prioritize follow-up reading that complements the supplied history. Studies comparing content-only and collaborative-content methods are especially useful.',
 '查找使用内容特征解决物品冷启动的论文，结合提供上下文推荐后续阅读，优先有纯内容与协同内容融合对照的研究。',
 '内容特征用于物品冷启动', '纯内容与融合对照、补充已有阅读', '讨论内容推荐或物品冷启动但二者关系不明确', '仅讨论新用户或与推荐无关的冷启动计算问题'),
('Find papers on learning recommendation models from implicit feedback while accounting for unequal exposure or unobserved feedback. I want the assumptions about missing observations to be stated.',
 '查找从隐式反馈学习推荐、同时考虑曝光不均或未观测反馈的论文，重点关注缺失观测假设。',
 '隐式反馈推荐中的曝光或未观测反馈建模', '明确缺失观测假设', '涉及隐式推荐或偏差校正，但摘要不能确认曝光或缺失反馈处理', '只把未点击当作已知负例而没有相关建模，或非推荐场景的一般缺失值处理'),
('Using the supplied history, recommend papers on unbiased or counterfactual offline evaluation of recommendation policies, especially their exposure or logging-policy assumptions.',
 '结合提供上下文，推荐推荐策略的无偏或反事实离线评价研究，优先说明曝光或日志策略假设的论文。',
 '推荐策略的无偏或反事实离线评价', '曝光/日志策略假设及上下文联系', '只研究去偏训练或通用反事实方法，离线推荐评价联系不明确', '普通离线排序指标报告，未涉及无偏或反事实评价'),
('Find studies of exposure bias in recommendation, then prioritize papers related to the supplied history that explain the assumptions behind offline evaluation.',
 '查找推荐中的曝光偏差研究，再结合提供上下文优先阅读解释离线评价假设的论文。',
 '推荐曝光偏差及其离线评价问题', '评价假设可理解、与上下文有关', '只覆盖曝光偏差训练或泛化的评价，未明确两者联系', '与曝光偏差无关的普通推荐精度比较'),
('Find papers evaluating tool-using language-model agents under explicit tool-call, token, or latency budgets. I want completion and failure measures as well as resource usage.',
 '查找在明确工具调用、token或延迟预算下评价语言模型Agent的论文，同时关注完成情况、失败和资源消耗。',
 '工具型语言模型Agent的评价包含明确资源预算或成本', '任务完成和失败指标与成本并报', '有工具Agent评价但资源限制或成本未说明', '仅做语言能力测试、普通聊天或与工具Agent无关的规划'),
('Using the supplied history, recommend papers on reliable tool calling or resource-aware planning for language-model agents. Favor work that analyzes invalid actions, repeated calls, or unfinished tasks.',
 '结合提供上下文，推荐语言模型Agent可靠工具调用或资源感知规划的论文，优先分析非法动作、重复调用或未完成任务。',
 '语言模型Agent的工具可靠性或资源感知规划', '具体失败分析及上下文联系', '通用Agent规划但没有工具可靠性或资源关注', '纯聊天、提示词写作或无工具的文本生成'),
('Find studies comparing language-model agent planning with fixed tool workflows, and use the supplied history to prioritize relevant follow-up reading. Comparisons should make their task and resource conditions clear.',
 '查找语言模型Agent规划与固定工具流程的对照研究，结合提供上下文排序，优先明确任务和资源条件的比较。',
 '语言模型Agent规划与固定流程或规则流程有直接比较', '共同任务/资源条件和上下文联系', '有工具Agent或工作流研究，但没有明确的固定流程对照', '无工具Agent研究或只有普通语言模型之间的比较'),
('Find papers on whether citations in retrieval-augmented answers support the associated claims, and how that support is evaluated.',
 '查找检索增强回答中的引用是否支持对应论断、以及如何评价这种支持关系的论文。',
 '检索增强回答中引用与论断的支持关系及评价', '区分引用存在、可追溯与内容支持', '有带引用的RAG，但只报告可追溯链接或一般回答精度', '仅参考文献格式、文献计量或不含引用支持的通用检索'),
('Using the supplied history, recommend research on retrieving evidence for language-model answers grounded in source citations.',
 '结合提供上下文，推荐为带来源引用的语言模型回答检索证据的研究。',
 '证据检索服务于带来源依据的语言模型回答', '与提供上下文的证据或引用问题相关', '有证据检索或RAG但未明确回答的来源依据', '只做普通搜索、引用格式生成或无证据自由回答'),
('Find retrieval-augmented generation methods with source-grounded citations, then prioritize connections to the supplied history. Evidence-support verification is a preferred feature, not an assumed property.',
 '查找带来源依据引用的检索增强生成方法，结合提供上下文确定阅读顺序；优先含证据支持核验，不预设引用就一定正确。',
 '检索增强生成提供与原来源关联的引用', '证据支持核验与上下文联系', '一般RAG或只有来源展示，引用与回答的关联不明确', '无检索来源的回答生成或仅文献列表管理'),
('Find methods that add newly available documents or items to a search or recommendation index without retraining the full model for each update.',
 '查找把新文档或新物品加入搜索或推荐索引的方法，重点关注每次更新无需重训整个模型。',
 '检索或推荐索引增量纳入新对象并减少全模型重训', '说明更新范围与更新成本', '动态检索/推荐相关，但摘要未说明索引更新或重训范围', '静态索引、仅用户画像变化或与搜索推荐无关的增量学习'),
('Using the supplied history, recommend papers on time-aware recommendation or changing user interests. Connections to maintaining retrieval indexes over time are a secondary preference.',
 '结合提供上下文，推荐时序推荐或用户兴趣变化研究，兼顾与持续维护检索索引有关的工作。',
 '时序推荐或用户兴趣随时间变化', '与索引维护及上下文有关', '只研究静态推荐或只做增量索引，未覆盖时序推荐/兴趣变化', '无时序推荐或兴趣建模关联的时间序列预测'),
('Find work on maintaining retrieval indexes as new items arrive or adapting recommendations as interests change; use the supplied history to prioritize useful connections between these two problems.',
 '查找随新对象到来维护检索索引、或随兴趣变化调整推荐的研究，结合提供上下文优先建立两类问题的联系。',
 '明确覆盖增量检索索引或动态兴趣推荐至少一类', '连接两类问题并补充提供上下文', '只出现时间或在线字样，摘要未明确索引更新或兴趣变化', '纯静态检索/推荐且未涉及上述任一问题'),
('Find studies using knowledge distillation to reduce retrieval or ranking inference cost, with reported ranking-quality and resource-cost comparisons.',
 '查找用知识蒸馏降低检索或排序推理成本的研究，优先同时报告排序质量和资源成本对照。',
 '知识蒸馏用于检索或排序推理降本', '同时有排序质量与实际资源成本', '通用模型蒸馏或高效检索，但二者结合未明确', '与检索/排序无关的压缩，或只有训练加速'),
('Using the supplied history, recommend work on compact retrieval representations or efficient ranking. Prefer studies that report quality alongside inference latency or memory usage.',
 '结合提供上下文，推荐紧凑检索表示或高效排序研究，优先同时报告质量、推理延迟或内存。',
 '紧凑检索表示或高效排序', '质量与推理成本并报、上下文联系', '一般模型压缩或检索质量研究，效率目标不明确', '无检索/排序用途的模型压缩或仅优化训练时间'),
('Find retrieval or ranking studies that compare quality with inference latency or memory, then prioritize efficient-ranking connections to the supplied history.',
 '查找同时比较检索或排序质量与推理延迟或内存的论文，再结合提供上下文确定高效排序的阅读顺序。',
 '检索/排序研究包含质量与推理延迟或内存的对照', '实验资源条件清楚、与高效排序上下文有关', '涉及效率或质量但摘要未能确认二者联合比较', '仅训练速度或非检索/排序系统性能优化'),
]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():raise ValueError('Keep existing revision; create a new version instead')
    original=json.loads(SOURCE.read_text(encoding='utf-8'))
    assert len(original)==len(DRAFTS)==24
    OUT.mkdir(parents=True)
    rows=[]
    for source, draft in zip(original,DRAFTS,strict=True):
        en,zh,core,preferred,partial,unrelated=draft
        rows.append({'query_id':source['query_id'].replace('q20-','q25-'),'parent_query_id':source['query_id'],
            'intent':source['intent'],'topic_family':source['topic_family'],'topic_zh':source['topic_zh'],
            'request':en,'request_zh':zh,'required_focus_zh':core,'preferred_focus_zh':preferred,
            'reading_context':'none' if source['intent']=='topic' else 'same supplied five-paper context; not inferred personal intent',
            'source_profile_id':source['profile_id'],'at':source['at'],'inherited_split':source['split'],
            'grade_2_rule':'原摘要明确覆盖核心要求：'+core+'。次要偏好仅辅助理解，不单独改变等级。',
            'grade_1_rule':partial+'；说明哪些内容缺失或不明确。',
            'grade_0_rule':unrelated+'。只有明确不符合时判0；无法判断保持空白并说明。',
            'query_origin':'assistant_refined_draft','human_authored':False,'human_confirmed':False,
            'change_reason':'把原问题改为论文查找任务，明确核心与偏好，增加可供人使用的分级边界。',
            'candidate_pool_rebuild_required':True,'old_labels_reused':False})
    (OUT/'queries-v2-proposal.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (OUT/'human-review-blank.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['query_id','request','request_zh','query_origin','decision','reviewer_id','reviewed_at','note']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({**{k:r[k] for k in fields[:4]},**{k:'' for k in fields[4:]}} for r in rows)
    text=['# 24条论文查找需求：双语精修草稿','',
          '本文件由助手起草，等待真人确认。判据是拟定的标注规范，不是对任何论文的相关性判断。',
          '新ID对应原ID；核心要求决定相关性，次要偏好不能抵消主题不符。推荐/组合均使用任务提供的相同阅读上下文。',
          '判级顺序：明确满足完整核心=2；能确认部分相关但不满足完整核心=1；明确主题不符=0；无法可靠判断则留空并说明。下文“未说明”只在已确认部分相关时支持1，未知不自动计0或1。',
          '全部需求都需重新生成候选池。原24条、423个候选对及旧标注流程保留；新草稿不能直接替换旧工作表。',
          '确认表 human-review-blank.csv 的 decision 可填 approve/reject/clarify，并填真人别名、带时区时间及理由；当前全部空白。',
          '继承的 tuning/evaluation 仅维持主题分组，后段不是独立真实用户测试。','']
    for r in rows:
        text += [f"## {r['query_id']}｜{r['topic_zh']}｜{r['intent']}｜{r['inherited_split']}",'',
                 f"原需求：{r['parent_query_id']}",'',r['request_zh'],'',r['request'],'',
                 f"- 核心：{r['required_focus_zh']}",f"- 次要偏好：{r['preferred_focus_zh']}",
                 f"- 高度相关（2）：{r['grade_2_rule']}",f"- 部分相关（1）：{r['grade_1_rule']}",
                 f"- 不相关（0）：{r['grade_0_rule']}",'']
    (OUT/'需求精修_24条.md').write_text('\n'.join(text),encoding='utf-8')
    manifest={'origin':'assistant_refined_draft','source_sha256':sha(SOURCE),'queries':len(rows),
        'topic_families':len({r['topic_family'] for r in rows}),'intents':{i:sum(r['intent']==i for r in rows) for i in ['topic','recommend','mixed']},
        'human_confirmations_created':0,'human_labels_created':0,'candidate_pool_rebuild_required':True,
        'original_queries_and_pool_changed':False,'files':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'drafted','queries':len(rows),'human_confirmations':0,'path':str(OUT)},ensure_ascii=False))


if __name__=='__main__':main()
