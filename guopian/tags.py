"""场景词表：把中文搜索词映射成 CLIP 认识的英文提示词。

为什么要一张固定的词表，而不是让用户直接打字：

CLIP 的文本塔只在英文上训练过。"海边"两个字喂进去是噪声，出来的向量和
"沙滩照片"没有关系。而机器翻译会引入它自己的错误，还得多一个依赖。

所以词表放在这里，中文词 -> 英文提示词由人写好。向量是一次性算好的
（guopian/data/tag_vecs.npy，78 x 512，float16，80 KB），运行时不带文本塔。
代价是搜索范围受词表限制；好处是结果可控、快、没有翻译层。

加一个新词的成本 = 写一行 + 跑一次 evaluation/export_tags.py。
不需要重新分析任何照片 —— 照片向量和词向量在同一个空间里。
"""

from __future__ import annotations

import json
import os

import numpy as np

# zh, en(提示词), group, aliases
TAGS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # ---- 场景 scene -------------------------------------------------------
    ("海边", "a photo of a beach and the sea", "scene", ("沙滩", "大海", "海滩", "海岸")),
    ("湖泊", "a photo of a calm lake surrounded by mountains", "scene", ("湖", "湖水", "湖面")),
    ("雪山", "a photo of snow covered mountains", "scene", ("雪峰", "冰川")),
    ("山峰", "a photo of rocky mountain peaks", "scene", ("山", "山脉", "高山")),
    ("云海", "a photo of a sea of clouds below mountain peaks", "scene", ("云雾", "云")),
    ("森林", "a photo of a dense green forest", "scene", ("树林", "林子", "松林")),
    ("草地", "a photo of a green grass meadow", "scene", ("草原", "草坪", "草甸")),
    ("花田", "a photo of a field full of flowers", "scene", ("花海", "花丛", "野花")),
    ("溪流", "a photo of a stream flowing over rocks", "scene", ("小河", "溪水")),
    ("瀑布", "a photo of a waterfall", "scene", ()),
    ("沙漠", "a photo of sand dunes in a desert", "scene", ("沙丘", "戈壁")),
    ("峡谷", "a photo of a deep canyon", "scene", ("山谷",)),
    ("城市街道", "a photo of a city street with buildings", "scene", ("街道", "马路", "街", "城区")),
    ("古镇", "a photo of an old chinese town with traditional houses", "scene", ("老街", "老房子")),
    ("寺庙", "a photo of a chinese temple", "scene", ("佛寺", "寺院", "庙")),
    ("教堂", "a photo of a church", "scene", ()),
    ("建筑", "a photo of a modern building", "scene", ("楼房", "高楼", "大厦")),
    ("室内", "a photo taken indoors in a room", "scene", ("房间", "屋里")),
    ("咖啡馆", "a photo inside a cafe", "scene", ("咖啡店", "咖啡厅")),
    ("餐厅", "a photo inside a restaurant", "scene", ("饭店", "餐馆")),
    ("公路", "a photo of an empty road", "scene", ("路上", "车道", "盘山路")),
    ("桥", "a photo of a bridge", "scene", ("桥面", "吊桥")),
    ("公园", "a photo taken in a park", "scene", ("园林",)),
    ("停车场", "a photo of a parking lot", "scene", ()),
    ("机场", "a photo inside an airport", "scene", ()),
    ("火车站", "a photo of a train station", "scene", ("车站", "月台")),
    ("地铁", "a photo inside a subway train", "scene", ("地铁站", "城铁")),
    ("商场", "a photo inside a shopping mall", "scene", ("超市", "店铺")),
    ("游乐场", "a photo taken in an amusement park", "scene", ()),
    ("博物馆", "a photo inside a museum", "scene", ("展览", "展馆")),
    ("栈道", "a photo of a wooden boardwalk", "scene", ("木栈道", "海边栈道")),
    ("星空", "a photo of a starry night sky", "scene", ("银河", "夜空")),
    ("夜景", "a photo of a city at night with lights", "scene", ("夜晚", "灯光")),
    ("日出", "a photo of a sunrise", "scene", ("朝霞",)),
    ("日落", "a photo of a sunset", "scene", ("晚霞", "黄昏", "夕阳")),
    ("雾", "a photo with heavy fog", "scene", ("大雾", "雾气")),
    ("雪景", "a photo of a snowy landscape", "scene", ("下雪", "积雪")),
    ("雨天", "a photo taken in the rain", "scene", ("下雨",)),
    ("阴天", "a photo taken under an overcast sky", "scene", ()),
    ("晴天", "a photo taken under a clear blue sky", "scene", ("蓝天", "白云")),

    # ---- 主体 subject -----------------------------------------------------
    ("人像", "a portrait photo of a person", "subject", ("人物", "人", "女孩", "男生", "女生")),
    ("合影", "a photo of a couple posing together", "subject", ("情侣", "两个人", "合照")),
    ("单人照", "a photo of one person standing alone", "subject", ("单独一人",)),
    ("儿童", "a photo of a child", "subject", ("小孩", "孩子", "宝宝")),
    ("一群人", "a photo of a group of people", "subject", ("人群",)),
    ("背影", "a photo of a person seen from behind", "subject", ("背面",)),
    ("自拍", "a selfie photo", "subject", ("自拍照",)),
    ("宠物", "a photo of a pet animal", "subject", ("猫狗",)),
    ("猫", "a photo of a cat", "subject", ("小猫",)),
    ("狗", "a photo of a dog", "subject", ("小狗",)),
    ("鸟", "a photo of a bird", "subject", ("小鸟",)),
    ("食物", "a photo of food on a plate", "subject", ("吃的", "菜", "美食", "饭")),
    ("火锅", "a photo of a chinese hotpot", "subject", ("火锅店",)),
    ("咖啡", "a photo of a cup of coffee", "subject", ("拿铁", "咖啡杯")),
    ("蛋糕", "a photo of a cake", "subject", ("甜品", "甜点")),
    ("水果", "a photo of fresh fruit", "subject", ()),
    ("花", "a close up photo of flowers", "subject", ("花朵", "鲜花")),
    ("树", "a photo of a tree", "subject", ("大树", "树木")),
    ("汽车", "a photo of a car", "subject", ("轿车", "车辆")),
    ("摩托车", "a photo of a motorcycle", "subject", ("摩托",)),
    ("自行车", "a photo of a bicycle", "subject", ("单车",)),
    ("船", "a photo of a boat on the water", "subject", ("小船", "游船")),
    ("帐篷", "a photo of a camping tent", "subject", ("露营",)),
    ("经幡", "a photo of colorful tibetan prayer flags", "subject", ("旗子", "彩旗")),
    ("牦牛", "a photo of a yak", "subject", ("牛",)),
    ("马", "a photo of a horse", "subject", ()),
    ("招牌", "a photo of a sign with chinese characters", "subject", ("牌子", "路牌")),

    # ---- 光线与风格 light / style ----------------------------------------
    ("逆光", "a photo taken against the light", "light", ("背光",)),
    ("强光", "a photo with harsh bright sunlight", "light", ("大太阳",)),
    ("弱光", "a photo taken in dim low light", "light", ("暗光", "光线很暗")),
    ("闪光灯", "a photo taken with a camera flash", "light", ("打了闪光灯",)),
    ("黑白", "a black and white photograph", "light", ("黑白照",)),
    ("特写", "a close up photo", "light", ("近景", "微距")),
    ("远景", "a wide landscape photo with a tiny subject", "light", ("大场景", "广角")),
    ("俯拍", "a photo taken from above looking down", "light", ("从上往下",)),
    ("仰拍", "a photo taken from below looking up", "light", ("从下往上",)),
    ("截图", "a screenshot of a phone screen", "light", ("手机截图",)),
    ("文档", "a photo of a document or paper", "light", ("文件", "纸张")),
]

