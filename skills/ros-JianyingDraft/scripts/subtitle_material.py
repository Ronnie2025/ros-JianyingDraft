"""Native caption metadata, independent from timeline clip grouping.

Schema reference: aoguai/pyJianYingDraft, Apache-2.0,
commit 4a7730c9a14e91aa497e723c85b5c433a62a163c, text_segment.py
and _script_file_segments.py. Project adaptation preserves caller styles.
"""
import uuid

def rgb_hex(rgb):
    return '#'+''.join(f'{max(0,min(255,round(v*255))):02X}' for v in rgb)

def apply_subtitle_materials(raw,plan):
    materials={m['id']:m for m in raw['materials']['texts']}
    raw['config']['subtitle_sync']=plan.get('subtitle_sync',True)
    groups={}; result=[]
    for track,native in zip(plan['tracks'],raw['tracks']):
        if track['type'] not in ('text','subtitle'):continue
        originals={uuid.uuid5(uuid.NAMESPACE_URL,'jdc:'+s['id']).hex:s for s in track['segments']}
        for segment in native['segments']:
            original=originals[segment['id']];mat=materials[segment['material_id']]
            # The pinned library uses wrapping to choose text/subtitle and
            # hard-codes this flag to false. Preserve explicit role and wrapping.
            mat['type']=track['type']
            mat['force_apply_line_max_width']=original['style'].get('auto_wrapping',False)
        if track['type']!='subtitle':continue
        key=track.get('subtitle_group',track['name'])
        if key not in groups:groups[key]=f'import_{uuid.uuid4().int}'
        group=groups[key]
        for segment in native['segments']:
            original=originals[segment['id']];mat=materials[segment['material_id']]
            style=original['style'];border=original.get('border')
            mat.update(type='subtitle',add_type=2,sub_type=0,group_id=group,
                       layer_weight=1,recognize_type=0,recognize_task_id='',recognize_text='',
                       relevance_segment=[],is_rich_text=False,is_lyric_effect=False,is_words_linear=False,
                       words=dict(end_time=[],start_time=[],text=[]),
                       current_words=dict(end_time=[],start_time=[],text=[]),
                       font_size=float(style['size']),text_size=round(style['size']*6),
                       text_color=rgb_hex(style['color']),text_alpha=style.get('alpha',1.0),
                       background_style=0,background_color='',has_shadow=False,
                       border_width=(border['width']/100*0.2 if border else 0),
                       border_color=(rgb_hex(border['color']) if border else ''),
                       border_alpha=(border.get('alpha',1.0) if border else 1.0))
        result.append(dict(track=track['name'],group=key,material_group_id=group,count=len(native['segments'])))
    return result

def verify_subtitle_materials(raw,plan):
    """Check caption identities and batch boundaries independently of file hashes."""
    sync=raw.get('config',{}).get('subtitle_sync')
    if not isinstance(sync,bool) or sync != plan.get('subtitle_sync',True):
        raise ValueError('subtitle_sync changed')
    mats={m['id']:m for m in raw['materials']['texts']}
    native_by_name={t['name']:t for t in raw['tracks']}
    group_ids={}; used_groups={}
    for track in plan['tracks']:
        if track['type'] not in ('text','subtitle'):continue
        originals={uuid.uuid5(uuid.NAMESPACE_URL,'jdc:'+s['id']).hex:s for s in track['segments']}
        for seg in native_by_name[track['name']]['segments']:
            mat=mats[seg['material_id']];original=originals[seg['id']]
            if track['type']=='text':
                if mat.get('type')!='text' or mat.get('group_id') or mat.get('add_type')==2:
                    raise ValueError('ordinary text was enrolled into caption linkage')
                continue
            if any(mat.get(k)!=v for k,v in dict(type='subtitle',add_type=2,sub_type=0,layer_weight=1,recognize_type=0).items()):
                raise ValueError('native subtitle metadata missing or changed')
            group=mat.get('group_id');key=track.get('subtitle_group',track['name'])
            if not isinstance(group,str) or not group.startswith('import_') or len(group)==7:
                raise ValueError('native subtitle group missing')
            if key in group_ids and group_ids[key]!=group:
                raise ValueError('same subtitle batch split into different groups')
            if group in used_groups and used_groups[group]!=key:
                raise ValueError('different subtitle batches merged')
            group_ids[key]=group;used_groups[group]=key
            style=original['style'];border=original.get('border')
            expected=dict(font_size=float(style['size']),text_size=round(style['size']*6),
                          text_color=rgb_hex(style['color']),text_alpha=style.get('alpha',1),
                          border_color=rgb_hex(border['color']) if border else '',
                          border_alpha=border.get('alpha',1) if border else 1,
                          border_width=border['width']/100*0.2 if border else 0)
            if any(mat.get(k)!=v for k,v in expected.items()):
                raise ValueError('subtitle UI style differs from input')
