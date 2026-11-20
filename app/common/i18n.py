from collections.abc import Mapping

MESSAGES: dict[str, dict[str, str]] = {
    "zh-CN": {
        "COMMON.VALIDATION_ERROR": "请求参数校验失败",
        "COMMON.BAD_REQUEST": "请求无效",
        "COMMON.METHOD_NOT_ALLOWED": "不支持的请求方法",
        "COMMON.NOT_ACCEPTABLE": "无法提供所请求的响应格式",
        "COMMON.NOT_FOUND": "资源不存在",
        "COMMON.CONFLICT": "资源冲突",
        "COMMON.PRECONDITION_FAILED": "前置条件不匹配",
        "COMMON.PRECONDITION_REQUIRED": "缺少前置条件",
        "COMMON.TOO_MANY_REQUESTS": "请求过于频繁",
        "COMMON.PAYLOAD_TOO_LARGE": "请求体过大",
        "COMMON.RANGE_NOT_SATISFIABLE": "请求范围无法满足",
        "COMMON.UNSUPPORTED_MEDIA_TYPE": "不支持的媒体类型",
        "COMMON.INTERNAL_ERROR": "服务器内部错误",
        "AUTH.UNAUTHORIZED": "未认证",
        "AUTH.FORBIDDEN": "无权访问",
        "SYSTEM.DATABASE_UNAVAILABLE": "数据库不可用",
        "SYSTEM.SERVICE_UNAVAILABLE": "依赖服务不可用",
    },
    "en-US": {
        "COMMON.VALIDATION_ERROR": "Request validation failed",
        "COMMON.BAD_REQUEST": "Bad request",
        "COMMON.METHOD_NOT_ALLOWED": "Method not allowed",
        "COMMON.NOT_ACCEPTABLE": "Not acceptable",
        "COMMON.NOT_FOUND": "Resource not found",
        "COMMON.CONFLICT": "Resource conflict",
        "COMMON.PRECONDITION_FAILED": "Precondition failed",
        "COMMON.PRECONDITION_REQUIRED": "Precondition required",
        "COMMON.TOO_MANY_REQUESTS": "Too many requests",
        "COMMON.PAYLOAD_TOO_LARGE": "Payload too large",
        "COMMON.RANGE_NOT_SATISFIABLE": "Requested range is not satisfiable",
        "COMMON.UNSUPPORTED_MEDIA_TYPE": "Unsupported media type",
        "COMMON.INTERNAL_ERROR": "Internal server error",
        "AUTH.UNAUTHORIZED": "Authentication required",
        "AUTH.FORBIDDEN": "Access denied",
        "SYSTEM.DATABASE_UNAVAILABLE": "Database unavailable",
        "SYSTEM.SERVICE_UNAVAILABLE": "Required service unavailable",
    },
}
SUPPORTED = frozenset(MESSAGES)
ALIASES = {"zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN", "en": "en-US", "en-us": "en-US"}


def negotiate_locale(accept_language: str | None, default: str = "zh-CN") -> str:
    options: list[tuple[float, int, str]] = []
    for index, entry in enumerate((accept_language or "").split(",")):
        parts = entry.strip().split(";")
        language = ALIASES.get(parts[0].strip().lower())
        if language is None:
            continue
        quality = 1.0
        for param in parts[1:]:
            if param.strip().lower().startswith("q="):
                try:
                    quality = float(param.strip()[2:])
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            options.append((-quality, index, language))
    if options:
        return min(options)[2]
    return default if default in SUPPORTED else "zh-CN"


def translate(
    code: str, locale: str, fallback: str | None = None, params: Mapping[str, str] | None = None
) -> str:
    template = MESSAGES.get(locale, MESSAGES["zh-CN"]).get(code, fallback or code)
    if params:
        for key, value in params.items():
            template = template.replace("{" + key + "}", value)
    return template
