import json, sys, numpy as np, tetra3
sys.path.insert(0,'.')
import solver_stars as S
from multiprocessing import Pool
rows=[r for r in json.load(open('results/stars_real.json')) if r['subset'] in ('pixel4a-high-res','pixel6-high-res') and not r['solved']]
def run(r):
    g=S.load_gray(r['path']); fe=r['fov_est'] or 70; out=[]
    c=tetra3.get_centroids_from_image(g,max_returned=400)
    for frac in (0.5,0.65,0.8):
        cc=c[c[:,0]<frac*g.shape[0]][:60]
        s=S._t3('phone').solve_from_centroids(cc,g.shape,fov_estimate=fe,fov_max_error=12,pattern_checking_stars=12,solve_timeout=3000) if len(cc)>=4 else {}
        out.append(s.get('RA') is not None)
    return out
with Pool(12) as p: R=np.array(p.map(run,rows))
print(len(rows), R.sum(0))
