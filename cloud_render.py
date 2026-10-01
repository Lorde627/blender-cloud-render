#!/Users/a627/pr/blender-cloud-render/.venv/bin/python
"""Render a .blend on RunPod Serverless GPUs.

  ./cloud_render.py setup                         # one-time: volume + template + endpoint
  ./cloud_render.py render scene.blend --scene Pass_Pro2:samples=384,denoise=1 \
        --scene Pass_SeedCard:samples=128,denoise=0 --frames 1-120 --res 1080 --out ./frames
  ./cloud_render.py status | teardown
"""
import argparse, json, os, subprocess, sys, tempfile, time, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3, requests
from boto3.s3.transfer import TransferConfig

HERE = Path(__file__).resolve().parent
STATE = HERE / 'state.json'
IMAGE = 'ghcr.io/lorde627/blender-runpod:5.1.2'
DATACENTER = 'EU-RO-1'
GPU_TYPES = ['NVIDIA GeForce RTX 4090', 'NVIDIA RTX PRO 4500 Blackwell',
             'NVIDIA RTX PRO 4000 Blackwell', 'NVIDIA RTX A4500', 'NVIDIA L4']
LOCAL_BLENDER = '/opt/homebrew/bin/blender'
REST = 'https://rest.runpod.io/v1'
RUN = 'https://api.runpod.ai/v2'


