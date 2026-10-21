"""Export CLIP's vision tower to ONNX so the app needs neither torch nor HF.

The app must not depend on torch (2.5 GB) to embed a thumbnail, and it must not
need the text tower at runtime: the scene words are a fixed vocabulary whose
vectors are precomputed once (see export_tags). So only the visual encoder ships.

    python evaluation/export_clip_onnx.py [--quantize]

Writes models/clip_vision.onnx and prints a parity check against torch: the ONNX
graph must reproduce the torch embedding, otherwise this is a different model
that merely shares a name.
"""
import os
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = r"E:\ai project\guopian"
VENDOR = os.path.join(ROOT, ".cache", "clipvendor", "CLIP-main")
WEIGHTS = os.path.join(ROOT, "models", "ViT-B-32.pt")
OUT = os.path.join(ROOT, "models", "clip_vision.onnx")
CAT = os.path.join(ROOT, "catalogs", "101MSDCF-61e11b7294")

sys.path.insert(0, VENDOR)
sys.path.insert(0, ROOT)

import clip  # noqa: E402
from guopian import config, imageio  # noqa: E402

N_PX = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def preprocess(im: Image.Image) -> np.ndarray:
    """CLIP's own transform, reimplemented without torchvision.

    Resize(shorter side = 224, bicubic) then CenterCrop(224) then Normalize.
    Matching it exactly matters: a different resize filter moves embeddings
    enough that thresholds tuned on one pipeline stop working on the other.
    """
    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    s = N_PX / min(w, h)
    im = im.resize((max(N_PX, int(round(w * s))), max(N_PX, int(round(h * s)))),
                   Image.Resampling.BICUBIC)
    w, h = im.size
    left, top = (w - N_PX) // 2, (h - N_PX) // 2
    im = im.crop((left, top, left + N_PX, top + N_PX))
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = (a - MEAN) / STD
    return a.transpose(2, 0, 1)


def main():
    quantize = "--quantize" in sys.argv
    model, _ = clip.load(WEIGHTS, device="cpu", jit=False)
    model.eval()
    visual = model.visual

    class Vision(torch.nn.Module):
        def __init__(self, v):
            super().__init__()
            self.v = v

        def forward(self, x):
            return self.v(x)

    net = Vision(visual).eval()
    dummy = torch.zeros(1, 3, N_PX, N_PX)
    t0 = time.time()
    with torch.no_grad():
        # dynamo=False keeps the TorchScript exporter: the new one wants
        # onnxscript installed, and this graph is plain enough not to need it.
        torch.onnx.export(
            net, dummy, OUT,
            input_names=["pixels"], output_names=["embedding"],
            dynamic_axes={"pixels": {0: "batch"}, "embedding": {0: "batch"}},
            opset_version=17, do_constant_folding=True, dynamo=False,
        )
    print("exported %s  %.0f MB  %.0fs" % (OUT, os.path.getsize(OUT) / 1e6, time.time() - t0))

    if quantize:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        q = OUT.replace(".onnx", ".int8.onnx")
        # MatMul only. Quantising the patch-embed Conv as well produced a graph
        # onnxruntime's CPU provider refuses to run ("Could not find an
        # implementation"), and the convolutional stem is a tiny share of the
        # weights anyway -- the Linear layers are the 89 MB.
        quantize_dynamic(OUT, q, weight_type=QuantType.QInt8,
                         op_types_to_quantize=["MatMul"])
        print("quantised -> %s  %.0f MB" % (q, os.path.getsize(q) / 1e6))

    # ---- parity: same input, torch vs onnxruntime ----
    import onnxruntime as ort
    hit = sorted(os.listdir(os.path.join(CAT, "thumbs")))[:3]
    tc = imageio.ThumbCache(CAT)
    samples = []
    for b in hit:
        d = os.path.join(CAT, "thumbs", b)
        for f in sorted(os.listdir(d))[:2]:
            samples.append(os.path.join(d, f))
    samples = samples[:4]
    arr = np.stack([preprocess(Image.open(p)) for p in samples]).astype(np.float32)

    sess = ort.InferenceSession(OUT, providers=["CPUExecutionProvider"])
    t0 = time.time()
    got = sess.run(None, {"pixels": arr})[0]
    dt = time.time() - t0
    print("onnx: %d images in %.3fs (%.0f ms each)" % (len(samples), dt, dt * 1000 / len(samples)))

    with torch.no_grad():
        ref = net(torch.from_numpy(arr)).numpy()

    def unit(v):
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    cos = (unit(got) * unit(ref)).sum(axis=1)
    print("parity cosine vs torch: %s" % np.round(cos, 5))
    print("max abs diff: %.5f" % float(np.abs(got - ref).max()))

    if quantize:
        q = OUT.replace(".onnx", ".int8.onnx")
        sq = ort.InferenceSession(q, providers=["CPUExecutionProvider"])
        gq = sq.run(None, {"pixels": arr})[0]
        cosq = (unit(gq) * unit(ref)).sum(axis=1)
        dq = 1.0 - cosq
        print("quantised parity: cosine %s  min %.5f" % (np.round(cosq, 5), cosq.min()))
        # what the app actually uses: ranking. compare rankings on these images
        print("quantised size %.0f MB" % (os.path.getsize(q) / 1e6))


if __name__ == "__main__":
    main()
