# Runs inside Blender (-P) before rendering: GPU device, overrides, output path.
import bpy, json, sys
cfg = json.loads(sys.argv[sys.argv.index('--') + 1])
prefs = bpy.context.preferences.addons['cycles'].preferences
for backend in ('OPTIX', 'CUDA'):
    try:
        prefs.compute_device_type = backend
        prefs.get_devices()
        gpus = [d for d in prefs.devices if d.type == backend]
        if gpus:
            for d in prefs.devices:
                d.use = d.type == backend
            print(f'[setup] backend={backend} devices={[d.name for d in gpus]}')
            break
    except TypeError:
        continue
sc = bpy.context.scene
sc.cycles.device = 'GPU'
o = cfg.get('overrides', {})
if 'res' in o:
    sc.render.resolution_x = sc.render.resolution_y = o['res']
    sc.render.resolution_percentage = 100
if 'resolution' in o:
    sc.render.resolution_x, sc.render.resolution_y = o['resolution']
    sc.render.resolution_percentage = 100
if 'samples' in o:
    sc.cycles.samples = o['samples']
if 'denoise' in o:
    sc.cycles.use_denoising = o['denoise']
sc.render.use_persistent_data = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA' if sc.render.film_transparent else 'RGB'
sc.render.filepath = cfg['out']
