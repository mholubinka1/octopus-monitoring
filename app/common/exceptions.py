class APIError(Exception):
    pass


class InfluxDBError(Exception):
    pass


class MariaDBError(Exception):
    pass


class ArgumentError(ValueError):
    pass


class ConfigurationError(Exception):
    pass


class ConfigurationFileError(Exception):
    pass


class NullValueError(ValueError):
    pass
