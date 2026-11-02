import logging
import os
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout,)

logger = logging.getLogger("model-downloader")

def required_environment_variable(name: str) -> str:
    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(f"Обязательная перменная окружения {name} не задана.")

    return value.strip()

def main() -> None:
    repository = required_environment_variable("MODEL_REPOSITORY")
    revision = required_environment_variable("MODEL_REVISION")
    model_path = Path(required_environment_variable("MODEL_PATH"))

    complete_marker = model_path / ".complete"
    config_file = model_path / "config.json"

    if complete_marker.is_file() and config_file.is_file():
        logging.info("Модель уже присутствует в хранилище; "
                     "Загрузка модели пропущена.")
        return

    logger.info("Начало загрузки модели: репозиторий=%s версия=%s путь=%s",
                repository, revision, model_path,)

    model_path.mkdir(parents=True, exist_ok=True)

    token = os.getenv("HF_TOKEN") or None

    snapshot_download(repo_id=repository, revision=revision,
                      local_dir=str(model_path), token=token,)

    if not config_file.is_file():
        raise RuntimeError("Загрузка модели завершена, но config.json не найден.")

    complete_marker.write_text(f"репозиторий={repository}\nверсия={revision}\n",
                               encoding="utf-8",)

    logger.info("Загрузка модели завершилась успешно.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Загрузка модели не удалась.")
        raise