GROUP_LABELS = {"scene": "场景", "subject": "主体", "light": "光线"}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
VECTORS = os.path.join(DATA_DIR, "tag_vecs.npy")


def as_dicts() -> list[dict]:
    return [{"zh": z, "en": e, "group": g, "alias": list(a)} for z, e, g, a in TAGS]


def names() -> list[str]:
    return [t[0] for t in TAGS]


def alias_index() -> dict[str, str]:
    out: dict[str, str] = {}
    for zh, _en, _g, aliases in TAGS:
        out[zh] = zh
        for a in aliases:
            out.setdefault(a, zh)
    return out


def resolve(q: str) -> tuple[str | None, list[str]]:
    """(matched tag, suggestions).

    Exact, then alias, then substring either way. The suggestions matter: a
    query that finds nothing should say what it *does* know, not just fail.
    """
    q = (q or "").strip()
    if not q:
        return None, []
    idx = alias_index()
    if q in idx:
        return idx[q], []
    subs = [zh for zh in names() if q in zh or zh in q]
    if len(subs) == 1:
        return subs[0], []
    if subs:
        return None, subs
    subs = [word for word in idx if q in word][:8]
    if subs:
        return None, [idx[w] for w in subs]
    return None, []


def vectors() -> np.ndarray | None:
    """(n_tags, 512) float32, L2-normalised, or None when not shipped yet."""
    if not os.path.exists(VECTORS):
        return None
    v = np.load(VECTORS).astype(np.float32)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.maximum(n, 1e-8)


def meta() -> dict:
    return {"count": len(TAGS), "groups": GROUP_LABELS,
            "vectors": os.path.exists(VECTORS), "tags": as_dicts()}
