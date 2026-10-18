import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from wig_catalog_names import hairstyle_name, mention_evidence, resolution_policy


def test_catalogue_names():
    assert hairstyle_name('小圆-福利款·涩谷纱绘子·精修【仿递针工艺·免发网假发】中长发假发') == '涩谷纱绘子'
    assert hairstyle_name('kuku【免发网仿递针假发-布蕾兔】奶咖色精修中分假发全头套') == '布蕾兔'
    assert hairstyle_name('小圆-夺回&人生【仿递针】混进口丝发型师精修日常大波浪假发套') == '夺回&人生'


def test_current_identity_not_merely_a_mention():
    for text in ['夺回人生过了吗','夺回已过','以后夺回人生的话','有没有人生','下一款是人生']:
        assert not mention_evidence(text,'夺回&人生')['current']
    assert mention_evidence('这款叫涩谷纱绘子','涩谷纱绘子')['current']
    assert mention_evidence('这是人生','夺回&人生')['current']


def test_resolution_both_orientations_and_failed_probe():
    assert resolution_policy(1080,1920)['usable']
    assert resolution_policy(1920,1080)['usable']
    assert not resolution_policy(720,1280)['usable']
    assert resolution_policy(None,None)['action']=='review'


def test_names_do_not_merge_specification_suffixes():
    examples = {
        'KuKu公主假发-【宝宝冰蓝】发型师精修前蕾丝巴黎画染大波浪长卷发': '宝宝冰蓝',
        'kuku【美式拉拉队】进口弹力网假发': '美式拉拉队',
        'kuku【西梅乌龙】发型师精修中长发假发': '西梅乌龙',
        '小圆-夺回&人生【仿递针】发型师精修日常大波浪假发套': '夺回&人生',
        '小圆-芝麻乌龙·直发版【免发网】': '芝麻乌龙',
        '小圆-澳洲紫玫瑰【免发网】lolita假发': '澳洲紫玫瑰',
        '全进口丝假发': '',
        '【仿递针工艺·免发网假发】中长发假发': '',
    }
    for title, expected in examples.items():
        assert hairstyle_name(title) == expected, title


def test_color_alone_is_not_a_hairstyle_name():
    assert hairstyle_name('小圆【可以不戴发网的假发-黑色 昭和美人】精修日常长卷发')=='昭和美人'
    assert hairstyle_name('小圆-黑色【免发网假发】长卷发')==''


def test_no_styling_specification_does_not_hide_real_name():
    assert hairstyle_name('小圆【免醒发仿递针-天蝎座】精修进口混丝黑茶色齐刘海全头套假发') == '天蝎座'
    assert hairstyle_name('小圆【免醒发仿递针-焦糖栗子系列】精修进口混丝棕色假发') == '焦糖栗子系列'
    assert hairstyle_name('小圆【免醒发仿递针-升级版天蝎座】黑茶色全头套假发') == '天蝎座'
