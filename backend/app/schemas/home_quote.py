"""精确版本估价请求，价格只能由服务端计算。"""

from pydantic import Field
from app.schemas.spatial import SpatialModel


class HomeQuoteRequest(SpatialModel):
    home_version: int = Field(ge=1, strict=True)
    region: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9-]+$")
    client_mutation_id: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")
