# PaddleOCR-VL HPS runtime

Production uses PaddleOCR's official high-performance serving appliance. It is
prepared into the ignored `runtime/` directory so SDK archives and model
artifacts are never committed.

Run `backend/scripts/prepare_hps.sh` on the A10 server before the first
production build. The upstream source is pinned to commit
`211989f046cc1878460f9e65574690c00a127a1a`; the defaults are
PaddleOCR-VL-1.6 and PaddleX HPS 3.6.
The official appliance requires an NVIDIA GPU with compute capability 8.x and a
driver supporting CUDA 12.6.

The source layout and request endpoint follow PaddleOCR's official
[`deploy/paddleocr_vl_docker/hps`](https://github.com/PaddlePaddle/PaddleOCR/tree/main/deploy/paddleocr_vl_docker/hps)
appliance. Keep `HPS_PADDLEX_VERSION`, `HPS_TRITON_BASE_IMAGE`, and the SDK
directory on the same release line. Pin `HPS_VLM_IMAGE` to a digest when
promoting a tested production release; its model download cache is stored in
the Compose volume `monkeyocr_hps_model_cache`.
