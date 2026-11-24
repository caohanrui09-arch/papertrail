# 阅读改进版 v34

直接复用已封存v33的全部Preact 11.1.0、HTM 3.1.1及Anime.js 4.5.0文件和完整许可，vendor文件逐字节核验。Anime.js固定提交、Git blob与MIT许可见reports/stage33/vendor-source.json；本轮不下载、安装、修改第三方组件或共享包。

沿用原v33图形与页面风格；工作台不增加入场动画。连续阅读为项目接口适配：Preact钩子维护当前候选位置与组件引用，浏览器原生scrollTo只移动对应面板，focus({preventScroll:true})定位当前标题；保留原AbortController/序号控制和原摘要核验API。不重写滚动或动画引擎。

明确小改动，按项目AGENTS.md例外无需重新进行大型GitHub方案选型。复用阶段33来源核验，并读取W3C对比度说明与MDN原生滚动文档，记录于阶段34报告。采样对比度检查不等同全站无障碍认证。
