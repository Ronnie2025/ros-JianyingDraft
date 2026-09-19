# ros-JianyingDraft

将**已经明确的剪辑方案与源素材**转换为剪映可继续编辑的独立草稿。

保留指定的素材、切点、轨道、字幕、声音关系与受支持参数。适合把文字剪辑说明、表格或结构化时间线交给 Agent 后，转换成剪映工程。

## 安装与调用

```bash
npx -y skills add Ronnie2025/ros-JianyingDraft -g --all
```

安装后在支持 Skill 的 Agent 中调用：

```text
$ros-JianyingDraft
请将下面已经确定的剪辑方案和素材转换为剪映草稿，保留切点、字幕与音画关系。
```

Skill 名称保留 `ros-JianyingDraft` 的大小写；不同宿主的菜单显示及安装目录可能采用规范化形式，请以安装输出为准。

首次运行由 Agent 执行 Skill 内的 `scripts/setup_runtime.sh` 配置独立环境。需要 Python 3.10+、Git，以及提供 `ffprobe` 的 FFmpeg。安装依赖时需要联网；转换使用本地文件，不上传素材。

## 工作范围

- 按既定清单生成完整时间线，保留空隙与跨轨重叠。
- 默认引用完整源文件，保留原素材范围内的拖边余量。
- 支持原生字幕样式联动：修改同批一条字幕的字号时，其余字幕同步；普通标题保持独立。可在剪映内关闭联动。
- 支持原生文字、矩形裁切、位置、缩放、旋转、透明度、恒速、指定音量和音频淡入淡出。
- 接收上游已经提供的图片或预制动效视频；这些媒体的内部元素保持合成状态。
- 每次新建独立草稿，保留已有工程。素材仍依赖原位置，移动后可通过明确路径映射和文件校验重新定位。
- 信息不足或必需效果无法转换时报告缺项，不自行补做剪辑决定。

本 Skill 不承担转写、挑选镜头、节奏优化、叙事重排、字幕改写、素材生成、效果创作、人工工程合并或默认成片导出。只有最终 MP4 时，无法恢复缺失的原始分层数据。

原生蒙版、模糊、转场、关键帧、曲线变速和未列入输入格式的效果，首版暂不支持。

## 字幕联动

口播和对白字幕使用 `type: "subtitle"` 轨道，标题或独立标注使用 `type: "text"`。默认启用字幕面板中的“文本、排列、气泡、花字应用到全部字幕”；可通过根字段 `subtitle_sync: false` 关闭。构建时保留各条输入样式，后续在剪映中修改才触发联动。

每条字幕轨道默认对应一个批次，可用 `subtitle_group` 明确跨轨共享批次。已有清单的 `text` 保持旧行为；需要联动的字幕轨道应显式改为 `subtitle`。

剪映 11.5.0 已实测：同批字幕字号同步、普通标题不受影响、关闭联动后可单独修改、保存重开保留状态。不同批次之间的 UI 隔离范围尚未完整验证。

字幕样式联动与时间轴轨道联动是两项功能。视频移动跟随取决于剪映的轨道联动开关；转换清单的 `clip_id` 用于初始时间换算，不承诺剪切、删除或变速后自动重算字幕。

## 输入与命令

见 [输入格式与完整示例](skills/ros-JianyingDraft/references/input-format.md)。时间字段以秒表示；字幕必须说明使用源素材时间或成片时间。

在 Skill 所在目录使用独立环境的 Python：

```bash
python scripts/converter.py check plan.json
python scripts/converter.py build plan.json --output output/new-draft
python scripts/converter.py verify output/new-draft
python scripts/converter.py install output/new-draft
```

输出草稿、转换清单、依赖清单及验证报告。安装需要目标剪映已退出，并备份原草稿列表。同名工程采用新版本名称。

## 兼容与验证范围

- 当前安装适配面向 **macOS 国内剪映**，通过 `com.lemon.lvpro` 识别；不代替 CapCut 或 Windows 适配。
- 11.4.2 环境已验证外链重新关联、原生字幕修改、源视频前后拖边，以及保存关闭后重开保留修改。
- 自动回归与独立竖屏样本的结构检查通过。图片、裁切、描边和淡入淡出完成结构检查；未覆盖全部组合的应用内表现。
- 未执行成片导出和逐段试听；音频在应用内核对至指定音量参数。
- Mac 首次访问外链素材可能显示无访问权限，需要在剪映的“链接媒体”窗口选择准确原文件，保存重开后核对素材库、预览与时间线。

更多细节见 [Mac 兼容说明](skills/ros-JianyingDraft/references/mac-compatibility.md)和[验收方法](skills/ros-JianyingDraft/references/regression-cases.md)。生成成功与应用实际验证分别记录，软件更新后需重新核验。

## 来源与致谢

草稿生成能力基于 GuanYixuan / Gary Guan 的 **[pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)**。感谢上游作者与贡献者提供的工作。本项目固定使用提交 [`c331806`](https://github.com/GuanYixuan/pyJianYingDraft/tree/c3318066d964744e2bfc66f75c71745fe8cea52a)，Mac 安装与转换范围由本项目单独验证。

原生字幕分组及编辑态字段参考 [aoguai/pyJianYingDraft](https://github.com/aoguai/pyJianYingDraft/tree/4a7730c9a14e91aa497e723c85b5c433a62a163c) 的公开实现，感谢作者对字幕统一编辑的补充。

Mac 草稿适配参考了 **[video-shotcraft 的公开适配实现](https://github.com/Vincentwei1021/video-shotcraft/blob/main/jianying-export/mac_draft.py)**，感谢其作者提供参考。

**特别感谢栋哥的 Skill Maker Skill**，为本项目的 Skill 制作与验证提供帮助。此处仅作致谢，本仓库未收录该 Skill 的内容。

本项目采用 [Apache License 2.0](LICENSE)，第三方来源见 [NOTICE](NOTICE)。
