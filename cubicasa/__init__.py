from io import BytesIO
import logging
import requests
from tqdm.auto import tqdm
from zipfile import ZipFile
import pandas as pd
from pathlib import Path
import gzip
import numpy as np
from rebar import parallel

log = logging.getLogger(__name__)

def download(url):
    bs = BytesIO()
    log.info(f'Downloading {url}')
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers['Content-Length']) if 'Content-Length' in r.headers else None
        with tqdm(total=total, unit_scale=True, unit_divisor=1024, unit='B') as pbar:
            for chunk in r.iter_content(chunk_size=2**20): 
                pbar.update(len(chunk))
                bs.write(chunk)
    return bs.getvalue()

def cubicasa5k():
    p = Path('.cache/cubicasa.zip')
    if not p.exists():
        url = 'https://zenodo.org/record/2613548/files/cubicasa5k.zip?download=1'
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_bytes(download(url))
    return str(p)

def svgdata(regenerate=False):
    p = Path('.cache/cubicasa-svgs.json.gz')
    if not p.exists():
        p.parent.mkdir(exist_ok=True, parents=True)
        if regenerate:
            log.info('Regenerating SVG cache from cubicasa dataset. This will require a 5G download.')
            with ZipFile(cubicasa5k()) as zf:
                pattern = r'cubicasa5k/(?P<category>[^/]*)/(?P<id>\d+)/(?P<filename>[^.]*)\.svg'
                svgs = (pd.Series(zf.namelist(), name='path')
                            .to_frame()
                            .loc[lambda df: df.path.str.match(pattern)]
                            .reset_index(drop=True))
                svgs = pd.concat([svgs, svgs.path.str.extract(pattern)], axis=1)
                svgs['svg'] = svgs.path.apply(lambda p: zf.read(p).decode())
                compressed = gzip.compress(svgs.to_json().encode())
                p.write_bytes(compressed)
        else:
            #TODO: Shift this to Github 
            url = 'https://www.dropbox.com/s/iblduqobhqomz4g/cubicasa-svgs.json.gzip?raw=1'
            p.write_bytes(download(url))
    return pd.read_json(gzip.decompress(p.read_bytes()))

def flatten(tree):
    flat = {}
    for k, v in tree.items():
        if isinstance(v, dict):
            for kk, vv in flatten(v).items():
                flat[f'{k}/{kk}'] = vv
        else:
            flat[k] = v
    return flat

def geometrydata(regenerate=False):
    # Why .npz.gz? Because applying gzip manually manages x10 better compression than
    # np.savez_compressed. They use the same compression alg, so I assume the difference
    # is in the default compression setting.
    p = Path('.cache/cubicasa-geometry.npz.gz')
    if not p.exists():
        p.parent.mkdir(exist_ok=True, parents=True)
        if regenerate:
            log.info('Regenerating geometry cache from SVG cache.')
            # Hide the import since it uses a fair number of libraries.
            from . import geometry
            with parallel.parallel(geometry.geometry) as pool:
                gs = pool.wait({str(row.id): pool(row.id, row.svg) for _, row in svgdata(regenerate).iterrows()})
            gs = flatten(gs)

            bs = BytesIO()
            np.savez(bs, **gs)
            p.write_bytes(gzip.compress(bs.getvalue()))
        else:
            #TODO: Shift this to Github 
            url = ''
            p.write_bytes(download(url))
    return np.load(BytesIO(gzip.decompress(p.read_bytes())))
