"""Minimal guarded patch for product loading in the drifted production bundle."""
import hashlib

EXPECTED = 'd957372b5ab16a483ab4800b086434ee2e88cc2e21ed2b4b9c26f095510a7ed3'


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Product loading anchor mismatch')
    return text.replace(before, after, 1)


def patch(text):
    assert hashlib.sha256(text.encode()).hexdigest() == EXPECTED, 'Production bundle drift'
    text = once(text, 'async function T(){i.value=await ss()}',
        'let productLoading=z(!0),productError=z(``);async function T(){productLoading.value=!0;productError.value=``;try{let items=await ss();if(!Array.isArray(items))throw Error(`商品数据格式错误`);i.value=items}catch(e){productError.value=`商品加载失败，请重试`;r(productError.value,`error`)}finally{productLoading.value=!1}}')
    text = once(text, 'Qn(async()=>{a.value=await Do(),await T()})',
        'Qn(()=>{Promise.allSettled([Do().then(items=>{a.value=items}).catch(()=>r(`直播间加载失败，商品仍可查看`,`error`)),T()])})')
    text = once(text, 'K(`div`,I_,[V(K(`select`',
        'K(`div`,I_,[K(`button`,{class:`btn-secondary`,disabled:productLoading.value,onClick:T},productLoading.value?`加载中…`:`刷新商品`),productError.value?K(`span`,{role:`alert`,style:{color:`#fbbf24`}},productError.value):J(``,!0),V(K(`select`')
    return once(text, 'G(`div`,vv,`暂无商品`)',
        'G(`div`,vv,productLoading.value?`正在加载商品…`:productError.value?`商品加载失败，请点击“刷新商品”重试`:o.value||s.value?`没有符合筛选条件的商品`:`暂无商品`)')
