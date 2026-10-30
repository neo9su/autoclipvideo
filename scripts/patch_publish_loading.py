"""Guarded picker-loading patch for the current drifted production bundle."""
import hashlib

EXPECTED = '4d5a20a07cba8b381d986089bf4afc695563d1cdf74d118e7f229b95c97fb596'


def once(source, before, after):
    if source.count(before) != 1:
        raise ValueError('Publish loading anchor drift')
    return source.replace(before, after, 1)


def patch(source):
    assert hashlib.sha256(source.encode()).hexdigest() == EXPECTED, 'Production bundle drift'
    source = once(source, 'async function Eo(e,t,n=`请求失败`){let r=await $(e,t);', 'async function Eo(e,t,n=`请求失败`,timeout){let r=await $(e,t,timeout);')
    source = once(source,
        'async function gt(){w.value=!0;try{let[e,t]=await Promise.all([Eo(`${Q}/api/codex/publish-groups`),ss()]);ee.value=e.filter(st),re.value=t.filter(e=>e.enabled)}finally{w.value=!1}}',
        'let publishGroupsError=z(``),publishGroupsLoad=null;function gt(){if(publishGroupsLoad)return publishGroupsLoad;w.value=!0;publishGroupsError.value=``;publishGroupsLoad=Promise.allSettled([Eo(`${Q}/api/codex/publish-groups`,void 0,`视频分组加载失败`,60000).then(items=>{if(!Array.isArray(items))throw Error(`分组数据格式错误`);ee.value=items.filter(st)}).catch(()=>{publishGroupsError.value=`视频分组加载失败，请点击刷新重试`;t(publishGroupsError.value,`error`)}),ss().then(items=>{re.value=items.filter(e=>e.enabled)}).catch(()=>t(`商品加载失败，请点击刷新重试`,`error`))]).finally(()=>{w.value=!1;publishGroupsLoad=null});return publishGroupsLoad}')
    source = once(source,
        'return Qn(async()=>{C(),await ft();let[e,n]=await Promise.all([Eo(`${Q}/api/codex/publish-groups`),Do()]);ee.value=e.filter(st),te.value=n,T.value=await _s();let i=T.value.find(e=>e.account_name===`颜遇生活`);i&&(I.value.account_id=i.id),re.value=(await ss()).filter(e=>e.enabled),ue=Po(',
        'return Qn(async()=>{C();await Promise.allSettled([ft(),gt(),Do().then(items=>{te.value=items}).catch(()=>t(`直播间加载失败，请重试`,`error`)),_s().then(items=>{T.value=items;let account=items.find(e=>e.account_name===`颜遇生活`);if(account)I.value.account_id=account.id}).catch(()=>t(`发布账号加载失败，请重试`,`error`))]);ue=Po(')
    source = once(source, 'K(`div`,Nb,[Xe.value.length?',
        'publishGroupsError.value?K(`div`,{role:`alert`,style:{color:`#f59e0b`,fontSize:`12px`}},publishGroupsError.value,1):J(``,!0),K(`div`,Nb,[Xe.value.length?')
    source = once(source,
        'G(`div`,Pb,(codexPublishBatch.query.value.trim()?\'未找到匹配的视频，请更换关键词\':\'暂无已合并分组\'))',
        'G(`div`,Pb,w.value?`正在加载视频分组…`:publishGroupsError.value?`加载失败，原有选择会保留，请刷新重试`:(codexPublishBatch.query.value.trim()?`未找到匹配的视频，请更换关键词`:`暂无已合并分组`),1)')
    return source
