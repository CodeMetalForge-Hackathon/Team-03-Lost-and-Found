import json, sys, numpy as np, tetra3, math
sys.path.insert(0,'.')
import solver_stars as S
from multiprocessing import Pool
rows=[r for r in json.load(open('results/stars_real.json')) if r['subset'] in ('pixel4a-high-res','pixel6-high-res')]
CFG=[dict(sigma=2),dict(sigma=3,max_axis_ratio=2.0),dict(sigma=4,max_axis_ratio=2.0),dict(sigma=3,max_axis_ratio=1.6,min_area=4),dict(sigma=5,max_axis_ratio=2.0)]
def run(r):
    g=S.load_gray(r['path']); res=[]
    for cfg in CFG:
        c=tetra3.get_centroids_from_image(g,max_returned=60,**cfg)
        fe=r['fov_est'] or 70
        ok=False
        for fe2 in (fe,):
            if len(c)>=4:
                s=S._t3('phone').solve_from_centroids(c,g.shape,fov_estimate=fe2,fov_max_error=12,pattern_checking_stars=12,solve_timeout=3000)
                ok=s.get('RA') is not None
        res.append(ok)
    return res
with Pool(12) as p: R=p.map(run,rows)
R=np.array(R); 
for cfg,col in zip(CFG,R.T): print(cfg, col.sum(),'/',len(col))
