from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from .base import AdapterError, check_response, identifier, source_base


class BrowserDemoAdapter:
    name = "Demo Browser Calculator"
    description = "Fill the included calculator and extract seven result fields with Playwright."
    fields = ["identifier", "quantity", "unit_price", "discount"]
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
        for key, default, lower, upper in (
            ("quantity", "1", 1, 1000000),
            ("unit_price", "10", 0, 100000000),
            ("discount", "0", 0, 100),
        ):
            try:
                value = Decimal(str(data.get(key) if data.get(key) not in (None, "") else default))
                if not value.is_finite() or not lower <= value <= upper:
                    raise ValueError
            except (ValueError, InvalidOperation):
                raise AdapterError(
                    "invalid",
                    "invalid_parameters",
                    f"{key} must be a finite number between {lower} and {upper}.",
                ) from None

    def execute(self, data, config):
        from playwright.sync_api import Error, TimeoutError, sync_playwright

        self.validate_config(config)
        self.validate_row(data)
        base = source_base()
        origin = urlsplit(base)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(service_workers="block", accept_downloads=False)

                def restrict(route):
                    target = urlsplit(route.request.url)
                    if (target.scheme, target.hostname, target.port) == (
                        origin.scheme,
                        origin.hostname,
                        origin.port,
                    ):
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")

                context.route("**/*", restrict)
                page = context.new_page()
                page.set_default_timeout(15000)
                response = page.goto(
                    f"{base}/calculator?identifier={identifier(data)}&attempt={config.get('_attempt', 1)}",
                    wait_until="domcontentloaded",
                )
                if response is None:
                    raise AdapterError(
                        "transient", "empty_response", "The calculator did not respond."
                    )
                check_response(response.status, response.headers.get("retry-after"))
                for key, default in (
                    ("identifier", ""),
                    ("quantity", "1"),
                    ("unit_price", "10"),
                    ("discount", "0"),
                ):
                    value = data.get(key)
                    page.locator(f"#{key}").fill(str(default if value in (None, "") else value))
                page.locator("#calculate").click()
                page.locator("#results[data-ready='true']").wait_for()
                result = {
                    key: page.locator(f"[data-result='{key}']").inner_text()
                    for key in (
                        "identifier",
                        "quantity",
                        "unit_price",
                        "subtotal",
                        "discount_amount",
                        "tax",
                        "total",
                    )
                }
                context.close()
                browser.close()
                return self.normalize_result(result)
        except TimeoutError:
            raise AdapterError(
                "transient", "browser_timeout", "The calculator timed out."
            ) from None
        except Error:
            raise AdapterError(
                "blocked",
                "browser_unavailable",
                "Browser execution failed. Check Chromium installation and source availability.",
            ) from None

    def normalize_result(self, result):
        return {
            key: str(result[key])
            for key in (
                "identifier",
                "quantity",
                "unit_price",
                "subtotal",
                "discount_amount",
                "tax",
                "total",
            )
        }
