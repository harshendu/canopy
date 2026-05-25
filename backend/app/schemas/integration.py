from pydantic import BaseModel, ConfigDict

from app.models.base import Provider, ReadStrategy, WriteStrategy


class IntegrationSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    provider: Provider
    read_strategy: ReadStrategy
    write_strategy: WriteStrategy
    allow_user_connect: bool


class IntegrationSettingUpdate(BaseModel):
    read_strategy: ReadStrategy | None = None
    write_strategy: WriteStrategy | None = None
    allow_user_connect: bool | None = None
