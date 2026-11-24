# Papertrail Studio v33

Preact 11.1.0 (MIT)、HTM 3.1.1 (Apache-2.0)直接复用v32的核验文件，许可全文保留在dist/vendor。

Anime.js 4.5.0，Copyright (c) 2025 Julian Garnier，MIT。直接复用官方提交`01b81be1df6843ccfe0a71c0699a746bf740dd77`发布的`dist/bundles/anime.esm.min.js`，完整MIT许可在`dist/vendor/ANIME_LICENSE.md`，Git blob与SHA256在`reports/stage33/vendor-source.json`。使用其animate/stagger/createScope执行页面入场与SVG图层过渡；Scope.revert负责组件清理、原生mediaQueries处理系统减少动态偏好。未重写动画引擎，不安装共享包。

设计参考：MotionSites的整页/应用构图栏目、React Bits的主视觉和可组合图形意识、Uiverse的独立按钮状态、Aceternity的非等重网格和图形卡片、Anime.js的编排。官方网页及GitHub许可重新读取；外网交互预览超时，图片检索仅作为静态设计参考，未冒称实时视觉/动态验证。未复制这些站点的组件、图片、品牌、付费素材或模板；React Bits当前许可为MIT附Commons Clause，本轮不分发其组件。

论文轨道、主题小图形、品牌标记由本项目以SVG绘制，是装饰示意，未使用算法结果构造关系图，不代表论文相似度、引用网络或检索关系。搜索API直接复用封存v30，仅替换静态挂载。
