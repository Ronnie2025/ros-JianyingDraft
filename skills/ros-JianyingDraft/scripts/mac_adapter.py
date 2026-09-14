"""Stage and install NEW Mac Jianying drafts; never patch app-saved projects.

Based on the 2026-09-08 compatibility fixture: duplicate the public timeline
as draft_info.json, register media in meta type 0, and prepend a root entry.
The 5.4.0 platform value is a compatibility schema value, NOT app detection.
App opening/saving/export must be verified separately for every target version.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return value


def _write(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise ValueError(f'Refuse symlink: {path}')
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _relocate(value, old: Path, new: Path):
    if isinstance(value, dict):
        return {k: _relocate(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_relocate(v, old, new) for v in value]
    if isinstance(value, str):
        if value == str(old) or value.startswith(str(old) + '/'):
            return str(new) + value[len(str(old)):]
        # Text styles store font paths inside JSON-encoded strings.
        if value.startswith(('{', '[')):
            try:
                return json.dumps(_relocate(json.loads(value), old, new), ensure_ascii=False)
            except (ValueError, TypeError):
                pass
    return value


def adapt(draft_dir: Path, draft_name: str, final_dir: Path,
          asset_metadata: list) -> dict:
    """Adapt a fresh generated draft in place, referencing external originals.

    Assets: id, path (absolute), kind (video/audio/image/photo), duration_us,
    width, height. Metadata IDs are retained in the media browser. Source files
    are not copied. Paths already inside staging are relocated for installation.
    Refuses a differing/encoded draft_info or app timeline directory.
    """
    draft_dir, final_dir = Path(draft_dir).resolve(), Path(final_dir).resolve()
    if not draft_dir.is_dir() or not draft_name or '/' in draft_name:
        raise ValueError('Existing staging directory and plain draft name required')
    if final_dir == draft_dir or final_dir.is_relative_to(draft_dir):
        raise ValueError('Final directory must be outside staging')
    content = _read(draft_dir / 'draft_content.json')
    entry = draft_dir / 'draft_info.json'
    if (draft_dir / 'Timelines').exists():
        raise ValueError('App timeline detected; adapt only newly generated drafts')
    if entry.exists() and _read(entry) != content:
        raise ValueError('draft_info differs from draft_content; refusing stale overwrite')
    meta_path = draft_dir / 'draft_meta_info.json'
    meta = _read(meta_path) if meta_path.exists() else {}
    now = time.time_ns() // 1000
    draft_id = str(meta.get('draft_id') or uuid.uuid4()).upper()
    records, size, seen = [], 0, set()
    for a in asset_metadata:
        path = Path(a['path'])
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f'Absolute existing source required: {path}')
        if not a.get('id') or a['id'] in seen:
            raise ValueError('Asset IDs must be present and unique')
        seen.add(a['id'])
        kind = {'video': 'video', 'audio': 'music', 'image': 'photo', 'photo': 'photo'}.get(a['kind'])
        if kind is None:
            raise ValueError(f'Unsupported media kind: {a["kind"]}')
        duration = int(a.get('duration_us', 0))
        if duration < 0:
            raise ValueError('Negative source duration')
        records.append(dict(create_time=now // 1_000_000, duration=duration,
                            extra_info=path.name, file_Path=str(path),
                            height=int(a.get('height', 0)), width=int(a.get('width', 0)),
                            id=str(uuid.uuid5(uuid.NAMESPACE_URL,'jdc-browser:'+str(path))).upper(), import_time=now // 1_000_000,
                            import_time_ms=now, item_source=1, md5='', metetype=kind,
                            roughcut_time_range={'duration': -1, 'start': -1},
                            sub_time_range={'duration': -1, 'start': -1}, type=0))
        size += path.stat().st_size
    for key in ('platform', 'last_modified_platform'):
        content.setdefault(key, {}).update(os='mac', app_version='5.4.0',
            device_id='', hard_disk_id='', mac_address='')
    content['name'] = draft_name
    meta.update(draft_id=draft_id, draft_name=draft_name,
                draft_fold_path=str(final_dir), draft_root_path=str(final_dir.parent),
                draft_cover=str(final_dir / 'draft_cover.jpg') if (draft_dir / 'draft_cover.jpg').exists() else '',
                tm_draft_create=now, tm_draft_modified=now, tm_draft_removed=0,
                tm_duration=int(content.get('duration', 0)),
                draft_timeline_materials_size_=size,
                draft_materials=[{'type': t, 'value': records if t == 0 else []}
                                 for t in (0, 1, 2, 3, 6, 7, 8)])
    meta.pop('draft_is_ai_translate', None)
    content = _relocate(content, draft_dir, final_dir)
    meta = _relocate(meta, draft_dir, final_dir)
    _write(draft_dir / 'draft_content.json', content)
    _write(draft_dir / 'draft_info.json', content)
    _write(meta_path, meta)
    return {'draft_id': draft_id, 'draft_name': draft_name, 'final_dir': str(final_dir),
            'asset_count': len(records), 'app_open_verified': False}


def install(draft_dir: Path, final_dir: Path, *, root_index: Path | None = None) -> dict:
    """Copy new staged draft and prepend root registration without overwrites.

    Caller must ensure Jianying is closed. Concurrent index writes detected
    before replacement abort registration; the copied draft remains for review.
    Existing index fields and entries are preserved. No implicit default root.
    """
    draft_dir, final_dir = Path(draft_dir).resolve(), Path(final_dir).absolute()
    if final_dir.exists() or final_dir.is_symlink():
        raise FileExistsError(final_dir)
    final_dir = final_dir.resolve()
    if final_dir == draft_dir or final_dir.is_relative_to(draft_dir):
        raise ValueError('Final directory must be outside staging')
    index = Path(root_index).absolute() if root_index else final_dir.parent / 'root_meta_info.json'
    if index.is_symlink() or index.parent.resolve() != final_dir.parent:
        raise ValueError('Root index must be a regular file beside the new draft')
    # Only the newly generated entry pair is installable; app-saved versions
    # may leave a stale plaintext file behind.
    content = _read(draft_dir / 'draft_content.json')
    if _read(draft_dir / 'draft_info.json') != content:
        raise ValueError('Entry/timeline mismatch; refusing stale content installation')
    meta = _read(draft_dir / 'draft_meta_info.json')
    old_final = Path(meta['draft_fold_path'])
    raw = index.read_bytes() if index.exists() else None
    data = json.loads(raw) if raw is not None else {'all_draft_store': [], 'draft_ids': 0, 'root_path': str(final_dir.parent)}
    before = data.get('all_draft_store')
    if not isinstance(before, list) or any(not isinstance(x, dict) for x in before):
        raise ValueError('Invalid root draft list')
    if any(x.get('draft_id') == meta['draft_id'] or x.get('draft_fold_path') == str(final_dir)
           or x.get('draft_name') == meta['draft_name'] for x in before):
        raise FileExistsError('Draft ID, name or path already registered')
    # Reject symlinks rather than unintentionally copying outside source files.
    if any(p.is_symlink() for p in draft_dir.rglob('*')):
        raise ValueError('Staging symlinks are unsupported; use external media references')
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if raw is not None:
        backup = index.with_name(index.name + f'.before_install.{time.time_ns()}.bak')
        with backup.open('xb') as f:
            f.write(raw)
    shutil.copytree(draft_dir, final_dir)  # refuses an existing destination
    # Relocate all plaintext JSON sidecars, including a generation manifest.
    for p in final_dir.rglob('*.json'):
        try:
            obj = _read(p)
        except (ValueError, UnicodeError):
            continue
        obj = _relocate(_relocate(obj, old_final, final_dir), draft_dir, final_dir)
        _write(p, obj)
    meta = _read(final_dir / 'draft_meta_info.json')
    meta['draft_fold_path'] = str(final_dir)
    meta['draft_root_path'] = str(final_dir.parent)
    _write(final_dir / 'draft_meta_info.json', meta)
    entry = dict(cloud_draft_cover=False, cloud_draft_sync=False,
        draft_is_invisible=False, draft_is_cloud_temp_draft=False,
        streaming_edit_draft_ready=True, draft_new_version='', draft_type='',
        draft_id=meta['draft_id'], draft_name=meta['draft_name'],
        draft_fold_path=str(final_dir), draft_root_path=str(final_dir.parent),
        draft_json_file=str(final_dir / 'draft_info.json'), draft_cover=meta.get('draft_cover', ''),
        draft_timeline_materials_size=meta.get('draft_timeline_materials_size_', 0),
        tm_duration=meta['tm_duration'], tm_draft_create=meta['tm_draft_create'],
        tm_draft_modified=meta['tm_draft_modified'], tm_draft_removed=0)
    updated = copy.deepcopy(data)
    updated['all_draft_store'] = [entry] + before
    # Preserve draft_ids: the native field is a counter, not a list/count.
    fd, tmp = tempfile.mkstemp(prefix='.root_meta_install_', dir=index.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(updated, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        current = index.read_bytes() if index.exists() else None
        if current != raw:
            raise RuntimeError(f'Root index changed concurrently; unregistered draft retained at {final_dir}')
        os.replace(tmp, index)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {'installed_path': str(final_dir), 'draft_id': meta['draft_id'],
            'previous_projects_preserved': len(before),
            'index_backup': str(backup) if backup else None, 'app_open_verified': False}
