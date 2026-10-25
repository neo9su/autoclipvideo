"""Reuse the immutable frontend-entry deployer with room-label release anchors."""
from pathlib import Path


def build():
    source=(Path(__file__).with_name('deploy_product_loading.py')).read_text()
    changes={
        "OLD_ASSET='index-publish-notice-d957372b5ab1.js'":"OLD_ASSET='index-publish-loading-40433d572265.js'",
        "OLD_SHA='d957372b5ab16a483ab4800b086434ee2e88cc2e21ed2b4b9c26f095510a7ed3'":"OLD_SHA='40433d572265687e9d28fe20e214f1b7e8e91563240b8eb66147afce99a07f9f'",
        "asset_name=='index-product-loading-'":"asset_name=='index-publish-rooms-'",
        "('product-loading-'+datetime":"('publish-rooms-'+datetime",
    }
    for old,new in changes.items():
        assert source.count(old)==1,'Frontend deploy template drift'
        source=source.replace(old,new,1)
    compile(source,'<room-label-deploy>','exec')
    return source


if __name__=='__main__':print(build())
