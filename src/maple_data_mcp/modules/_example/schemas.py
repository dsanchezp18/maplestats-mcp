from __future__ import annotations

from pydantic import BaseModel

from maple_data_mcp.shared.models import Provenance


class EchoResult(BaseModel):
    message: str
    provenance: Provenance
