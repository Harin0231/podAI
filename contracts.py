from pydantic import BaseModel, Field
from typing import Protocol, Dict, Optional
from time import monotonic

class TokenBucketConfig(BaseModel):
    capacity: int = Field(gt=0, description='Max tokens in bucket')
    refill_rate_per_sec: float = Field(gt=0, description='Tokens added per second')
    key: str = Field(default='global', description='Bucket identity e.g. client IP')

class RateLimitDecision(BaseModel):
    allowed: bool
    remaining_tokens: float
    retry_after_sec: Optional[float] = None
    limit: int
    key: str

class BucketState(BaseModel):
    key: str
    tokens: float
    capacity: int
    refill_rate_per_sec: float
    last_refill_ts: float
    total_consumed: int
    total_rejected: int

class MetricsResponse(BaseModel):
    total_keys: int
    buckets: Dict[str, BucketState]
    total_consumed: int
    total_rejected: int

class TokenBucketProtocol(Protocol):
    config: TokenBucketConfig
    def consume(self, tokens: int = 1, now: float | None = None) -> RateLimitDecision: ...
    def get_state(self) -> BucketState: ...
    def refill(self, now: float | None = None) -> None: ...

class RateLimiterStoreProtocol(Protocol):
    def get_bucket(self, key: str) -> TokenBucketProtocol: ...
    def get_all_states(self) -> Dict[str, BucketState]: ...
    def reset(self, key: str | None = None) -> None: ...

class MetricsProviderProtocol(Protocol):
    def snapshot(self) -> MetricsResponse: ...
