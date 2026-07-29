# -*- coding: utf-8 -*-
"""商品库种子数据：成品家具 SKU + 定制报价规则（模拟数据，后期手动替换为真实产品）。

    python seed_data.py          # 空表时灌入，已有数据则跳过
    python seed_data.py --force  # 清空后重灌
"""

import sys

from app.db.database import Base, SessionLocal, engine
from app.db.models import CustomQuoteRule, Product

PRODUCTS = [
    # ---- 客厅 ----
    dict(sku="SF-001", name="云朵感三人位布艺沙发", category="沙发", room="客厅", style="奶油风",
         material="科技布 + 高回弹海绵", price=4999, price_max=7299, size="宽 2.4m x 深 1.05m",
         selling_point="科技布耐抓易清洁，坐感松弛，宠物家庭首选", alternative="棉麻布艺款（更透气，价格低 500）"),
    dict(sku="SF-002", name="奶油白猫抓布转角沙发", category="沙发", room="客厅", style="奶油风",
         material="猫抓布 + 白蜡木脚", price=6800, price_max=9800, size="2.8m x 1.7m 转角",
         selling_point="L 型转角利用率高，猫抓布面料五年质保", alternative="直排三人位（小客厅更合适）"),
    dict(sku="SF-003", name="中古风绒布单人椅", category="沙发", room="客厅", style="中古风",
         material="复古绒布 + 实木框架", price=1580, size="宽 0.78m",
         selling_point="一抹复古绿点亮空间，阅读角标配", alternative="藤编休闲椅（更轻盈）"),
    dict(sku="CJ-001", name="白蜡木圆角茶几", category="茶几", room="客厅", style="原木风",
         material="北美白蜡木", price=1680, price_max=2280, size="直径 0.8m / 0.9m 两规格",
         selling_point="全圆角设计对孩子友好，实木耐用越用越润", alternative="岩板小边几组合（更易清洁）"),
    dict(sku="CJ-002", name="岩板套几（大小两件）", category="茶几", room="客厅", style="轻奢风",
         material="哑光岩板 + 碳素钢", price=2380, size="0.9m + 0.6m 组合",
         selling_point="可分可合灵活挪动，岩板不怕烫不渗色", alternative="白蜡木圆角茶几（更温润）"),
    dict(sku="DG-001", name="奶油白蘑菇落地灯", category="灯具", room="客厅", style="奶油风",
         material="金属烤漆 + 玻璃灯罩", price=680, size="高 1.5m",
         selling_point="3000K 暖光，沙发角氛围担当", alternative="可调色温阅读落地灯（功能性更强）"),
    dict(sku="DT-001", name="低饱和几何短绒地毯", category="地毯", room="客厅", style="北欧风",
         material="混纺短绒", price=990, price_max=1690, size="2m x 2.9m",
         selling_point="短绒好打理，扫地机器人无压力", alternative="羊毛平织款（质感更好需保养）"),
    # ---- 卧室 ----
    dict(sku="CH-001", name="白橡木悬浮床架", category="床", room="卧室", style="日式风",
         material="白橡木", price=3680, price_max=5280, size="1.5m / 1.8m 两规格",
         selling_point="低矮悬浮设计放大层高，FAS 级实木", alternative="软包箱体床（收纳更强）"),
    dict(sku="CH-002", name="奶油风软包床", category="床", room="卧室", style="奶油风",
         material="猫抓布软包 + 松木框架", price=2980, price_max=4380, size="1.8m x 2m",
         selling_point="床头软包倚靠舒适，圆润无锐角", alternative="白橡木悬浮床（更透气简洁）"),
    dict(sku="CT-001", name="藤编床头柜", category="柜子", room="卧室", style="原木风",
         material="橡胶木 + 藤编", price=880, size="0.45m x 0.4m",
         selling_point="藤编门透气不闷潮，抽屉静音滑轨", alternative="悬浮壁挂床头柜（小卧室释放地面）"),
    dict(sku="DG-002", name="纸艺吊线床头灯（一对）", category="灯具", room="卧室", style="日式风",
         material="纸艺灯罩", price=460, size="直径 0.3m x2",
         selling_point="替代台灯释放床头柜台面，光线柔和助眠", alternative="壁挂阅读灯（光线更聚焦）"),
    dict(sku="CL-001", name="亚麻遮光窗帘", category="窗帘", room="卧室", style="日式风",
         material="亚麻混纺 85% 遮光", price=95, price_max=160, size="按米计价（幅宽 2.8m）",
         selling_point="天然肌理透气感 + 达标遮光，卧室平衡之选", alternative="雪尼尔全遮光帘（遮光 99%）"),
    # ---- 餐厅 ----
    dict(sku="ZY-001", name="岩板圆形餐桌", category="餐桌", room="餐厅", style="轻奢风",
         material="12mm 岩板 + 碳素钢", price=3280, price_max=4680, size="直径 1.2m / 1.35m",
         selling_point="圆桌动线灵活，岩板耐高温易清洁", alternative="白蜡木原木餐桌（氛围更温馨）"),
    dict(sku="ZY-002", name="白蜡木原木长餐桌", category="餐桌", room="餐厅", style="原木风",
         material="北美白蜡木大板", price=2880, price_max=4280, size="1.4m / 1.6m / 1.8m",
         selling_point="一整块大板纹理自然，全家围坐有温度", alternative="岩板餐桌（更耐造零维护）"),
    dict(sku="CY-001", name="藤编靠背餐椅", category="餐椅", room="餐厅", style="原木风",
         material="橡胶木 + 手工藤编", price=460, size="座高 0.45m",
         selling_point="透气藤编久坐不闷，手工编织有质感", alternative="布艺软包餐椅（久坐更舒适）"),
    dict(sku="DG-003", name="黄铜玻璃餐吊灯", category="灯具", room="餐厅", style="轻奢风",
         material="拉丝黄铜 + 柔光玻璃", price=1180, size="直径 0.5m",
         selling_point="离桌 75cm 聚拢用餐氛围，铜件不生锈", alternative="纸艺吊灯（日式氛围）"),
    # ---- 书房 ----
    dict(sku="SZ-001", name="白蜡木电动升降书桌", category="书桌", room="书房", style="现代简约",
         material="白蜡木桌板 + 双电机架", price=2680, price_max=3980, size="1.4m x 0.7m",
         selling_point="可站可坐护腰，双电机三档记忆", alternative="固定实木长桌（预算减 1000）"),
    dict(sku="YZ-001", name="人体工学椅", category="书椅", room="书房", style="现代简约",
         material="网布 + 铝合金脚", price=1380, price_max=2280, size="标准款 / 大体型款",
         selling_point="居家办公久坐必备，腰托扶手全可调", alternative="实木软包书椅（颜值优先）"),
    dict(sku="SJ-001", name="白橡木开放书架", category="柜子", room="书房", style="原木风",
         material="白橡木框架", price=1980, size="0.8m x 1.8m",
         selling_point="开放格随手取阅，背板加固不晃", alternative="玻璃门书柜（防尘）"),
    dict(sku="DT-002", name="羊毛圈绒书房地毯", category="地毯", room="书房", style="日式风",
         material="新西兰羊毛", price=1480, size="1.6m x 2.3m",
         selling_point="圈绒耐压耐磨，冬天脚感温暖", alternative="剑麻编织毯（更透气）"),
]

