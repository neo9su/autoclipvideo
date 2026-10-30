import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from publish_catalog_match import match_candidates


def row(i,name='氧气栗子',room=1,enabled=1,url=None,keywords=''):
    return dict(id=i,product_name=name,room_id=room,enabled=enabled,product_url=url if url is not None else f'https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id={3800000000000000000+i}',keywords=keywords)


def test_spoken_alias_selects_all_distinct_links_and_excludes_wrong_keyword():
    rows=[row(1),row(2),row(3,room=None),row(4,name='夺回人生',keywords='氧气'),row(5,enabled=0),row(6,url=''),row(7,room=2)]
    assert [p['id'] for p in match_candidates({'wig_model':'氧气粒子直发','room_id':1},rows)]==[1,2,3]


def test_tracking_variants_deduplicated_but_same_name_distinct_products_kept():
    a=row(1);b=row(2,url=a['product_url']+'&origin_type=2631')
    assert [p['id'] for p in match_candidates({'room_id':1},[a,b,row(3)],'氧气粒子')]==[1,3]
