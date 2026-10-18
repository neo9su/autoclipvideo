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
