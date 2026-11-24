# 视觉参考拆解与修正方向

用户澄清：背景和界面框架以黑白灰为主，插画、图形、数据和关键交互允许有其他颜色形成对比。前轮把所有图形一并转换为灰度，范围过宽。本次只调研和整理方向，尚未再次修改运行页面。

## 官网参考

- MotionSites：https://motionsites.ai/motionsite 。原对话只提供名称，存在同名站；本次以该站公开的整页设计与动效说明为参考，未访问付费模板。
- React Bits：https://reactbits.dev/components/tilted-card 、https://reactbits.dev/animations/animated-content 、https://reactbits.dev/llms.txt 。说明了指针倾斜、分层阴影、内容入场及各组件依赖差异。
- Uiverse：https://uiverse.io/ 。按钮、加载与悬停组件，支持 HTML/CSS、Tailwind 等代码形式。
- Anime.js：https://animejs.com/ 。Timeline、stagger、SVG 描线/路径和滚动触发能力。
- Aceternity UI：https://ui.aceternity.com/components/bento-grid 、https://ui.aceternity.com/components/3d-card-effect 。大小网格组合与 CSS perspective 分层卡片。

本次证据是官网公开文档与组件说明，未进行逐站浏览器动效实测，未下载付费内容或复制组件源码，不据此声称真实用户转化率提升。

## 对当前截图的判断与建议

以下属于本项目的设计判断，非上述网站统一规范。

1. 保留左大右小的专题布局及黑白灰底色。大图形、标题、说明、按钮形成清楚层次；次要标签与网格保持安静。
2. 生成式检索图形以蓝色标出文档到 ID 的路径与关键标记，纸张和深色卡片仍中性；推荐图形以琥珀色突出兴趣连接；评价图形以蓝/紫区分确有含义的系列。相同算法跨图始终使用同一颜色，附文字与图例。
3. 每张卡片有明确的图形焦点。图形色用于表达结构，避免给卡片背景整体上色。正文对比度独立保证。
4. 只在首页/专题插画安排轻量分层悬停或一次性入场；搜索列表与阅读区保持稳定。按钮状态和工具轨迹变化依托真实状态，不以装饰动画模拟模型进度。
5. 现有站使用 Preact，优先复用现有组件、CSS Grid 和 SVG。微交互用 transform/opacity；复杂编排确有需要时才引入动画依赖，并支持减少动态效果。React 组件不能视为可无成本直接替换。

后续最小实施范围应先为截图中的三张专题卡恢复有选择的彩色插画，保留中性背景；验收静止画面、悬停、键盘焦点与减少动态效果模式，再扩展到其他页面。尚未执行该修改。
