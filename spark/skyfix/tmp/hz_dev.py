import sys; sys.path.insert(0,'.')
import horizon as H, ch1, numpy as np, torch
from PIL import Image
dev,_=ch1.split()
m,proc,devc=H._sam()
res={k:[] for k in ['best','largest','union','union_top5','dp']}
for it in dev:
    im=Image.open(it['path']).convert('RGB'); gt=H.gt_rows(it['mask']); w,h=im.size
    for name,pts in [('top3',[[0.5*w,0.03*h],[0.15*w,0.03*h],[0.85*w,0.03*h]]),('top5',[[x*w,0.03*h] for x in (0.1,0.3,0.5,0.7,0.9)])]:
        inp=proc(images=im,input_points=[[pts]],input_labels=[[[1]*len(pts)]],return_tensors='pt').to(devc)
        with torch.inference_mode(): out=m(**inp,multimask_output=True)
        mk=proc.post_process_masks(out.pred_masks.cpu(),inp['original_sizes'])[0][0].numpy()
        sc=out.iou_scores.cpu().numpy()[0,0]
        if name=='top3':
            res['best'].append(np.abs(H.rows_from_sky_mask(mk[sc.argmax()])-gt).mean())
            res['largest'].append(np.abs(H.rows_from_sky_mask(mk[mk.sum((1,2)).argmax()])-gt).mean())
            res['union'].append(np.abs(H.rows_from_sky_mask(mk.any(0))-gt).mean())
        else:
            res['union_top5'].append(np.abs(H.rows_from_sky_mask(mk.any(0))-gt).mean())
    res['dp'].append(np.abs(H.dp_horizon_rows(im)-gt).mean())
for k,v in res.items(): print(k, 'median MAE px', round(np.median(v),2), 'mean', round(np.mean(v),2), 'frac<5px', np.mean(np.array(v)<5))
