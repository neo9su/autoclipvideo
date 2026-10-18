import pytest
from backend.publish_product_links import ProductLinkUnavailable,resolve_publish_products

PRODUCTS=[{'id':1,'product_id':'dom_a','product_name':'same','product_url':'https://example.invalid/a'},
          {'id':2,'product_id':'1234567890123456789','product_name':'same','product_url':'https://example.invalid/b'},
          {'id':3,'product_id':'dom_missing','product_name':'missing','product_url':''}]


def test_multi_selection_preserves_order_same_names_distinct_urls():
    r=resolve_publish_products({'product_ids':'2,1,2'},PRODUCTS)
    assert r=={'links':['https://example.invalid/b','https://example.invalid/a'],'names':['same','same']}


def test_single_catalogue_selection_reads_updated_url_not_dom_id():
    assert resolve_publish_products({'product_id':1,'product_douyin_id':'dom_a'},PRODUCTS)['links']==['https://example.invalid/a']


def test_missing_one_link_never_silently_publishes_partial_cart():
    for selection in ('1,3','99','3','bad','0','1.5'):
        with pytest.raises(ProductLinkUnavailable):resolve_publish_products({'product_ids':selection},PRODUCTS)


def test_legacy_id_requires_a_unique_stored_url_not_url_construction():
    assert resolve_publish_products({'product_douyin_id':'1234567890123456789'},PRODUCTS)['links']==['https://example.invalid/b']
    for legacy in ('dom_missing','9999999999999999999'):
        with pytest.raises(ProductLinkUnavailable):resolve_publish_products({'product_douyin_id':legacy},PRODUCTS)
    extra=PRODUCTS+[dict(PRODUCTS[1],id=4,product_url='https://example.invalid/other')]
    with pytest.raises(ProductLinkUnavailable):resolve_publish_products({'product_douyin_id':'1234567890123456789'},extra)


def test_explicit_no_cart_and_legacy_direct_url_remain_supported():
    assert resolve_publish_products({'no_cart':1,'product_ids':'3'},PRODUCTS)=={'links':[],'names':[]}
    assert resolve_publish_products({'product_douyin_id':'https://example.invalid/direct'},[])['links']==['https://example.invalid/direct']
    for bad in ('javascript:alert(1)','http://user:password@example.invalid/a'):
        with pytest.raises(ProductLinkUnavailable):resolve_publish_products({'product_douyin_id':bad},[])


def test_duplicate_url_is_not_added_twice_and_invalid_url_is_rejected():
    extra=PRODUCTS+[dict(PRODUCTS[0],id=5),dict(PRODUCTS[0],id=6,product_url='dom_bad')]
    assert resolve_publish_products({'product_ids':[1,5]},extra)['links']==['https://example.invalid/a']
    with pytest.raises(ProductLinkUnavailable):resolve_publish_products({'product_id':6},extra)
