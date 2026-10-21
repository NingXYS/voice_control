# 背部穴位图素材说明

- 制作日期：2026-10-21。
- 底图：内置 image_gen 工具原创生成的教学模型背部插画，透明 PNG；没有使用网站图片或复制书籍插图。
- 文件：`VoiceUi/assets/back-torso-sage.png`，1024 × 1536 RGBA。
- 中文名称、编号、引线和穴位点：`voice_ui/index.html` 内联 SVG，样式为 `VoiceUi/back-atlas.css`，独立于生成底图。
- 此图只作常见穴位位置示意，既不提供个体精确定位，也不连接机器人坐标或下发运动指令。

## 标注核对

名称和相对纵向层次依据 WHO《Standard Acupuncture Point Locations in the Western Pacific Region》（2008，2009 重印）。正文页码如下；没有将示意图像素当作取穴尺度。

| 名称 | 编号 | 相对层次 | 分布 | 正文页 |
| --- | --- | --- | --- | --- |
| 大椎 | GV14 | C7 下 | 正中 | 210 |
| 肺俞 | BL13 | T3 下缘水平 | 双侧 | 106 |
| 心俞 | BL15 | T5 下缘水平 | 双侧 | 107 |
| 膈俞 | BL17 | T7 下缘水平 | 双侧 | 108 |
| 肝俞 | BL18 | T9 下缘水平 | 双侧 | 108 |
| 脾俞 | BL20 | T11 下缘水平 | 双侧 | 109 |
| 肾俞 | BL23 | L2 下缘水平 | 双侧 | 111 |
| 腰阳关 | GV3 | L4 下 | 正中 | 205 |

标准原文：[WHO 标准（MEDBOX 镜像）](https://www.medbox.org/index.php/dl/627a4de115110145a1723f64)。仅核对名称与标准位置描述，未复制原插图；图中排布为界面示意。

## 最终生成提示词

使用内置 image_gen；未使用 CLI 或外部付费 API。

```text
Use case: scientific-educational. Create a clinical educational illustration of the POSTERIOR SURFACE OF A MEDICAL ANATOMICAL MANNEQUIN, a non-living plastic anatomy teaching model of neck, shoulder blades, thoracic back and lumbar back only. Show one straight-on symmetrical posterior torso model, shoulders relaxed, no head/face, no front, no lower body. Crop at the upper pelvic rim. It is a simplified teaching diagram with subtle anatomical contours, with no exposed muscles or internal anatomy. Narrow vertical spine groove down the exact center, believable scapular outlines, realistic upper back to waist proportions. Render as elegant muted sage-green contour drawing and very light warm sand shading on ivory-colored plastic, soft hand-drawn clinical editorial style. Intended as a quiet small illustration in an ivory and sage dashboard. Portrait composition 2:3, the model fills the canvas height with small margins, shoulders extend nearly to the sides, everything symmetrical. Transparent background. No text, no labels, no markers, no diagrams overlaid, no acupoints, no needles, no logos, no frame, no watermark.
```
