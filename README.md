# blender-cloud-render

Render `.blend` files on RunPod Serverless GPUs with one command.

- `Dockerfile` + `worker/`: the serverless worker image (Blender 5.1.2 Linux + RunPod handler).
  RunPod builds it from this repo; a new GitHub **release** triggers a rebuild.
- `cloud_render.py`: local client. Packs the .blend, uploads it to the network volume over
  the S3 API, fans frame chunks out to the endpoint, downloads the PNGs and cleans up.

## Credentials

`.env` (git-ignored):

```
RUNPOD_API_KEY=...
RUNPOD_S3_ACCESS_KEY=...
RUNPOD_S3_SECRET_KEY=...
```

## Usage

```
./cloud_render.py render scene.blend \
    --scene Pass_Pro2:samples=384,denoise=1 --scene Pass_SeedCard:samples=128,denoise=0 \
    --frames 1-120 --res 1080 --out ~/Downloads/frames
./cloud_render.py status
```

`--scene NAME[:samples=N,denoise=0|1,res=N]` may be repeated; `--chunk` sets frames per request
(default 24). Endpoint/volume ids live in `state.json`.
