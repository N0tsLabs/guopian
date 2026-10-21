研究：本地 CLIP 能不能用来分组、搜场景、判表情

不是接进产品的代码，是为了回答三个问题而做的测量，留在仓库里当证据：
换算法之前先量一遍，比换完再说“应该更准”可靠。

结论（都在这台机器、这个 1428 张的库上实测）：

1. 相似分组 —— 有用，而且正好解决“一张有人、一张没人”那对。
   余弦：真近似重复 0.98，同一场景不同瞬间 0.90-0.95，
   争议那对（双人合影 vs 空景）只有 0.58，真·空景重拍 0.992。
   用“完全连接 + 余弦阈值 0.85 + 15 秒窗口 + 每组最多 12 张”重做：
   371 组、93% 的照片进组、最大组 12 张（现在是单链聚合，最大组 128 张）。
   速度：CPU 上 28 ms/张，1428 张 110 秒。

2. 语义搜索 —— 可用。
   78 个中英双语标签（scene_tags.py），中文词经别名表映射到英文提示词，
   实测「湖」10/10 是湖、「人像」10/10 是人、「雪山」10/10 是雪景；
   docs/img/_clip_湖泊.png 等是这个脚本 `sheet` 子命令生成的对照图。
   检索运行时根本不需要文本编码器：标签向量一次算好存下来，
   每张照片只需一个 512 维向量（float16 存是 1 KB/张）。

3. 表情 —— CLIP 不行，别在它身上花钱。
   整图：与 blendshape 的 Spearman 相关全在 ±0.25 以内，
   “闭眼”提示词的 Top12 里没有一张是闭着眼的（_expr_blink.png，
   它匹配的是墨镜和抬手）。
   换成人脸裁切：只有“笑”这一项起来了（ρ=0.33），
   闭眼 −0.12（方向都反了）、张嘴/眯眼/尴尬 ≈0。
   原因很直白：CLIP 是 224px 的整图语义模型，学的是“这张图讲什么”，
   不是“脸部肌肉怎么动”。表情该用 MediaPipe 已经给出的 52 个 blendshape。

跑法（需要 models/ViT-B-32.pt，不在仓库里）：

    python evaluation/clip_index.py build          # 标签 + 全部照片向量
    python evaluation/clip_index.py sim            # 分组阈值评估
    python evaluation/clip_group_eval.py           # 完全连接 + 分组大小
    python evaluation/clip_index.py sheet 湖 人像   # 生成检索对照图
    python evaluation/clip_expression_eval.py      # 整图表情
    python evaluation/clip_face_eval.py            # 人脸裁切表情

依赖说明：HF 在这台机器上连不通（huggingface.co / cdn-lfs 超时），
权重是从 OpenAI 的 CDN（openaipublic.azureedge.net）下的；
onnxruntime 也没装成，所以现在走的是已经装好的 torch。
真要发版应该导出成 ONNX 只留视觉编码器（量化后约 88 MB），运行时不需要 torch。
