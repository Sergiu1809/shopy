"""Catalog field types shared by the admin API and the seed (PATTERN-006, GH-5, GH-6).

`Text`, `Key`, `Sku` and `AttributeValue` are defined here once; `seed/schema.py`
imports them, so the seed and the admin routes accept the same shapes.
"""

from typing import Annotated

from pydantic import StrictBool, StrictInt, StrictStr, StringConstraints

Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Key = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Sku = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z0-9]+(-[A-Z0-9]+)*$")]
AttributeValue = StrictStr | StrictInt | StrictBool | list[StrictStr]
