from pydantic import BaseModel


class MariaDBSettings(BaseModel):
    host: str
    port: int
    database: str
    username: str
    password: str
