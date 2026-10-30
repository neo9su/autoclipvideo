"""Reuse the existing immutable frontend deployer for a verified follow-up asset."""
from pathlib import Path
import re


def build(old_asset, old_sha, prefix, backup):
    assert re.fullmatch(r'index-[a-z0-9-]+\.js',old_asset)
    assert re.fullmatch(r'[a-f0-9]{64}',old_sha)
    assert re.fullmatch(r'index-[a-z-]+-',prefix) and re.fullmatch(r'[a-z-]+-',backup)
    source=Path(__file__).with_name('deploy_product_loading.py').read_text()
    changes={
        "OLD_ASSET='index-publish-notice-d957372b5ab1.js'":'OLD_ASSET='+repr(old_asset),
        "OLD_SHA='d957372b5ab16a483ab4800b086434ee2e88cc2e21ed2b4b9c26f095510a7ed3'":'OLD_SHA='+repr(old_sha),
        "asset_name=='index-product-loading-'":'asset_name=='+repr(prefix),
        "('product-loading-'+datetime":'('+repr(backup)+'+datetime',
    }
    for before,after in changes.items():
        assert source.count(before)==1,'Frontend deployment template drift'
        source=source.replace(before,after,1)
    compile(source,'<frontend deployment>','exec')
    return source
