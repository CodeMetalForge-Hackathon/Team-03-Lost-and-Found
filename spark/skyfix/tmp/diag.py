import sys; sys.path.insert(0,'.')
import ch1, horizon as HZ, solver_skyline as SK, numpy as np, math
from PIL import Image
dev,_=ch1.split(); d=SK._dem()
for it in dev[:8]:
    img=Image.open(it['path']); W,H=img.size
    gt=HZ.gt_rows(it['mask']); az,el=HZ.rows_to_angles(gt,it['focal_px'],W,H); v=(gt>1)&(gt<H-2)
    j,e,vv=SK.resample_1deg(az,el,v)
    lats,lons,prof=SK.grid(it['prior_lat'],it['prior_lon'],it['loc_key'])
    cs,cpsi,_=SK.match(j,e,vv,prof,'rms')
    p_true,dist,h0=d.profile(it['lat'],it['lon'],return_dist=True)
    res=[]
    for dh in (0,50,100,200,400):
        pt=d.profile(it['lat'],it['lon'],obs_h_m=1.7+dh)
        s,ps,_=SK.match(j,e,vv,pt[None],'rms'); res.append((dh,round(float(s[0]),3),int(ps[0])))
    print(it['id'][:22], 'best',round(float(cs.max()),3),'truth@h:',res, 'h0',round(h0), 'ptp photo',round(np.ptp(e[vv]),1),'valid',vv.sum())
