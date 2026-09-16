# Twick 编辑与渲染架构

## 数据所有权

OurVideoCreator 继续拥有 Project、Asset、AI 工作流和任务队列。Twick 只提供浏览器编辑内核与实时播放器。媒体索引存在 PostgreSQL `assets` 表，私有文件存在 `data/assets`，编辑元素通过 `metadata.assetId` 与 `props.srcAssetId` 引用它。

```text
AI 分镜 / 项目素材
        ↓
MyVideoAsset → Twick Element adapter
        ↓
Project.document.editor.timeline
        ↓
EditorRenderCompiler
        ↓
持久化 export job → native FFmpeg → 新视频 Asset
```

## 项目结构

```json
{
  "editor": {
    "version": 1,
    "timeline": {
      "version": 2,
      "tracks": [],
      "assets": {}
    }
  }
}
```

`timeline.assets` 是轻量清单，服务于恢复和可移植性；它不是第二套素材库。后端渲染不信任浏览器提交的 URL，只用 `assetId` 在当前项目中解析服务器文件。

## 编辑领域 API

`src/editor/editorActions.ts` 是 UI 与后续 Agent 的共同入口，覆盖轨道、片段移动与裁剪、切分、素材入点、速度、替换、transform、滤镜、标题、字幕、转场、音量及自动化。React 组件只负责收集用户输入和显示错误。

## 渲染编译器

`backend/editor_renderer.py` 对工程执行结构、时间范围、元素 ID、素材归属、素材类型和媒体长度校验，然后生成单次 FFmpeg filter graph：

- 画面轨按轨道与 z-index 叠加；视频/图片执行 trim、scale/object-fit、rotate、opacity、fade 和滤镜。
- 相邻转场为下一画面建立预卷并对两路 alpha 做交叉淡化，保持工程总时长。
- 标题和字幕编译为项目私有 ASS 文件后烧录。
- 视频原声与音频轨按时间延迟后混音；支持 trim、速度、静态音量、关键帧线性插值和淡入淡出。
- 最终固定输出 24fps H.264/AAC MP4，并由原 worker 登记回项目素材库。

编译器只接受它能够兑现的元素、转场、动画和滤镜；第三方工程中的未知效果会明确报错，不会静默丢失。Twick 0.15.31 的 transition metadata 与音量自动化目前不进入其浏览器实时播放器，对应控件已标注“以导出成片为准”，FFmpeg 输出仍完整实现。

legacy `document.timeline: Clip[]` 和原导出器继续存在。只有工程包含 `editor_timeline` 时才走新编译器，因此旧项目与原 AI 生成链路不需要迁移即可继续工作。
