def process_bool_attr(value: str | bool | None) -> bool:
    """
    Process a boolean RH attribute.

    RH had (and still may) improperly decode boolean attributes
    stored in the database. This is a helper function to make sure
    that boolean values stored as strings are properly converted.

    Args:
        value: The value to convert

    Returns:
        The boolean status
    """
    if value is None:
        return False
    if isinstance(value, str):
        if value == "1":
            return True
        return False
    return value
