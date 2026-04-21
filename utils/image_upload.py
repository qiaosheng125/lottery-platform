import io


ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def prepare_uploaded_image(file_storage, max_side: int = 2000):
    """
    Prepare an uploaded image for storage.

    If Pillow is available, the image is resized/compressed to JPEG.
    If Pillow is unavailable, fall back to storing the original bytes so
    image upload still works in minimal environments.
    """
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else "jpg"
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("不支持的图片格式")

    try:
        from PIL import Image as image_module
    except ModuleNotFoundError:
        file_storage.stream.seek(0)
        raw = file_storage.read()
        if not raw:
            raise ValueError("图片文件为空")
        save_ext = "jpg" if ext == "jpeg" else ext
        return io.BytesIO(raw), save_ext

    try:
        image = image_module.open(file_storage.stream).convert("RGB")
        if max(image.width, image.height) > max_side:
            image.thumbnail((max_side, max_side), image_module.LANCZOS)
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=92, optimize=True)
        buf.seek(0)
        return buf, "jpg"
    except Exception as exc:
        raise ValueError(f"图片处理失败: {exc}") from exc
