from typing import ClassVar


class ApiError(Exception):
    http_status: ClassVar[int]
    code: ClassVar[str]


class InvalidRequestError(ApiError):
    http_status = 400
    code = "invalid_request"


class UnauthorizedError(ApiError):
    http_status = 401
    code = "unauthorized"


class CartNotFoundError(ApiError):
    http_status = 404
    code = "cart_not_found"


class CartNotActiveError(ApiError):
    http_status = 409
    code = "cart_not_active"


class PaymentAlreadyStartedError(ApiError):
    http_status = 409
    code = "payment_already_started"


class EmptyCartError(ApiError):
    http_status = 422
    code = "cart_is_empty"


class PaymentMethodNotFoundError(ApiError):
    http_status = 422
    code = "payment_method_not_found"
