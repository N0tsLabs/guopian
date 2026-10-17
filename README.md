<div align="center">

# 过片 Guopian

**一张一张看照片，说「要」或者「不要」。**

一次旅行拍了几千张，大部分是同一场景的连拍 ——<br>
过片把照片一张张推到你面前，按 <kbd>→</kbd> 留下、按 <kbd>←</kbd> 不要，<br>
最后一次性归档到三个文件夹。

<sub>Windows · macOS · Linux · 全部在本机运行 · 不上传 · 不联网</sub>

</div>

## 它解决什么

翻开一个几千张的文件夹，你不知道从哪看起。一张张双击、判断、重命名、移动，
几百张之后就不想干了。

过片把这件事变成**一个动作**：照片推到你面前，你只回答留不留。

- **不用一张张打开。** 一张接一张，没有文件管理器。
- **会告诉你哪里有问题。** 过曝、失焦、白平衡偏了、闭眼、视线没看镜头、
  同一场景里哪张最好 —— 逐条列出，不是给个分数。
- **不动你的文件。** 筛选全程只写数据库；归档是最后单独一步，先给你看清单，
  确认了才移动，移动完还能撤回。
- **结果能带走。** 归档后是三个普通文件夹，资源管理器能看，Lightroom 也能导入。

## 它检查什么

| 类别 | 例子 |
| --- | --- |
| 曝光 | 高光溢出、暗部死黑、画面发灰 |
| 清晰度 | 失焦、噪点、分辨率偏低 |
| 色彩 | 白平衡偏蓝 / 偏黄 |
| 人脸 | 闭眼、视线没看镜头、表情、头部偏转 |
| 连拍 | 相似分组、组内排名、几乎完全相同 |

每一项都标出**具体是哪张脸、什么程度**，不是一个笼统的分数。

## 下载

从 [Releases](../../releases) 下载对应系统的压缩包，解压，双击运行，不需要安装。

> 目前还没有发布预编译包，请按下面的「从源码运行」。

## 怎么用

1. 打开文件夹 —— 整个目录会被读进来，子文件夹也算
2. 一张张过：

| 按键 | 作用 |
| --- | --- |
| <kbd>→</kbd> / <kbd>K</kbd> | 要 |
| <kbd>←</kbd> / <kbd>J</kbd> | 不要（只是标记，不删文件） |
| <kbd>空格</kbd> | 精选 —— 要，而且是这批里最好的 |
| <kbd>↑</kbd> <kbd>↓</kbd> | 只是翻看，不改状态 |
| <kbd>⌫</kbd> | 撤销上一步 |
| <kbd>I</kbd> | 显示人脸框 |

3. 点**应用决策** —— 先看清单，确认后照片分进三个文件夹：`过` / `不过` / `精选`。
   **没审过的留在原地。**

按键可以按住预览、松手才生效；拖动卡片也能做决定。完整键位在应用里按 <kbd>?</kbd>。

第一次打开项目会有一个简短的引导，用演示画面走一遍流程，不碰你自己的照片。

## 你的照片是安全的

- 筛选过程**不写任何文件**，决定只存在数据库里
- 归档要**二次确认**，并且可以整批撤回
- 可以「只读方式打开」，那样连归档按钮都是灰的
- 全程离线，不联网、不上传、不收集任何东西

## 从源码运行

需要 Python 3.10+。

```bash
git clone https://github.com/N0tsLabs/guopian.git
cd guopian
python -m venv .venv
```

```bat
:: Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

```bash
# macOS / Linux
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

第一次打开项目时会自动下载人脸模型（约 3.6 MB）。也可以手动下载：

```bash
python scripts/fetch_models.py
```

### 自己打包

```bash
python scripts/build.py
```

产物在 `release/`。

## 技术栈

Python + Flask 起一个本地服务，前端是十一个浏览器原生 ES module —— **零依赖、无构建步骤**，
改一行 CSS 刷新就生效。图像分析用 OpenCV + MediaPipe，全部在本机跑。

为什么这么选、踩过哪些坑，写在 [docs/design.md](docs/design.md)。

## 许可证

[MIT](LICENSE)

## 第三方

- [MediaPipe](https://github.com/google/ai-edge-mediapipe) — 人脸检测（Apache-2.0）
- [Flask](https://flask.palletsprojects.com/) — 本地服务（BSD-3）
- [Pillow](https://python-pillow.org/) · [OpenCV](https://opencv.org/) · [NumPy](https://numpy.org/)