QUOTE_RULES = [
    # 柜类定制（按投影面积 ㎡）
    dict(project_name="定制衣柜", category="柜类定制", pricing_unit="㎡", material_grade="E0 颗粒板",
         unit_price=680, description="投影面积计价，含柜体柜门基础五金；抽屉/格拉斯另计"),
    dict(project_name="定制衣柜", category="柜类定制", pricing_unit="㎡", material_grade="多层实木",
         unit_price=980, description="防潮性更好，握钉力强，南方潮湿环境推荐"),
    dict(project_name="定制衣柜", category="柜类定制", pricing_unit="㎡", material_grade="实木（橡木）",
         unit_price=1680, description="全实木框架柜门，环保与质感天花板"),
    dict(project_name="电视柜背景墙", category="柜类定制", pricing_unit="㎡", material_grade="E0 颗粒板 + 木饰面",
         unit_price=880, description="整墙收纳柜 + 木饰面背景，含灯带槽"),
    dict(project_name="玄关柜", category="柜类定制", pricing_unit="㎡", material_grade="E0 颗粒板",
         unit_price=720, description="顶天立地款，含换鞋凳位 + 底部感应灯带"),
    dict(project_name="书柜", category="柜类定制", pricing_unit="㎡", material_grade="多层实木",
         unit_price=920, description="层板加厚防弯，可选玻璃门"),
    dict(project_name="榻榻米", category="柜类定制", pricing_unit="㎡", material_grade="多层实木",
         unit_price=1080, description="含上翻门液压杆，床垫另计"),
    dict(project_name="阳台储物柜", category="柜类定制", pricing_unit="㎡", material_grade="E0 颗粒板（防潮封边）",
         unit_price=650, description="含洗衣机位预留，防潮铝封边"),
    # 厨房定制（按延米）
    dict(project_name="橱柜地柜", category="厨房定制", pricing_unit="延米", material_grade="多层实木 + 石英石台面",
         unit_price=1380, description="含台面、柜体、门板、基础五金；水槽灶具另计"),
    dict(project_name="橱柜吊柜", category="厨房定制", pricing_unit="延米", material_grade="多层实木",
         unit_price=780, description="含上翻/平开门板五金"),
    dict(project_name="岛台", category="厨房定制", pricing_unit="项", material_grade="多层实木 + 岩板台面",
         unit_price=4800, description="1.2m 标准岛台整项价，含插座预留"),
    # 其他
    dict(project_name="全屋窗帘定制", category="软装定制", pricing_unit="米", material_grade="亚麻混纺",
         unit_price=120, description="按轨道米数计价，含轨道安装；纱帘另计 60/米"),
]


def main():
    force = "--force" in sys.argv
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Product).count()
        if existing > 0 and not force:
            print(f"products 表已有 {existing} 条数据，跳过（用 --force 重灌）")
            return
        if force:
            db.query(Product).delete()
            db.query(CustomQuoteRule).delete()
            db.commit()
            print("已清空旧数据")

        db.add_all([Product(**p) for p in PRODUCTS])
        db.add_all([CustomQuoteRule(**r) for r in QUOTE_RULES])
        db.commit()
        print(f"OK: 已写入 {len(PRODUCTS)} 件成品家具 + {len(QUOTE_RULES)} 条定制报价规则")
    finally:
        db.close()


if __name__ == "__main__":
    main()
