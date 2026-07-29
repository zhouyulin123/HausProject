"""本地效果图生成服务（Stable Diffusion 1.5 + ControlNet MLSD）。

跑在本机 GPU（RTX 5060 8G，实测单张 ~10s、峰值显存 ~3.6GB）。
- 有房间照片：MLSD 提结构线 → ControlNet 重绘，锁住户型换风格
- 无房间照片：纯文生图，根据方案描述凭空生成

懒加载：首次调用才加载模型（约几秒）；之后常驻内存。
GPU 串行：加锁避免并发出图导致显存溢出。
不可用（未装依赖 / 无 GPU / 关闭）时抛 SDUnavailable，由调用方降级。
"""

import io
import logging
import os
import threading
import time
from typing import Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)

# 必须在导入 torch/diffusers 前设置：禁用 Xet（绕过代理会失败）+ 指定缓存目录
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HOME", settings.hf_home)


class SDUnavailable(Exception):
    pass


_lock = threading.Lock()
_loaded = False
_txt_pipe = None  # 文生图
_cn_pipe = None  # ControlNet 重绘
_mlsd = None  # 结构线检测器
_device = "cuda"

_NEG_PROMPT = (
    "lowres, blurry, distorted, deformed, watermark, text, signature, "
    "people, person, ugly, messy, cluttered, oversaturated"
)
_QUALITY_SUFFIX = (
    ", interior design photography, photorealistic, natural lighting, "
    "high detail, 8k, magazine quality"
)


def is_available() -> bool:
    return bool(settings.sd_enabled)


def _load() -> None:
    """懒加载所有模型；共享 UNet/VAE/text_encoder 以省显存。"""
    global _loaded, _txt_pipe, _cn_pipe, _mlsd
    if _loaded:
        return
    if not settings.sd_enabled:
        raise SDUnavailable("SD 效果图生成已关闭（sd_enabled=False）")

    try:
        import torch
        from controlnet_aux import MLSDdetector
        from diffusers import (
            ControlNetModel,
            StableDiffusionControlNetPipeline,
            StableDiffusionPipeline,
        )
    except Exception as exc:  # 依赖未装
        raise SDUnavailable(f"SD 依赖未就绪: {exc}") from exc

    if not torch.cuda.is_available():
        raise SDUnavailable("未检测到可用 CUDA GPU")

    t0 = time.time()
    logger.info("加载 SD 基础模型 %s ...", settings.sd_base_model)
    base = StableDiffusionPipeline.from_pretrained(
        settings.sd_base_model, torch_dtype=torch.float16, safety_checker=None
    ).to(_device)
    base.enable_attention_slicing()
    base.enable_vae_slicing()

    logger.info("加载 ControlNet %s ...", settings.sd_controlnet_model)
    controlnet = ControlNetModel.from_pretrained(
        settings.sd_controlnet_model, torch_dtype=torch.float16
    )
    # 复用基础模型的组件，只额外占用 ControlNet 的显存
    cn = StableDiffusionControlNetPipeline(
        vae=base.vae,
        text_encoder=base.text_encoder,
        tokenizer=base.tokenizer,
        unet=base.unet,
        scheduler=base.scheduler,
        controlnet=controlnet,
        safety_checker=None,
        feature_extractor=None,
        requires_safety_checker=False,
    ).to(_device)
    cn.enable_attention_slicing()
    cn.enable_vae_slicing()

    _mlsd = MLSDdetector.from_pretrained("lllyasviel/Annotators")
    _txt_pipe = base
    _cn_pipe = cn
    _loaded = True
    logger.info("SD 模型全部就绪 (%.0fs)", time.time() - t0)


def _fit_size(w: int, h: int, long_side: int = 768) -> Tuple[int, int]:
    """按比例缩放到长边 = long_side，且宽高为 8 的倍数。"""
    if w >= h:
        nw = long_side
        nh = round(long_side * h / w)
    else:
        nh = long_side
        nw = round(long_side * w / h)
    nw = max(384, (nw // 8) * 8)
    nh = max(384, (nh // 8) * 8)
    return nw, nh


def render_effect_image(
    style_prompt: str,
    room_image_bytes: Optional[bytes] = None,
    seed: Optional[int] = None,
) -> Tuple[bytes, str]:
    """生成一张效果图，返回 (PNG 字节, 模式)。模式为 controlnet / text2img。

    style_prompt：方案的风格描述（英文效果更好，中文也可）。
    room_image_bytes：用户上传的房间照片；提供则走 ControlNet 锁结构重绘。
    """
    import torch
    from PIL import Image

    _load()
    prompt = style_prompt.strip() + _QUALITY_SUFFIX
    generator = torch.Generator(_device).manual_seed(
        seed if seed is not None else int(time.time()) % 100000
    )

    with _lock:  # GPU 串行，防止并发爆显存
        try:
            if room_image_bytes:
                src = Image.open(io.BytesIO(room_image_bytes)).convert("RGB")
                w, h = _fit_size(*src.size)
                control = _mlsd(src.resize((w, h)))
                result = _cn_pipe(
                    prompt,
                    image=control,
                    negative_prompt=_NEG_PROMPT,
                    num_inference_steps=25,
                    guidance_scale=7.5,
                    controlnet_conditioning_scale=1.0,
                    width=w,
                    height=h,
                    generator=generator,
                ).images[0]
                mode = "controlnet"
            else:
                result = _txt_pipe(
                    prompt,
                    negative_prompt=_NEG_PROMPT,
                    num_inference_steps=25,
                    guidance_scale=7.5,
                    width=768,
                    height=512,
                    generator=generator,
                ).images[0]
                mode = "text2img"
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise SDUnavailable(f"显存不足: {exc}") from exc
        except Exception as exc:
            raise SDUnavailable(f"效果图生成失败: {exc}") from exc

    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue(), mode
