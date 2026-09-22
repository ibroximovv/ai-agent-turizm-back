from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    verbose_name = "O'quv kontenti"

    def ready(self) -> None:
        from apps.catalog import signals  # noqa: F401  (registers the receivers)
