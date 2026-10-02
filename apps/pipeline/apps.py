from django.apps import AppConfig


class PipelineConfig(AppConfig):
    name = "apps.pipeline"
    verbose_name = "Ingestion pipeline"

    def ready(self) -> None:
        from apps.pipeline import checks  # noqa: F401  (registers the system checks)
