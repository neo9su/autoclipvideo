from backend.cart_link_evidence import card_link_evidence


def url(pid):return 'https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id='+pid


def test_observed_links_preserve_same_name_different_products():
    a=card_link_evidence('同名商品',[url('3718933356298240815')])
    b=card_link_evidence('同名商品',[url('3829443305008136690')])
    assert a['product_id']!=b['product_id'] and a['product_url']!=b['product_url']


def test_mixed_card_and_untrusted_links_never_select_a_product():
    r=card_link_evidence('同名商品',[url('3718933356298240815'),url('3829443305008136690')])
    assert not r['product_url'] and len(r['observed_product_links'])==2
    assert r['link_evidence_status']=='multiple_products_in_card'
    for u in ('javascript:alert(1)',url('dom_123'),url('3718933356298240815')+'&id=3829443305008136690',
              url('3718933356298240815').replace('haohuo.jinritemai.com','haohuo.jinritemai.com.evil.invalid')):
        assert not card_link_evidence('同名商品',[u])['product_url']


def test_url_forms_same_id_keep_original_url_and_missing_evidence_stays_empty():
    u=url('3718933356298240815')
    r=card_link_evidence('同名商品',[u,u+'&origin_type=2631'])
    assert r['product_url']==u and r['product_id']=='3718933356298240815'
    assert card_link_evidence('同名商品',None)['product_url']==''
