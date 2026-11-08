import sys; sys.path.insert(0,'.')
import ch1, horizon as HZ, solver_skyline as SK, numpy as np, math
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from PIL import Image
dev,_=ch1.split(); d=SK._dem()
fig,axs=plt.subplots(4,2,figsize=(14,12))
for ax,it in zip(axs.ravel(),dev[:8]):
    img=Image.open(it['path']); W,H=img.size
    gt=HZ.gt_rows(it['mask']); az,el=HZ.rows_to_angles(gt,it['focal_px'],W,H); v=(gt>1)&(gt<H-2)
    j,e,vv=SK.resample_1deg(az,el,v)
    pt=d.profile(it['lat'],it['lon'])
    s,ps,S=SK.match(j,e,vv,pt[None],'rms_detrend')
    psi=int(ps[0]); win=pt[(psi+j)%360]
    ax.plot(j[vv], e[vv]-e[vv].mean()+win[vv].mean(),'b-',label='photo (GT mask)')
    ax.plot(j, win,'r-',label=f'DEM at truth, heading {psi}')
    full=np.arange(-90,91); ax.plot(full, pt[(psi+full)%360],'r:',alpha=.4)
    ax.set_title(f"{it['id'][:20]} s={s[0]:.2f} hfov={it['hfov']:.0f}"); ax.legend(fontsize=7)
plt.tight_layout(); plt.savefig('tmp/diag.png',dpi=60)
