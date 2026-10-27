"""Compatibility layer providing Pydantic v2, pydantic-settings, and Google GenAI types.

If `pydantic`, `pydantic_settings`, or `google-genai` are installed in the active environment,
their native classes are re-exported directly. If running in an air-gapped or minimal sandbox
without third-party wheels installed yet, lightweight drop-in implementations with full field
constraint validation (`ge`, `le`, `gt`, `lt`, `min_length`, `max_length`, `pattern`,
`default_factory`, `model_dump`, `model_validate`, `model_dump_json`) are used transparently.
"""

from __future__ import annotations

import copy
import json
import os
import re
from enum import Enum
from typing import Any, Callable, ClassVar, Dict, Optional, Type, TypeVar, get_type_hints

T = TypeVar("T", bound="BaseModel")

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator  # type: ignore
    HAS_NATIVE_PYDANTIC = True
except ImportError:  # pragma: no cover
    HAS_NATIVE_PYDANTIC = False

    class ValidationError(ValueError):
        """Raised when model validation fails."""

    class _FieldInfo:
        def __init__(
            self,
            default: Any = ...,
            *,
            default_factory: Optional[Callable[[], Any]] = None,
            description: Optional[str] = None,
            ge: Optional[float] = None,
            le: Optional[float] = None,
            gt: Optional[float] = None,
            lt: Optional[float] = None,
            min_length: Optional[int] = None,
            max_length: Optional[int] = None,
            pattern: Optional[str] = None,
        ) -> None:
            self.default = default
            self.default_factory = default_factory
            self.description = description
            self.ge = ge
            self.le = le
            self.gt = gt
            self.lt = lt
            self.min_length = min_length
            self.max_length = max_length
            self.pattern = re.compile(pattern) if pattern is not None else None

        def get_default(self) -> Any:
            if self.default_factory is not None:
                return self.default_factory()
            return copy.deepcopy(self.default)

        def validate(self, name: str, value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if self.ge is not None and value < self.ge:
                    raise ValidationError(f"Field '{name}'={value} must be >= {self.ge}")
                if self.le is not None and value > self.le:
                    raise ValidationError(f"Field '{name}'={value} must be <= {self.le}")
                if self.gt is not None and value <= self.gt:
                    raise ValidationError(f"Field '{name}'={value} must be > {self.gt}")
                if self.lt is not None and value >= self.lt:
                    raise ValidationError(f"Field '{name}'={value} must be < {self.lt}")
            if isinstance(value, (str, list, tuple, dict, set)):
                if self.min_length is not None and len(value) < self.min_length:
                    raise ValidationError(
                        f"Field '{name}' length {len(value)} must be >= {self.min_length}"
                    )
                if self.max_length is not None and len(value) > self.max_length:
                    raise ValidationError(
                        f"Field '{name}' length {len(value)} must be <= {self.max_length}"
                    )
            if isinstance(value, str) and self.pattern is not None:
                if not self.pattern.search(value):
                    raise ValidationError(
                        f"Field '{name}'='{value}' does not match pattern '{self.pattern.pattern}'"
                    )
            return value

    def Field(  # noqa: N802
        default: Any = ...,
        *,
        default_factory: Optional[Callable[[], Any]] = None,
        description: Optional[str] = None,
        ge: Optional[float] = None,
        le: Optional[float] = None,
        gt: Optional[float] = None,
        lt: Optional[float] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
    ) -> Any:
        return _FieldInfo(
            default=default,
            default_factory=default_factory,
            description=description,
            ge=ge,
            le=le,
            gt=gt,
            lt=lt,
            min_length=min_length,
            max_length=max_length,
            pattern=pattern,
        )

    def field_validator(*fields: str, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            setattr(fn, "__validator_fields__", fields)
            return fn

        return decorator

    def _coerce_nested(annotation: Any, val: Any) -> Any:
        if val is None:
            return None
        origin = getattr(annotation, "__origin__", None)
        args = getattr(annotation, "__args__", ())
        if origin is list and args and isinstance(val, list):
            return [_coerce_nested(args[0], item) for item in val]
        if origin is dict and len(args) == 2 and isinstance(val, dict):
            return {k: _coerce_nested(args[1], v) for k, v in val.items()}
        if origin is not None and args:
            # Handle Optional[T] / Union[T, None]
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return _coerce_nested(non_none[0], val)
        if isinstance(annotation, type):
            if issubclass(annotation, BaseModel):
                if isinstance(val, annotation):
                    return val
                if isinstance(val, dict):
                    return annotation.model_validate(val)
                raise ValidationError(f"Expected {annotation.__name__} or dict, got {type(val).__name__}")
            if issubclass(annotation, Enum):
                if isinstance(val, annotation):
                    return val
                try:
                    return annotation(val)
                except ValueError as exc:
                    raise ValidationError(str(exc)) from exc
        return val

    class BaseModel:
        """Drop-in Pydantic v2 BaseModel fallback for offline/minimal environments."""

        __field_Constraint_cache__: ClassVar[Dict[str, _FieldInfo]] = {}

        def __init__(self, **data: Any) -> None:
            cls = self.__class__
            annotations = getattr(cls, "__annotations__", {})
            try:
                resolved_hints = get_type_hints(cls)
            except Exception:
                resolved_hints = annotations

            for field_name in annotations:
                if field_name.startswith("_") or field_name == "model_config":
                    continue
                attr = getattr(cls, field_name, ...)
                hint = resolved_hints.get(field_name, annotations.get(field_name))
                if field_name in data:
                    raw_val = data[field_name]
                elif isinstance(attr, _FieldInfo):
                    if attr.default is ... and attr.default_factory is None:
                        raise ValidationError(f"Missing required field: '{field_name}'")
                    raw_val = attr.get_default()
                elif attr is not ...:
                    raw_val = copy.deepcopy(attr)
                else:
                    raise ValidationError(f"Missing required field: '{field_name}'")

                coerced = _coerce_nested(hint, raw_val)
                if isinstance(attr, _FieldInfo):
                    coerced = attr.validate(field_name, coerced)
                setattr(self, field_name, coerced)

            # Set any extra passed fields if not in annotations
            for k, v in data.items():
                if k not in annotations:
                    setattr(self, k, v)

        def model_dump(self, *, mode: str = "python") -> Dict[str, Any]:
            result: Dict[str, Any] = {}
            annotations = getattr(self.__class__, "__annotations__", {})
            for field_name in annotations:
                if field_name.startswith("_") or field_name == "model_config":
                    continue
                val = getattr(self, field_name, None)
                result[field_name] = self._serialize_value(val, mode=mode)
            return result

        @classmethod
        def _serialize_value(cls, val: Any, mode: str = "python") -> Any:
            if isinstance(val, BaseModel):
                return val.model_dump(mode=mode)
            if isinstance(val, Enum):
                return val.value if mode == "json" else val
            if isinstance(val, list):
                return [cls._serialize_value(item, mode=mode) for item in val]
            if isinstance(val, dict):
                return {k: cls._serialize_value(v, mode=mode) for k, v in val.items()}
            return copy.deepcopy(val)

        def model_dump_json(self, *, indent: Optional[int] = None) -> str:
            return json.dumps(self.model_dump(mode="json"), indent=indent)

        def model_copy(self, *, deep: bool = False, update: Optional[Dict[str, Any]] = None) -> Any:
            dumped = self.model_dump()
            if update:
                dumped.update(update)
            copied = self.__class__.model_validate(dumped)
            return copy.deepcopy(copied) if deep else copied

        @classmethod
        def model_validate(cls: Type[T], obj: Any) -> T:
            if isinstance(obj, cls):
                return obj
            if isinstance(obj, dict):
                return cls(**obj)
            raise ValidationError(f"Cannot validate {type(obj).__name__} as {cls.__name__}")

        @classmethod
        def model_validate_json(cls: Type[T], json_str: str) -> T:
            return cls.model_validate(json.loads(json_str))

        def __eq__(self, other: Any) -> bool:
            if not isinstance(other, self.__class__):
                return False
            return self.model_dump() == other.model_dump()

        def __repr__(self) -> str:
            fields_str = ", ".join(f"{k}={v!r}" for k, v in self.model_dump().items())
            return f"{self.__class__.__name__}({fields_str})"


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore
except ImportError:  # pragma: no cover
    def SettingsConfigDict(**kwargs: Any) -> Dict[str, Any]:  # noqa: N802
        return kwargs

    class BaseSettings(BaseModel):
        """Drop-in BaseSettings reading environment variables over defaults."""

        model_config: ClassVar[Dict[str, Any]] = {}

        def __init__(self, **values: Any) -> None:
            annotations = getattr(self.__class__, "__annotations__", {})
            merged: Dict[str, Any] = {}
            for field_name, field_type in annotations.items():
                if field_name.startswith("_") or field_name == "model_config":
                    continue
                if field_name in values:
                    merged[field_name] = values[field_name]
                    continue
                env_val = os.environ.get(field_name.upper())
                if env_val is not None:
                    if field_type in (bool, "bool"):
                        merged[field_name] = env_val.lower() in ("1", "true", "yes")
                    elif field_type in (int, "int"):
                        merged[field_name] = int(env_val)
                    elif field_type in (float, "float"):
                        merged[field_name] = float(env_val)
                    else:
                        merged[field_name] = env_val
            super().__init__(**merged)


try:
    from google.genai import types as genai_types  # type: ignore
except ImportError:  # pragma: no cover
    class _HarmCategory(str, Enum):
        HARM_CATEGORY_HATE_SPEECH = "HARM_CATEGORY_HATE_SPEECH"
        HARM_CATEGORY_HARASSMENT = "HARM_CATEGORY_HARASSMENT"
        HARM_CATEGORY_DANGEROUS_CONTENT = "HARM_CATEGORY_DANGEROUS_CONTENT"
        HARM_CATEGORY_SEXUALLY_EXPLICIT = "HARM_CATEGORY_SEXUALLY_EXPLICIT"

    class _HarmBlockThreshold(str, Enum):
        BLOCK_LOW_AND_ABOVE = "BLOCK_LOW_AND_ABOVE"
        BLOCK_MEDIUM_AND_ABOVE = "BLOCK_MEDIUM_AND_ABOVE"

    class _SafetySetting(BaseModel):
        category: _HarmCategory
        threshold: _HarmBlockThreshold

    class _GenerateContentConfig(BaseModel):
        temperature: float = 0.0
        safety_settings: list[_SafetySetting] = Field(default_factory=list)

    class _GenAITypesNamespace:
        HarmCategory = _HarmCategory
        HarmBlockThreshold = _HarmBlockThreshold
        SafetySetting = _SafetySetting
        GenerateContentConfig = _GenerateContentConfig

    genai_types = _GenAITypesNamespace()  # type: ignore
