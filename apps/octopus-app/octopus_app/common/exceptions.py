class APIError(Exception):
    pass


class InfluxDBError(Exception):
    pass


class ArgumentError(ValueError):
    pass


class ConfigurationFileError(Exception):
    pass


class NullValueError(ValueError):
    pass
