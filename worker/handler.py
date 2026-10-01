import json, os, subprocess, time
import runpod

VOL = '/runpod-volume'


def handler(job):
    i = job['input']
    job_dir = os.path.join(VOL, i['job'])
    blend = os.path.join(job_dir, i.get('blend', 'scene.blend'))
    scene = i['scene']
    fs, fe = int(i['frame_start']), int(i['frame_end'])
    out = os.path.join(job_dir, 'out', f'{scene}_####')
    cfg = json.dumps({'out': out, 'overrides': i.get('overrides', {})})
    cmd = ['blender', '-b', blend, '-S', scene, '-P', '/app/setup_render.py',
           '-s', str(fs), '-e', str(fe), '-a', '--', cfg]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    log = (p.stdout + p.stderr).splitlines()
    saved = [l.split("Saved: '")[1].rstrip("'") for l in log if "Saved: '" in l]
    if p.returncode != 0 or len(saved) < fe - fs + 1:
        return {'error': f'blender exit {p.returncode}, saved {len(saved)}/{fe - fs + 1}',
                'log_tail': log[-60:]}
    return {'scene': scene, 'frames': [fs, fe], 'seconds': round(time.time() - t0, 1),
            'saved': [os.path.relpath(s, VOL) for s in saved],
            'setup': [l for l in log if l.startswith('[setup]')]}


runpod.serverless.start({'handler': handler})
