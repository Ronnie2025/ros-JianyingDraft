# 输入清单 v1

Agent 将用户已经确定的文字说明或表格转为此 JSON。仅执行明确映射与算术；必需信息缺失时集中报告。已有成片只能用于参考，不能据此推断源素材、切点或分层。

## 根对象

`schema_version: 1`、`name`、`canvas: {width,height,fps}`、`assets`、`tracks` 必填。可选根字段 `subtitle_sync` 为布尔值，默认 true，对应字幕面板样式联动开关。画幅由宽高确定，fps 为 24/25/30/50/60 整数。轨道按数组从底到顶排列，类型为 video/audio/text/subtitle；所有轨道名称、所有片段 ID、所有素材 ID 各自唯一。

所有时间字段以秒表示，保留至微秒，禁止时间码字符串与毫秒混入。非整帧时间只报告提示，保留原微秒值，不主动吸附。跨轨重叠与空隙保留；同一轨道重叠暂不支持，需上游明确不同图层，转换器不会自行重排。

素材字段：`id,path,kind` 必填，`sha256` 可选。kind=video/audio/image。path 可为绝对路径或相对输入 JSON 所在目录的路径。首次探测记录完整文件指纹。后续输入带指纹可检测同名替换。`--path-map` 接受 `{旧绝对路径: 新绝对路径}`；重定位必需原 sha256，转换器校验相同文件后才替换。原素材不复制，稳定保存在外部位置；generated media 同样由上游提供明确文件。

## 视频、音频和图片片段

- 视频/音频必填 `id,asset,source_in,source_out,target_start,speed,volume`。入点包含、出点不包含。目标持续时长=(出点−入点)/speed。volume 为线性增益，0=静音，1=原音量；视频本身无声也要明确填写0。同期声用视频自己的原声；独立旁白使用音轨，原视频音量由输入明确指定。
- 图片必填 `id,asset,target_start,duration`；放在 video 轨道。图片无音频与源时间字段。
- `change_pitch` 可选，默认 false，对应恒速变速保持音调；`fade_in,fade_out` 是明确指定的音频淡入淡出秒数，缺省无淡入淡出。
- `transform` 可选，缺省表示保持原生中性变换：`alpha=1,rotation=0,scale_x=1,scale_y=1,transform_x=0,transform_y=0,flip_horizontal=false,flip_vertical=false`。位置单位是半画布宽/高，旋转为角度。未指定不补背景、不裁主体。原生适配与参考渲染有差异时报告。
- `crop: [left,top,right,bottom]` 是相对原素材0..1的矩形裁切；省略表示无裁切，使用完整源文件。不支持音轨crop或transform。

## 原生文字与字幕联动

`type: "subtitle"` 轨道用于已明确的对白/口播字幕，生成剪映原生字幕材料及同批 `group_id`，启用字幕面板的统一样式修改。每条字幕仍可单独改字。同一轨道默认为一个批次；可用轨道字段 `subtitle_group` 指定非空批次名，让多条字幕轨道共享同一个批次。不同批次的实际联动范围依目标版本核验，勿承诺所有版本均按分组隔离。

`type: "text"` 保持原有普通文字行为，适用于标题、章节和独立标注，不参与字幕样式联动。旧清单不会按轨道名字自动转换；已确认属于字幕的旧轨道可将 type 从 text 改成 subtitle。两类轨道中的文字、时间和样式输入格式相同。

根字段 `subtitle_sync: false` 关闭字幕样式联动，保留原生字幕身份。联动不会在构建时统一或覆盖输入中不同的样式；它控制后续剪映内的编辑行为。

字幕样式联动与时间轴轨道联动分开：`clip_id` 继续仅指定源时间映射，不表示永久绑定。主轨移动时剪映可能依轨道联动开关自动带动覆盖区间的上层内容；本次只验证移动，不能据此承诺删除、分割、裁边或变速时自动重算全部字幕。


必填 `id,text,time_basis,start,end,font,style,transform`。`font="system"` 表示用户选择剪映系统字体；其他值为锁定上游 `FontType` 枚举名。实际字体仍需应用内检查。style 必填 size（剪映库原生单位）、color（RGB三元组0..1）、align（0左1中2右）。可选字段见下方示例；缺省属性遵循上游无修饰文本，不自动添加描边、自动换行或动画。

time_basis=timeline 使用成片秒数；time_basis=source 必须同时指定 `clip_id`，将该源素材时间按所引用片段的切点与速度映射到成片。必须落在该片段源范围内；跨切点或重复使用原素材时，需上游明确片段归属和拆分结果。转换器不会裁掉字幕或改写断句。

可选 `border: {width,color,alpha}` 表达原生描边；width 0..100，alpha缺省1。上游描边单位转换及字体显示需剪映内验证。图片里的文字不会变成原生文本。

## 最小完整示例

```json
{
  "schema_version": 1,
  "name": "明确方案转草稿",
  "canvas": {"width": 1280, "height": 720, "fps": 30},
  "assets": [{"id": "source", "path": "source.mp4", "kind": "video"}],
  "tracks": [
    {"name": "原视频", "type": "video", "segments": [
      {"id": "clip-a", "asset": "source", "source_in": 2, "source_out": 8, "target_start": 0, "speed": 1, "volume": 1}
    ]},
    {"name": "字幕", "type": "subtitle", "segments": [
      {"id": "text-a", "text": "已经确认的原文", "time_basis": "source", "clip_id": "clip-a", "start": 3, "end": 5,
       "font": "system", "style": {"size": 8, "color": [1,1,1], "align": 1, "bold": false, "auto_wrapping": false},
       "transform": {"transform_y": -0.8}, "border": {"width": 20, "color": [0,0,0]}}
    ]}
  ]
}
```

## 能力边界与输出

首版支持原生矩形裁切、位置/缩放/旋转/透明度、恒速、指定音量和淡入淡出、原生文字与描边、上游预制图像/视频。转场、关键帧、原生蒙版/模糊、效果库调用、曲线变速及未列出的字段会阻塞；即使上游存在相关API，也不表示本机该效果已验证。禁止静默丢弃字段或将必需效果降级。用上游已经提供的透明视频呈现复杂效果时，只能编辑其整体片段。

`check PLAN [--path-map MAP]` 只检查输入/媒体；不宣称草稿构建成功。`build PLAN --output DIR` 输出draft/、conversion-plan.json、dependencies.json、segment-map.json、generated-files.json和validation.json；输出目录已存在则拒绝。失败保留输入或规范化信息及阻塞原因。

`verify DIR` 核对生成文件指纹、当前源文件身份、素材引用、字幕和时间范围；不代表应用验收。`install DIR [--draft-root ROOT]` 在国内剪映关闭时安装独立新草稿并备份根索引。默认本机用户Movies下的剪映草稿目录；安装记录单独保存。已有名称生成后缀版本；不覆盖旧工程。应用保存后不会把旧明文JSON当作最新数据重新安装。
