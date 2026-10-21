"""A small bilingual scene vocabulary for zero-shot CLIP tagging.

Why a fixed list instead of free-form text: CLIP's text encoder is trained on
English, so "海边" goes in as gibberish and comes out as noise. Mapping the
Chinese word to an English prompt through a curated list is both more accurate
and more predictable than machine translation, and it keeps the runtime free of
a text encoder entirely (the vectors below are precomputed once, here).

`en` is written as a full prompt because that is what CLIP was trained to match
("a photo of a beach"), not as a bare noun.

Groups exist so the UI can show "场景 / 主体 / 光线" separately instead of one
undifferentiated wall of labels.
"""

TAGS = [
    # ---- 场景 scene -------------------------------------------------------
    ("海边", "a photo of a beach and the sea", "scene", ["沙滩", "大海", "海滩", "海岸"]),
    ("湖泊", "a photo of a calm lake surrounded by mountains", "scene", ["湖", "湖水", "湖面"]),
    ("雪山", "a photo of snow covered mountains", "scene", ["雪山", "雪峰", "冰川"]),
    ("山峰", "a photo of rocky mountain peaks", "scene", ["山", "山脉", "高山"]),
    ("云海", "a photo of a sea of clouds below mountain peaks", "scene", ["云雾", "云"]),
    ("森林", "a photo of a dense green forest", "scene", ["树林", "林子", "松林"]),
    ("草地", "a photo of a green grass meadow", "scene", ["草原", "草坪", "草甸"]),
    ("花田", "a photo of a field full of flowers", "scene", ["花海", "花丛", "野花"]),
    ("溪流", "a photo of a stream flowing over rocks", "scene", ["小河", "溪水", "小河沟"]),
    ("瀑布", "a photo of a waterfall", "scene", ["跌水"]),
    ("沙漠", "a photo of sand dunes in a desert", "scene", ["沙丘", "戈壁"]),
    ("峡谷", "a photo of a deep canyon", "scene", ["山谷", "峡谷"]),
    ("城市街道", "a photo of a city street with buildings", "scene", ["街道", "马路", "街", "城区"]),
    ("古镇", "a photo of an old chinese town with traditional houses", "scene", ["老街", "古镇", "老房子"]),
    ("寺庙", "a photo of a chinese temple", "scene", ["佛寺", "寺院", "庙"]),
    ("教堂", "a photo of a church", "scene", []),
    ("建筑", "a photo of a modern building", "scene", ["楼房", "高楼", "大厦"]),
    ("室内", "a photo taken indoors in a room", "scene", ["房间", "屋里"]),
    ("咖啡馆", "a photo inside a cafe", "scene", ["咖啡店", "咖啡厅"]),
    ("餐厅", "a photo inside a restaurant", "scene", ["饭店", "餐馆"]),
    ("公路", "a photo of an empty road", "scene", ["路上", "车道", "盘山路"]),
    ("桥", "a photo of a bridge", "scene", ["桥面", "吊桥"]),
    ("公园", "a photo taken in a park", "scene", ["园林"]),
    ("停车场", "a photo of a parking lot", "scene", []),
    ("机场", "a photo inside an airport", "scene", []),
    ("火车站", "a photo of a train station", "scene", ["车站", "月台"]),
    ("地铁", "a photo inside a subway train", "scene", ["地铁站", "城铁"]),
    ("商场", "a photo inside a shopping mall", "scene", ["超市", "店铺"]),
    ("游乐场", "a photo taken in an amusement park", "scene", []),
    ("博物馆", "a photo inside a museum", "scene", ["展览", "展馆"]),
    ("海边栈道", "a photo of a wooden boardwalk along the water", "scene", ["栈道", "木栈道"]),
    ("星空", "a photo of a starry night sky", "scene", ["银河", "夜空"]),
    ("夜景", "a photo of a city at night with lights", "scene", ["夜晚街道", "灯光"]),
    ("日出", "a photo of a sunrise", "scene", ["朝霞", "早上"]),
    ("日落", "a photo of a sunset", "scene", ["晚霞", "黄昏", "夕阳"]),
    ("雾", "a photo with heavy fog", "scene", ["大雾", "雾气"]),
    ("雪景", "a photo of a snowy landscape", "scene", ["下雪", "积雪"]),
    ("雨天", "a photo taken in the rain", "scene", ["下雨"]),
    ("阴天", "a photo taken under an overcast sky", "scene", []),
    ("晴天", "a photo taken under a clear blue sky", "scene", ["蓝天", "白云"]),

    # ---- 主体 subject -----------------------------------------------------
    ("人像", "a portrait photo of a person", "subject", ["人物", "人", "女孩", "男生", "女生"]),
    ("合影", "a photo of a couple posing together", "subject", ["情侣", "两个人", "合照"]),
    ("单人照", "a photo of one person standing alone", "subject", ["单独一人"]),
    ("儿童", "a photo of a child", "subject", ["小孩", "孩子", "宝宝"]),
    ("一群人", "a photo of a group of people", "subject", ["人群", "一群人"]),
    ("背影", "a photo of a person seen from behind", "subject", ["背面"]),
    ("自拍", "a selfie photo", "subject", ["自拍照"]),
    ("宠物", "a photo of a pet animal", "subject", ["猫狗"]),
    ("猫", "a photo of a cat", "subject", ["小猫"]),
    ("狗", "a photo of a dog", "subject", ["小狗"]),
    ("鸟", "a photo of a bird", "subject", ["小鸟"]),
    ("食物", "a photo of food on a plate", "subject", ["吃的", "菜", "美食", "饭"]),
    ("火锅", "a photo of a chinese hotpot", "subject", ["火锅店"]),
    ("咖啡", "a photo of a cup of coffee", "subject", ["拿铁", "咖啡杯"]),
    ("蛋糕", "a photo of a cake", "subject", ["甜品", "甜点"]),
    ("水果", "a photo of fresh fruit", "subject", []),
    ("花", "a close up photo of flowers", "subject", ["花朵", "鲜花"]),
    ("树", "a photo of a tree", "subject", ["大树", "树木"]),
    ("汽车", "a photo of a car", "subject", ["轿车", "车辆"]),
    ("摩托车", "a photo of a motorcycle", "subject", ["摩托"]),
    ("自行车", "a photo of a bicycle", "subject", ["单车"]),
    ("船", "a photo of a boat on the water", "subject", ["小船", "游船"]),
    ("帐篷", "a photo of a camping tent", "subject", ["露营"]),
    ("经幡", "a photo of colorful tibetan prayer flags", "subject", ["旗子", "彩旗"]),
    ("牦牛", "a photo of a yak", "subject", ["牛"]),
    ("马", "a photo of a horse", "subject", []),
    ("文字招牌", "a photo of a sign with chinese characters", "subject", ["招牌", "牌子", "路牌"]),

    # ---- 光线与风格 light / style ----------------------------------------
    ("逆光", "a photo taken against the light", "light", ["背光"]),
    ("强光", "a photo with harsh bright sunlight", "light", ["大太阳"]),
    ("弱光", "a photo taken in dim low light", "light", ["暗光", "光线很暗"]),
    ("闪光灯", "a photo taken with a camera flash", "light", ["打了闪光灯"]),
    ("黑白", "a black and white photograph", "light", ["黑白照"]),
    ("特写", "a close up photo", "light", ["近景", "微距"]),
    ("远景", "a wide landscape photo with a tiny subject", "light", ["大场景", "广角"]),
    ("俯拍", "a photo taken from above looking down", "light", ["从上往下"]),
    ("仰拍", "a photo taken from below looking up", "light", ["从下往上"]),
    ("手机截图", "a screenshot of a phone screen", "light", ["截图"]),
    ("文档", "a photo of a document or paper", "light", ["文件", "纸张"]),
]

COLUMNS = ("zh", "en", "group", "alias")


def as_dicts() -> list[dict]:
    return [dict(zip(COLUMNS, t)) for t in TAGS]


def alias_index() -> dict[str, str]:
    """Every Chinese word that should find this tag -> the tag's Chinese name."""
    out: dict[str, str] = {}
    for zh, _en, _g, aliases in TAGS:
        out[zh] = zh
        for a in aliases:
            out.setdefault(a, zh)
    return out
