import sys; sys.path.insert(0,'.')
import ch1, horizon as HZ, solver_skyline as SK, numpy as np, math
from PIL import Image
dev,_=ch1.split(); d=SK._dem()
win=0; win_exact=0
for it in dev:
    img=Image.open(it['path']); W,H=img.size
    gt=HZ.gt_rows(it['mask']); az,el=HZ.rows_to_angles(gt,it['focal_px'],W,H); v=(gt>1)&(gt<H-2)
    j,e,vv=SK.resample_1deg(az,el,v)
    lats,lons,prof=SK.grid(it['prior_lat'],it['prior_lon'],it['loc_key'])
    cs,_,_=SK.match(j,e,vv,prof,'rms_detrend')
    cl=math.cos(math.radians(it['lat']))
    P=np.stack([d.profile(it['lat']+dn/111.195, it['lon']+de/111.195/cl) for dn in np.arange(-1,1.01,.25) for de in np.arange(-1,1.01,.25)])
    s,_,_=SK.match(j,e,vv,P,'rms_detrend')
    pe=d.profile(it['lat'],it['lon']); se,_,_=SK.match(j,e,vv,pe[None],'rms_detrend')
    win+= s.max()>=cs.max(); win_exact+= se[0]>=cs.max()
    print(it['id'][:18], 'grid best',round(cs.max(),3),'near-truth 250m best',round(s.max(),3),'exact',round(se[0],3))
print('near-truth fine grid beats global 1km best:',win,'/',len(dev),' exact truth beats:',win_exact)
