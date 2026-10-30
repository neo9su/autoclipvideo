"""Add catalog IDs to both existing product pickers without unrelated assets."""
from pathlib import Path
import hashlib
from prepare_frontend_asset_deploy import build

OLD = 'index-publish-upload-48b36fc05b48.js'
SHA = '48b36fc05b488db604f4dcb2004a551568049bf020ee53cb100cce6442a98b37'


def patch(source):
    for key in ('vx', 'pS'):
        before = f'G(`span`,{key},N(e.room_name),1)):J(``,!0),K(`span`,null,N(e.product_name),1)'
        after = before.replace('N(e.product_name)', '`ID: `+N(e.id)+` · `+N(e.product_name)')
        assert source.count(before) == 1, 'Product picker changed; stop deployment'
        source = source.replace(before, after)
    return source


def main():
    root = Path(r'C:\Users\neo\douyin_backend\frontend\dist\assets')
    original = (root / OLD).read_bytes()
    assert hashlib.sha256(original).hexdigest() == SHA
    data = patch(original.decode('utf-8')).encode('utf-8')
    digest = hashlib.sha256(data).hexdigest()
    name = 'index-product-ids-' + digest[:12] + '.js'
    (root / name).with_suffix('.stage').write_bytes(data)
    namespace = {'__name__': 'product_id_deployment'}
    exec(build(OLD, SHA, 'index-product-ids-', 'product-ids-'), namespace)
    namespace['main'](name, digest)


if __name__ == '__main__':
    main()
