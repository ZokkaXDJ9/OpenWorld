from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect


def encode(row) -> dict:
    return jsonable_encoder(
        {
            column.key: (
                value.replace(tzinfo=UTC)
                if isinstance(value, datetime) and value.tzinfo is None
                else value
            )
            for column in inspect(type(row)).columns
            for value in [getattr(row, column.key)]
        }
    )
