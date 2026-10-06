from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Product(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int
    name: str
    price: float = Field(ge=0)


class Products(BaseModel):
    items: list[Product]


class Summary(BaseModel):
    model_config = ConfigDict(strict=True)
    total_orders: int = Field(ge=0)
    revenue: float = Field(ge=0)


class Inventory(BaseModel):
    model_config = ConfigDict(strict=True)
    sku: str
    available: int = Field(ge=0)


CONTRACTS = {"products": Products, "summary": Summary, "inventory": Inventory}
PATHS = {
    "/products": "products",
    "/orders/summary": "summary",
    "/inventory/SKU-001": "inventory",
}
VARIANTS = {"healthy", "schema-bug", "slow-query", "intermittent-500", "timeout", "high-jitter"}
CONTRACT_VERSION = "1"


def check_contract(name, payload):
    try:
        CONTRACTS[name].model_validate(payload)
        return None
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        return f"{field}: {first['msg']}"
