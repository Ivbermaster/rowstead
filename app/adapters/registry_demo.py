import httpx

from .base import AdapterError, check_response, identifier, source_base


class RegistryDemoAdapter:
    name = "Demo Registry API"
    description = "Enrich identifiers from the included deterministic registry."
    fields = ["identifier"]
    version = "1"

    def validate_config(self, config):
        source_base()
        if config.get("url") or config.get("base_url"):
            raise AdapterError(
                "blocked",
                "custom_source_disabled",
                "Demo adapters use only the operator-configured source.",
            )

    def validate_row(self, data):
        identifier(data)

    def execute(self, data, config):
        self.validate_config(config)
        self.validate_row(data)
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                response = client.get(
                    f"{source_base()}/api/registry/{identifier(data)}",
                    headers={"X-Batchflow-Attempt": str(config.get("_attempt", 1))},
                )
        except httpx.TransportError:
            raise AdapterError(
                "transient", "network_error", "The source request timed out or could not connect."
            ) from None
        check_response(response.status_code, response.headers.get("retry-after"))
        try:
            return self.normalize_result(response.json())
        except (ValueError, KeyError, TypeError):
            raise AdapterError(
                "permanent", "invalid_response", "The source returned an unexpected response."
            ) from None

    def normalize_result(self, result):
        return {
            key: result[key]
            for key in (
                "identifier",
                "company_name",
                "country",
                "industry",
                "employees",
                "active",
                "risk_score",
            )
        }