def load_env():
    for line in (HERE / '.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())


def api(method, url, **kw):
    r = requests.request(method, url, headers={'Authorization': f"Bearer {os.environ['RUNPOD_API_KEY']}"},
                         timeout=60, **kw)
    if r.status_code >= 400:
        sys.exit(f'{method} {url} -> {r.status_code}: {r.text[:500]}')
    return r.json() if r.text else {}


def s3(state):
    return boto3.client('s3', endpoint_url=f"https://s3api-{state['datacenter'].lower()}.runpod.io",
                        region_name=state['datacenter'],
                        aws_access_key_id=os.environ['RUNPOD_S3_ACCESS_KEY'],
                        aws_secret_access_key=os.environ['RUNPOD_S3_SECRET_KEY'])


def load_state():
    if not STATE.exists():
        sys.exit('Not set up yet: run ./cloud_render.py setup')
    return json.loads(STATE.read_text())


def cmd_setup(a):
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    st['datacenter'] = DATACENTER
    if 'volume_id' not in st:
        v = api('POST', f'{REST}/networkvolumes', json={'name': 'blender-render', 'size': a.volume_gb,
                                                         'dataCenterId': DATACENTER})
        st['volume_id'] = v['id']
        print('network volume', v['id'])
    if a.endpoint_id:  # endpoint deployed from GitHub in the RunPod console
        st['endpoint_id'] = a.endpoint_id
    if a.volume_only or 'endpoint_id' in st:
        STATE.write_text(json.dumps(st, indent=2))
        print('ready:', json.dumps(st))
        return
    if 'template_id' not in st:
        body = {'name': f'blender-{uuid.uuid4().hex[:6]}', 'imageName': IMAGE, 'isServerless': True,
                'containerDiskInGb': 20}
        if a.registry_auth:
            body['containerRegistryAuthId'] = a.registry_auth
        t = api('POST', f'{REST}/templates', json=body)
        st['template_id'] = t['id']
        print('template', t['id'])
    if 'endpoint_id' not in st:
        e = api('POST', f'{REST}/endpoints', json={
            'name': 'blender-render', 'templateId': st['template_id'], 'gpuTypeIds': GPU_TYPES,
            'networkVolumeId': st['volume_id'], 'dataCenterIds': [DATACENTER],
            'workersMin': 0, 'workersMax': a.max_workers, 'idleTimeout': 5,
            'executionTimeoutMs': 3600_000, 'flashboot': True})
        st['endpoint_id'] = e['id']
        print('endpoint', e['id'])
    STATE.write_text(json.dumps(st, indent=2))
    print('ready:', json.dumps(st))


def cmd_status(a):
    st = load_state()
    print(json.dumps(st, indent=2))
    print(json.dumps(api('GET', f"{RUN}/{st['endpoint_id']}/health"), indent=2))


def cmd_teardown(a):
    st = load_state()
    for kind, key in [('endpoints', 'endpoint_id'), ('templates', 'template_id'), ('networkvolumes', 'volume_id')]:
        if key in st:
            api('DELETE', f'{REST}/{kind}/{st[key]}')
            print('deleted', kind, st.pop(key))
    STATE.write_text(json.dumps(st, indent=2))


def parse_scene(spec):
    name, _, opts = spec.partition(':')
    ov = {}
    for kv in filter(None, opts.split(',')):
        k, v = kv.split('=')
        ov[k] = bool(int(v)) if k == 'denoise' else int(v)
    return name, ov


def pack_copy(blend):
    """Pack all external images/HDRIs into a temp copy so the worker needs nothing else."""
    out = Path(tempfile.mkdtemp()) / 'scene.blend'
    # Missing files are already missing locally, so the render matches; just report them.
    expr = ("import bpy\n"
            "try: bpy.ops.file.pack_all()\n"
            "except RuntimeError as e: print('[pack] warning:', e)\n"
            f"bpy.ops.wm.save_as_mainfile(filepath={str(out)!r}, copy=True, compress=True)")
    p = subprocess.run([LOCAL_BLENDER, '-b', str(blend), '--python-expr', expr],
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith('[pack]'):
            print(line)
    if not out.exists():
        sys.exit(f'pack failed:\n{p.stdout[-2000:]}{p.stderr[-2000:]}')
    return out


def cmd_render(a):
    st = load_state()
    cli = s3(st)
    bucket, ep = st['volume_id'], st['endpoint_id']
    job = f"jobs/{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    t0 = time.time()

    packed = pack_copy(Path(a.blend).resolve())
    mb = packed.stat().st_size / 1e6
    print(f'[upload] {mb:.0f} MB -> {job}/scene.blend')
    cli.upload_file(str(packed), bucket, f'{job}/scene.blend',
                    Config=TransferConfig(multipart_chunksize=64 * 1024 * 1024))

    fs, fe = map(int, a.frames.split('-'))
    tasks = []
    for spec in a.scene:
        name, ov = parse_scene(spec)
        if a.res:
            ov.setdefault('res', a.res)
        for s in range(fs, fe + 1, a.chunk):
            tasks.append({'job': job, 'scene': name, 'frame_start': s,
                          'frame_end': min(s + a.chunk - 1, fe), 'overrides': ov})
    print(f'[submit] {len(tasks)} chunks to endpoint {ep}')

    def run(task, attempt=1):
        rid = api('POST', f'{RUN}/{ep}/run', json={'input': task})['id']
        while True:
            time.sleep(4)
            r = api('GET', f'{RUN}/{ep}/status/{rid}')
            if r['status'] in ('COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'):
                break
        out = r.get('output') or {}
        tag = f"{task['scene']} {task['frame_start']}-{task['frame_end']}"
        if r['status'] != 'COMPLETED' or 'error' in out:
            print(f'[fail] {tag}: {r["status"]} {out.get("error", r.get("error"))}')
            if attempt < 2:
                return run(task, attempt + 1)
            print('\n'.join(out.get('log_tail', [])[-20:]))
            return False
        print(f"[done] {tag} in {out['seconds']}s  {' '.join(out.get('setup', []))}")
        return True

    with ThreadPoolExecutor(len(tasks)) as ex:
        ok = all(ex.map(run, tasks))

    dest = Path(a.out).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    keys = [o['Key'] for p in cli.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=f'{job}/out/')
            for o in p.get('Contents', [])]
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda k: cli.download_file(bucket, k, str(dest / Path(k).name)), keys))
    print(f'[download] {len(keys)} files -> {dest}')

    if not a.keep:
        for k in keys + [f'{job}/scene.blend']:
            cli.delete_object(Bucket=bucket, Key=k)
    print(f'[total] {time.time() - t0:.0f}s, {"OK" if ok else "SOME CHUNKS FAILED"}')
    sys.exit(0 if ok else 1)


def main():
    load_env()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('setup')
    s.add_argument('--volume-gb', type=int, default=20)
    s.add_argument('--max-workers', type=int, default=5)
    s.add_argument('--registry-auth', help='RunPod container registry auth id (private image)')
    s.add_argument('--endpoint-id', help='use an endpoint created in the console (GitHub deploy)')
    s.add_argument('--volume-only', action='store_true', help='only create the network volume')
    sub.add_parser('status')
    sub.add_parser('teardown')
    r = sub.add_parser('render')
    r.add_argument('blend')
    r.add_argument('--scene', action='append', required=True, help='NAME[:samples=N,denoise=0|1,res=N]')
    r.add_argument('--frames', required=True, help='e.g. 1-120')
    r.add_argument('--chunk', type=int, default=24, help='frames per worker request')
    r.add_argument('--res', type=int, help='square resolution override')
    r.add_argument('--out', required=True)
    r.add_argument('--keep', action='store_true', help='keep files on the volume')
    a = p.parse_args()
    {'setup': cmd_setup, 'status': cmd_status, 'teardown': cmd_teardown, 'render': cmd_render}[a.cmd](a)


if __name__ == '__main__':
    main()
