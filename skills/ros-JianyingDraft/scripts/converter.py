#!/usr/bin/env python3
"""Convert explicit edit plans. No editing decisions, rendering, or existing-draft merge."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from decimal import Decimal, ROUND_HALF_UP

COMMIT = 'c3318066d964744e2bfc66f75c71745fe8cea52a'
class PlanError(ValueError): pass

def require(ok, message):
    if not ok: raise PlanError(message)

def keys(obj, allowed, required, context):
    require(isinstance(obj, dict), f'{context}: expected object')
    require(not (set(obj)-set(allowed)), f'{context}: unsupported fields {sorted(set(obj)-set(allowed))}')
    require(not (set(required)-set(obj)), f'{context}: missing fields {sorted(set(required)-set(obj))}')

def number(value, context, minimum=0):
    require(isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=minimum, f'{context}: invalid number')
    return value

def us(value):
    number(value, 'time')
    return int((Decimal(str(value))*1000000).quantize(Decimal(1), rounding=ROUND_HALF_UP))

def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def probe(path, kind):
    if kind=='image':
        from PIL import Image
        try:
            with Image.open(path) as image:
                require(getattr(image,'n_frames',1)==1,'animated images require upstream video material')
                image.verify()
        except (OSError,SyntaxError) as e:raise PlanError(f'asset declared image is not a readable still image: {path}') from e
    p=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True)
    require(p.returncode==0, f'cannot probe media: {path}: {p.stderr[-300:]}')
    d=json.loads(p.stdout); streams=d['streams']
    video=next((s for s in streams if s['codec_type']=='video'),None)
    audio=next((s for s in streams if s['codec_type']=='audio'),None)
    require(video is not None if kind in ('video','image') else audio is not None, f'{path}: stream type mismatch')
    duration=0 if kind=='image' else us(float(d.get('format',{}).get('duration') or (video or audio).get('duration',0)))
    require(kind=='image' or duration>0, f'{path}: missing duration')
    return dict(duration_us=duration,width=(video or {}).get('width',0),height=(video or {}).get('height',0),has_audio=audio is not None)

TRANSFORM={'alpha','rotation','scale_x','scale_y','transform_x','transform_y','flip_horizontal','flip_vertical'}
STYLE={'size','color','alpha','align','bold','italic','underline','vertical','letter_spacing','line_spacing','auto_wrapping','max_line_width'}

def validate_transform(t):
    keys(t,TRANSFORM,[], 'transform')
    for k,v in t.items():
        if k.startswith('flip_'): require(isinstance(v,bool),f'{k}: expected boolean')
        else:
            require(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v), f'{k}: invalid value')
            if k=='alpha':require(0<=v<=1,'alpha must be 0..1')
            if k.startswith('scale_'):require(v>0,'scale must be positive')

def validate_style(t):
    keys(t,STYLE,['size','color','align'],'text style')
    number(t['size'],'text size',0.001)
    require(t['align'] in (0,1,2),'align must be 0,1,2')
    require(isinstance(t['color'],list) and len(t['color'])==3,'color must be RGB 0..1')
    for x in t['color']:require(0<=number(x,'color')<=1,'color must be 0..1')
    for k in ('alpha','max_line_width'):
        if k in t:require(0<=number(t[k],k)<=1,f'{k} must be 0..1')
    for k in ('bold','italic','underline','vertical','auto_wrapping'):
        if k in t:require(isinstance(t[k],bool),f'{k} must be boolean')
    for k in ('letter_spacing','line_spacing'):
        if k in t:number(t[k],k)

def normalize(plan_path, path_map=None):
    p=load(plan_path); keys(p,{'schema_version','name','canvas','assets','tracks','subtitle_sync'}, {'schema_version','name','canvas','assets','tracks'},'plan')
    require(p['schema_version']==1,'unsupported schema_version')
    require(isinstance(p.get('subtitle_sync',True),bool),'subtitle_sync must be boolean')
    require(isinstance(p['name'],str) and p['name'].strip() and not any(c in p['name'] for c in '/\\\0') and p['name'] not in ('.','..'),'invalid name')
    c=p['canvas'];keys(c,{'width','height','fps'}, {'width','height','fps'},'canvas')
    require(all(isinstance(c[k],int) and not isinstance(c[k],bool) and c[k]>0 for k in c),'canvas fields must be positive integers')
    require(c['fps'] in (24,25,30,50,60),'v1 fps must be 24,25,30,50,60')
    mapping=load(path_map) if path_map else {};require(isinstance(mapping,dict),'path map must be an object')
    require(isinstance(p['assets'],list) and isinstance(p['tracks'],list) and p['tracks'],'assets/tracks must be lists; tracks cannot be empty')
    deps=[]; assets={}; warnings=[]; hash_cache={}
    for a in p['assets']:
        keys(a,{'id','path','kind','sha256'}, {'id','path','kind'},'asset')
        require(isinstance(a['id'],str) and a['id'] and a['id'] not in assets,'duplicate/invalid asset id')
        require(a['kind'] in ('video','audio','image'),'unsupported asset kind')
        require(isinstance(a['path'],str),'asset path must be string')
        original=Path(a['path']).expanduser()
        if not original.is_absolute():original=Path(plan_path).resolve().parent/original
        original=str(original.resolve()); mapped=mapping.get(original,original)
        require(isinstance(mapped,str),'mapped path must be string')
        actual=Path(mapped).expanduser().resolve()
        require(actual.is_file(),f'missing asset {a["id"]}: {actual}')
        if mapped!=original:require('sha256' in a,'relocation requires original sha256 in plan')
        if str(actual) not in hash_cache:hash_cache[str(actual)]=digest(actual)
        h=hash_cache[str(actual)]
        if 'sha256' in a:require(a['sha256']==h,f'asset identity mismatch: {a["id"]}')
        metadata=dict(id=a['id'],path=str(actual),original_path=original,kind=a['kind'],size_bytes=actual.stat().st_size,sha256=h,**probe(actual,a['kind']))
        deps.append(metadata);assets[a['id']]=metadata
        a['path']=str(actual);a['sha256']=h
    segments={}; names=set(); prepared=[]
    for track in p['tracks']:
        keys(track,{'name','type','segments','subtitle_group'}, {'name','type','segments'},'track')
        require(isinstance(track['name'],str) and track['name'] and track['name'] not in names,'duplicate/invalid track name');names.add(track['name'])
        require(track['type'] in ('video','audio','text','subtitle'),'unsupported track type')
        if 'subtitle_group' in track:require(track['type']=='subtitle' and isinstance(track['subtitle_group'],str) and track['subtitle_group'].strip(),'subtitle_group requires subtitle track and nonempty name')
        require(isinstance(track['segments'],list) and track['segments'],'empty/invalid track segments')
        for s in track['segments']:
            allowed={'id','asset','source_in','source_out','target_start','duration','speed','volume','change_pitch','transform','crop','fade_in','fade_out'} if track['type'] not in ('text','subtitle') else {'id','text','time_basis','start','end','clip_id','style','transform','font','border'}
            required={'id','asset','target_start'} if track['type'] not in ('text','subtitle') else {'id','text','time_basis','start','end','style','transform','font'}
            keys(s,allowed,required,'segment')
            require(isinstance(s['id'],str) and s['id'] and s['id'] not in segments,'duplicate/invalid segment id')
            segments[s['id']]=(track,s)
            if track['type'] in ('text','subtitle'):continue
            require(s['asset'] in assets,f'unknown asset {s["asset"]}');a=assets[s['asset']]
            require((track['type']=='audio')==(a['kind']=='audio'),'track/asset kind mismatch')
            start=us(s['target_start'])
            if a['kind']=='image':
                require('duration' in s,'image duration required');dur=us(s['duration']);source=0;speed=1
                require(not set(s)&{'source_in','source_out','speed','volume','change_pitch','fade_in','fade_out'},'image cannot specify audio/source timing')
            else:
                require({'source_in','source_out','speed','volume'}<=set(s),'media needs source_in/source_out/speed/volume')
                require('duration' not in s,'media target duration is calculated from source and speed')
                source=us(s['source_in']);end=us(s['source_out']);speed=number(s['speed'],'speed',0.000001)
                require(source<end<=a['duration_us'],f'source range exceeds asset: {s["id"]}')
                dur=round((end-source)/speed);number(s['volume'],'volume')
                if not a['has_audio']:require(s['volume']==0,'silent source must explicitly use volume=0')
                require(isinstance(s.get('change_pitch',False),bool),'change_pitch must be boolean')
            require(dur>0,'duration must be positive')
            validate_transform(s.get('transform',{}))
            if track['type']=='audio':require(not set(s)&{'transform','crop'},'audio has no image transform')
            if 'crop' in s:
                r=s['crop'];require(isinstance(r,list) and len(r)==4,'crop=[left,top,right,bottom]')
                require(all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in r),'invalid crop values')
                require(0<=r[0]<r[2]<=1 and 0<=r[1]<r[3]<=1,'crop outside 0..1')
            fi=us(s.get('fade_in',0));fo=us(s.get('fade_out',0));require(fi+fo<=dur,'audio fades exceed segment duration')
            prepared.append(dict(id=s['id'],track=track['name'],type=track['type'],asset=a['id'],target_start_us=start,duration_us=dur,source_start_us=source,source_duration_us=dur if a['kind']=='image' else end-source,speed=speed))
    by_id={s['id']:s for s in prepared}
    for track,s in segments.values():
        if track['type'] not in ('text','subtitle'):continue
        require(isinstance(s['text'],str) and s['text'],'text must be nonempty string')
        require(s['time_basis'] in ('timeline','source'),'text time_basis must be timeline or source')
        start=us(s['start']);end=us(s['end']);require(end>start,'invalid text range')
        if s['time_basis']=='source':
            require(s.get('clip_id') in by_id,'source text requires a media clip_id')
            clip=by_id[s['clip_id']];require(assets[clip['asset']]['kind']!='image','source text cannot reference a still image')
            require(clip['source_start_us']<=start<end<=clip['source_start_us']+clip['source_duration_us'],'source text crosses clip cut: provide explicit split/text decisions')
            start=clip['target_start_us']+round((start-clip['source_start_us'])/clip['speed']);end=clip['target_start_us']+round((end-clip['source_start_us'])/clip['speed'])
        else:require('clip_id' not in s,'timeline text must not specify clip_id')
        require(end>start,'text duration collapses after speed mapping')
        validate_style(s['style']);validate_transform(s['transform']);require(isinstance(s['font'],str) and s['font'],'font must be system or upstream FontType name')
        if 'border' in s:
            keys(s['border'],{'width','color','alpha'},{'width','color'},'border')
            require(0<=number(s['border']['width'],'border width')<=100,'border width out of range')
            validate_style(dict(size=1,align=0,color=s['border']['color'],alpha=s['border'].get('alpha',1)))
        prepared.append(dict(id=s['id'],track=track['name'],type=track['type'],target_start_us=start,duration_us=end-start,text=s['text']))
    for t in p['tracks']:
        ordered=sorted((x for x in prepared if x['track']==t['name']),key=lambda x:x['target_start_us'])
        for a,b in zip(ordered,ordered[1:]):require(a['target_start_us']+a['duration_us']<=b['target_start_us'],f'overlap within track {t["name"]}: specify separate layers; input not changed')
    for s in prepared:
        for key in ('target_start_us','duration_us'):
            remainder=abs(s[key]*c['fps']/1e6-round(s[key]*c['fps']/1e6))
            if remainder>0.0001:warnings.append(f'{s["id"]}.{key}: off frame grid; exact microsecond timing retained')
    used={s['asset'] for s in prepared if 'asset' in s}
    for d in deps:d['used_on_timeline']=d['id'] in used
    return p,deps,prepared,warnings

def material_id(value):return uuid.uuid5(uuid.NAMESPACE_URL,'jdc:'+value).hex

def build(plan_path,output,path_map=None):
    import pyJianYingDraft as jy
    from mac_adapter import adapt
    output=Path(output).resolve();require(not output.exists(),f'output already exists: {output}')
    output.parent.mkdir(parents=True,exist_ok=True)
    try:p,deps,prepared,warnings=normalize(plan_path,path_map)
    except (PlanError,FileNotFoundError) as e:
        output.mkdir();shutil.copyfile(plan_path,output/'input-plan.json');dump(output/'validation.json',dict(status='blocked',errors=[str(e)],app_verified=False));raise
    stage=Path(tempfile.mkdtemp(prefix='.jdc-',dir=output.parent))
    dump(stage/'conversion-plan.json',p);dump(stage/'dependencies.json',deps);dump(stage/'segment-map.json',prepared)
    try:
        script=jy.ScriptFile(p['canvas']['width'],p['canvas']['height'],p['canvas']['fps'],False)
        metadata={d['id']:d for d in deps};objects={};info={s['id']:s for s in prepared}
        for t in p['tracks']:
            script.append_track(jy.TrackSpec(getattr(jy.TrackType,'text' if t['type']=='subtitle' else t['type']),t['name']))
            for s in t['segments']:
                n=info[s['id']];tr=jy.Timerange(n['target_start_us'],n['duration_us'])
                if t['type'] in ('text','subtitle'):
                    font=None if s['font']=='system' else jy.FontType.from_name(s['font'])
                    obj=jy.TextSegment(s['text'],tr,font=font,style=jy.TextStyle(**s['style']),clip_settings=jy.ClipSettings(**s['transform']),border=jy.TextBorder(**s['border']) if 'border' in s else None)
                else:
                    a=metadata[s['asset']];cache=(a['id'],json.dumps(s.get('crop')))
                    if cache not in objects:
                        if t['type']=='audio':m=jy.AudioMaterial(a['path'])
                        else:
                            kwargs={}
                            if 'crop' in s:
                                l,top,r,b=s['crop'];kwargs['crop_settings']=jy.CropSettings(upper_left_x=l,upper_left_y=top,upper_right_x=r,upper_right_y=top,lower_left_x=l,lower_left_y=b,lower_right_x=r,lower_right_y=b)
                            m=jy.VideoMaterial(a['path'],**kwargs)
                        m.material_id=material_id(str(cache));objects[cache]=m
                        if a['kind']!='image':require(abs(m.duration-a['duration_us'])<=100000,f'media parser duration mismatch: {a["id"]}')
                    m=objects[cache]
                    kwargs=dict(source_timerange=jy.Timerange(n['source_start_us'],n['source_duration_us']),speed=n['speed'],volume=s.get('volume',0),change_pitch=s.get('change_pitch',False))
                    if t['type']=='video':kwargs['clip_settings']=jy.ClipSettings(**s.get('transform',{}))
                    obj=(jy.AudioSegment if t['type']=='audio' else jy.VideoSegment)(m,tr,**kwargs)
                    if s.get('fade_in',0) or s.get('fade_out',0):obj.add_fade(us(s.get('fade_in',0)),us(s.get('fade_out',0)))
                obj.segment_id=material_id(s['id']);script.add_segment(obj,t['name'])
        draft=stage/'draft';draft.mkdir();script.dump(str(draft/'draft_content.json'))
        meta_template=load(Path(jy.__file__).parent/'assets/draft_meta_info.json')
        meta_template['draft_id']=str(uuid.uuid4()).upper();dump(draft/'draft_meta_info.json',meta_template)
        raw=load(draft/'draft_content.json');raw['id']=uuid.uuid4().hex.upper();raw['name']=p['name']
        from subtitle_material import apply_subtitle_materials
        subtitle_groups=apply_subtitle_materials(raw,p)
        dump(draft/'draft_content.json',raw)
        adapt(draft,p['name'],output/'draft',deps)
        dump(stage/'conversion-plan.json',p);dump(stage/'dependencies.json',deps);dump(stage/'segment-map.json',prepared)
        report=dict(status='structure_passed',app_verified=False,upstream_commit=COMMIT,canvas=p['canvas'],duration_us=max(x['target_start_us']+x['duration_us'] for x in prepared),segments=len(prepared),subtitle_groups=subtitle_groups,warnings=warnings,media_mode='reference',unsupported_effects_policy='block',editable_media='native trim/transform; supplied rendered media remains a single media element')
        dump(stage/'validation.json',report)
        dump(stage/'generated-files.json',{f.name:digest(f) for f in draft.iterdir() if f.is_file()})
        stage.rename(output);verify(output);return report
    except Exception as e:
        if stage.exists():
            dump(stage/'validation.json',dict(status='blocked',errors=[str(e)],app_verified=False));stage.rename(output)
        elif output.exists():dump(output/'validation.json',dict(status='blocked',errors=[str(e)],app_verified=False))
        raise

def verify(output):
    output=Path(output);report=load(output/'validation.json');require(report['status']=='structure_passed','bundle build did not pass')
    for filename,h in load(output/'generated-files.json').items():require(digest(output/'draft'/filename)==h,f'generated file changed: {filename}; regeneration cannot overwrite human changes')
    for d in load(output/'dependencies.json'):
        q=Path(d['path']);require(q.is_file(),f'missing media: {q}');require(q.stat().st_size==d['size_bytes'] and digest(q)==d['sha256'],f'media changed: {q}')
    raw=load(output/'draft/draft_content.json');wanted=load(output/'segment-map.json');actual={s['id']:s for t in raw['tracks'] for s in t['segments']}
    plan=load(output/'conversion-plan.json');asset_paths={a['id']:a['path'] for a in plan['assets']}
    require([(t['name'],t['type']) for t in raw['tracks']]==[(t['name'],'text' if t['type']=='subtitle' else t['type']) for t in plan['tracks']],'track order/type changed')
    originals={s['id']:s for t in plan['tracks'] for s in t['segments']}
    for t,pt in zip(raw['tracks'],plan['tracks']):
        require({s['id'] for s in t['segments']}=={material_id(s['id']) for s in pt['segments']},'segment assigned to wrong track')
    require(len(actual)==len(wanted),'segment count mismatch')
    materials={m['id']:m for entries in raw['materials'].values() if isinstance(entries,list) for m in entries if isinstance(m,dict) and 'id' in m}
    for x in wanted:
        s=actual[material_id(x['id'])];require(s['target_timerange']=={'start':x['target_start_us'],'duration':x['duration_us']},f'target range mismatch {x["id"]}')
        require(s['material_id'] in materials,'unresolved material')
        original=originals[x['id']];mat=materials[s['material_id']]
        if x['type'] in ('text','subtitle'):
            content=json.loads(mat['content']);require(content['text']==x['text'],'text changed')
            st=content['styles'][0];style=original['style']
            require(st['size']==style['size'] and st['fill']['content']['solid']['color']==style['color'] and mat['alignment']==style['align'],'text style changed')
            for key in ('bold','italic','underline'):require(st[key]==style.get(key,False),f'text {key} changed')
            require(mat['global_alpha']==style.get('alpha',1),'text alpha changed')
            require(mat['force_apply_line_max_width']==style.get('auto_wrapping',False),'text wrapping changed')
            require(mat['line_max_width']==style.get('max_line_width',0.82),'text wrapping width changed')
            require(mat['typesetting']==int(style.get('vertical',False)),'text direction changed')
            require(abs(mat['letter_spacing']-style.get('letter_spacing',0)*0.05)<1e-9 and abs(mat['line_spacing']-(0.02+style.get('line_spacing',0)*0.05))<1e-9,'text spacing changed')
            if original['font']=='system':require('font' not in st,'system font changed')
            else:
                import pyJianYingDraft as jy
                require(st['font']['id']==jy.FontType.from_name(original['font']).value.resource_id,'font changed')
            if 'border' in original:
                b=original['border'];stroke=st['strokes'][0]
                require(stroke['content']['solid']['color']==b['color'] and abs(stroke['width']-b['width']/100*0.2)<1e-9,'text border changed')
        else:
            require(s['source_timerange']=={'start':x['source_start_us'],'duration':x['source_duration_us']},'source range changed')
            require(mat['path']==asset_paths[x['asset']],'source file binding changed')
            require(s['speed']==x['speed'] and s['volume']==original.get('volume',0),'speed/volume changed')
            require(s['is_tone_modify']==original.get('change_pitch',False),'pitch setting changed')
            fades=[materials[r] for r in s.get('extra_material_refs',[]) if r in materials and materials[r].get('type')=='audio_fade']
            if original.get('fade_in',0) or original.get('fade_out',0):
                require(len(fades)==1 and fades[0]['fade_in_duration']==us(original.get('fade_in',0)) and fades[0]['fade_out_duration']==us(original.get('fade_out',0)),'audio fades changed')
            if 'crop' in original:
                l,top,r,b=original['crop'];require(mat['crop']==dict(upper_left_x=l,upper_left_y=top,upper_right_x=r,upper_right_y=top,lower_left_x=l,lower_left_y=b,lower_right_x=r,lower_right_y=b),'crop changed')
        if x['type']!='audio':
            tr=original.get('transform',{});clip=s['clip']
            for k,default in [('alpha',1),('rotation',0)]:require(clip[k]==tr.get(k,default),f'transform {k} changed')
            for k,group,axis,default in [('scale_x','scale','x',1),('scale_y','scale','y',1),('transform_x','transform','x',0),('transform_y','transform','y',0),('flip_horizontal','flip','horizontal',False),('flip_vertical','flip','vertical',False)]:require(clip[group][axis]==tr.get(k,default),f'transform {k} changed')
    require(raw['duration']==report['duration_us'],'duration mismatch')
    from subtitle_material import verify_subtitle_materials
    verify_subtitle_materials(raw,plan)
    return dict(status='structure_passed',app_verified=False,segments=len(actual))

def install_bundle(output,root=None,compatibility_trial=False):
    from mac_adapter import adapt,install
    output=Path(output).resolve();verify(output)
    apps=[]
    for folder in (Path('/Applications'),Path.home()/'Applications'):
        for path in folder.glob('*.app'):
            try:
                info=plistlib.loads((path/'Contents/Info.plist').read_bytes())
                if info.get('CFBundleIdentifier')=='com.lemon.lvpro':apps.append((path,info.get('CFBundleShortVersionString')))
            except (OSError,plistlib.InvalidFileException):pass
    require(len(apps)==1,'cannot uniquely identify domestic Jianying com.lemon.lvpro')
    require(apps[0][1] in ('11.4.0','11.4.2','11.5.0') or compatibility_trial,f'untested application version {apps[0][1]}; use --compatibility-trial only for isolated compatibility evaluation')
    executable=plistlib.loads((apps[0][0]/'Contents/Info.plist').read_bytes())['CFBundleExecutable']
    running=subprocess.run(['pgrep','-f',str(apps[0][0]/'Contents/MacOS'/executable)],capture_output=True,text=True)
    require(running.returncode in (0,1),'cannot inspect application process state; process-list access required')
    require(running.returncode==1,'Jianying main application is running; save and quit before registering a new draft')
    root=Path(root).expanduser().resolve() if root else Path.home()/'Movies/JianyingPro/User Data/Projects/com.lveditor.draft'
    require(root.is_dir(),'draft root missing: provide actual --draft-root')
    plan=load(output/'conversion-plan.json');name=plan['name'];target=root/name
    if target.exists():name=f'{name}_{uuid.uuid4().hex[:8]}';target=root/name
    with tempfile.TemporaryDirectory(prefix='jdc-install-') as tmp:
        staged=Path(tmp)/name;shutil.copytree(output/'draft',staged)
        meta=load(staged/'draft_meta_info.json');meta['draft_id']=str(uuid.uuid4()).upper();dump(staged/'draft_meta_info.json',meta)
        adapt(staged,name,target,load(output/'dependencies.json'))
        result=install(staged,target)
    result.update(application=str(apps[0][0]),application_version=apps[0][1],compatibility_trial=compatibility_trial,app_verified=False)
    dump(output/f'installation-{uuid.uuid4().hex[:8]}.json',result);return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    for action in ('check','build'):
        s=sub.add_parser(action);s.add_argument('plan');s.add_argument('--path-map')
        if action=='build':s.add_argument('--output',required=True)
    for action in ('verify','install'):
        s=sub.add_parser(action);s.add_argument('directory')
        if action=='install':s.add_argument('--draft-root');s.add_argument('--compatibility-trial',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='check':
            p,d,s,w=normalize(args.plan,args.path_map);result=dict(status='input_checked',segments=len(s),assets=len(d),warnings=w)
        elif args.command=='build':result=build(args.plan,args.output,args.path_map)
        elif args.command=='verify':result=verify(args.directory)
        else:result=install_bundle(args.directory,args.draft_root,args.compatibility_trial)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as e:
        print(json.dumps(dict(status='blocked',error=str(e),error_type=type(e).__name__),ensure_ascii=False),file=sys.stderr);return 2
    return 0

if __name__=='__main__':sys.exit(main())
