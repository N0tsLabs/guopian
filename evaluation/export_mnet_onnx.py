"""把 MobileNetV3-Small 的特征头导出成 ONNX（只留 576 维向量，不要分类头）。

产物 3.7 MB，运行时不需要 torch —— 这台机器上的 torch 装在用户目录里，
不可能塞进发布包。

    python evaluation/export_mnet_onnx.py

需要 torch + torchvision（只在导出时用）。导出后核对：
输出形状 (N, 576)、与 torch 的余弦 >= 0.9999。
"""
import os
import sys

import numpy as np
import torch

ROOT = r"E:\ai project\guopian"
OUT = os.path.join(ROOT, "models", "photo_embed.onnx")
os.environ.setdefault("TORCH_HOME", os.path.join(ROOT, ".cache", "torch"))


def main():
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

    w = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    m = mobilenet_v3_small(weights=w).eval()
    # features -> avgpool -> flatten = 576 维。扔掉最后的 classifier，
    # 那 1000 个输出是"这是不是金毛"，我们要的是"这张图长什么样"。
    feat = torch.nn.Sequential(m.features, m.avgpool, torch.nn.Flatten()).eval()

    x = torch.randn(4, 3, 224, 224)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    torch.onnx.export(
        feat, x, OUT,
        input_names=["input"], output_names=["feat"],
        opset_version=17, dynamo=False,
        dynamic_axes={"input": {0: "n"}, "feat": {0: "n"}},
    )
    print("导出: %s  %.2f MB" % (OUT, os.path.getsize(OUT) / 1e6))

    import onnxruntime as ort

    s = ort.InferenceSession(OUT, providers=["CPUExecutionProvider"])
    with torch.no_grad():
        yt = feat(x).numpy()
    yo = s.run(None, {"input": x.numpy()})[0]
    cos = float((yt[0] / np.linalg.norm(yt[0])) @ (yo[0] / np.linalg.norm(yo[0])))
    print("形状 %s | 与 torch 最大差 %.6f | 余弦 %.5f"
          % (yo.shape, float(np.abs(yt - yo).max()), cos))
    if cos < 0.9999:
        sys.exit("导出的图和 torch 不一致，别用")


if __name__ == "__main__":
    main()
